"""
WhatsApp Business Platform (Cloud API) adapter.

Incoming: Meta calls https://<business site>/webhooks/whatsapp/
- GET  is the one-time check: we answer hub.challenge when hub.verify_token matches.
- POST carries messages and delivery statuses. We only accept it when the
  X-Hub-Signature-256 header is a valid HMAC-SHA256 of the body with the
  business's app secret, and the phone number id is the business's own.
  We answer 200 quickly; Meta may send the same event more than once.

Outgoing: POST https://graph.facebook.com/<version>/<phone number id>/messages
with the business's access token. Errors never include the token.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

import requests
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.vault import crypto
from apps.vault import services as vault
from apps.vault.models import Connection
from apps.vault.providers import GRAPH_API_VERSION, TIMEOUT

from .models import WebhookDelivery

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com"


def _connection() -> Connection | None:
    return Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).order_by("is_backup", "id").first()


def valid_signature(body: bytes, header: str, app_secret: str) -> bool:
    if not header or not header.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def _record(ok: bool, note: str = "", messages: int = 0, statuses: int = 0) -> None:
    WebhookDelivery.objects.create(ok=ok, note=note[:200], messages=messages, statuses=statuses)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    conn = _connection()
    if conn is None:
        return HttpResponse(status=404)
    if request.method == "GET":
        token = conn.config.get("webhook_verify_token", "")
        if request.GET.get("hub.mode") == "subscribe" and token and constant_time_compare(request.GET.get("hub.verify_token", ""), token):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        _record(False, "Webhook check refused: wrong verify token")
        return HttpResponseForbidden("Wrong verify token")

    try:
        body = request.body
    except RequestDataTooBig:
        _record(False, "Too big")
        return HttpResponse(status=413)
    try:
        app_secret = vault.read_secrets(conn).get("app_secret", "")
    except crypto.VaultError:
        _record(False, "Saved keys could not be opened")
        return HttpResponse(status=503)
    if not valid_signature(body, request.headers.get("X-Hub-Signature-256", ""), app_secret):
        _record(False, "Refused: signature missing or wrong")
        return HttpResponseForbidden("Bad signature")
    try:
        payload = json.loads(body)
    except ValueError:
        _record(False, "Refused: not JSON")
        return HttpResponse(status=400)

    from . import services

    own_number = str(conn.config.get("phone_number_id", ""))
    counts = {"messages": 0, "statuses": 0, "skipped": 0}
    for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if str((value.get("metadata") or {}).get("phone_number_id", "")) != own_number:
                counts["skipped"] += 1  # not this business's number
                continue
            names = {str(c.get("wa_id")): (c.get("profile") or {}).get("name", "") for c in value.get("contacts", []) if isinstance(c, dict)}
            for msg in value.get("messages", []) or []:
                try:
                    if services.receive_whatsapp_message(msg, names.get(str(msg.get("from")), "")):
                        counts["messages"] += 1
                except Exception:  # noqa: BLE001 - one bad item must not lose the others
                    log.exception("Could not store an incoming WhatsApp message")
            for status in value.get("statuses", []) or []:
                try:
                    if services.update_whatsapp_status(status):
                        counts["statuses"] += 1
                except Exception:  # noqa: BLE001
                    log.exception("Could not apply a WhatsApp status")
    note = f"{counts['skipped']} item(s) for another phone number skipped" if counts["skipped"] else ""
    _record(True, note, counts["messages"], counts["statuses"])
    return HttpResponse("ok", content_type="text/plain")


@dataclass
class SendResult:
    ok: bool
    message_id: str = ""
    error: str = ""


def send_message(secrets: dict, config: dict, to: str, payload: dict) -> SendResult:
    version = config.get("graph_api_version") or GRAPH_API_VERSION
    url = f"{GRAPH}/{version}/{config['phone_number_id']}/messages"
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, **payload}
    try:
        response = requests.post(url, json=body, headers={"Authorization": f"Bearer {secrets['access_token']}"}, timeout=TIMEOUT, allow_redirects=False)
    except requests.Timeout:
        return SendResult(False, error="WhatsApp did not answer within 10 seconds. Try again.")
    except requests.RequestException:
        return SendResult(False, error="Could not reach WhatsApp. Check the internet connection.")
    try:
        data = response.json()
    except ValueError:
        data = {}
    if 200 <= response.status_code < 300:
        messages = data.get("messages") or [{}]
        return SendResult(True, message_id=str(messages[0].get("id", ""))[:128])
    error = data.get("error") or {}
    code = error.get("code", response.status_code)
    if code == 131047 or "24 hours" in str(error.get("message", "")):
        return SendResult(False, error="The 24-hour reply window has closed. Send an approved template.")
    if response.status_code in (401, 403) or code == 190:
        return SendResult(False, error="WhatsApp refused the access token. Check it on the Integrations page.")
    return SendResult(False, error=f"WhatsApp refused the message (code {code}).")
