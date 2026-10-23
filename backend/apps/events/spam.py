"""
Spam checks for the public enquiry form (task 3.1, D-173).

- With the business's own Cloudflare Turnstile keys (secret vault, tested and
  working): the form shows the Cloudflare check, and the server asks
  Cloudflare whether the token is real, single-use and for this web address.
- Always: a hidden field people never fill in, a signed time stamp (a form
  sent back within 3 seconds or after 2 hours is refused), and limits per
  visitor address and per business.

Bots that fill in the hidden field get the normal thank-you page, so they
learn nothing; nothing is saved.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from django.core import signing
from django.core.cache import cache
from django.db import connection

from apps.vault import providers as vault_providers

log = logging.getLogger(__name__)

HONEYPOT = "company_website"
SALT = "events.enquiry_form"
MIN_SECONDS = 3
MAX_SECONDS = 2 * 3600
PER_ADDRESS_PER_HOUR = 5
PER_BUSINESS_PER_DAY = 100
TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js"
TURNSTILE_ORIGIN = "https://challenges.cloudflare.com"
VERIFY_TIMEOUT = 8


@dataclass
class Turnstile:
    site_key: str
    secret_key: str


def turnstile() -> Turnstile | None:
    """The business's Turnstile keys, only when the connection was tested and works."""
    from apps.vault import services as vault
    from apps.vault.models import Connection

    conn = (Connection.objects.filter(provider="turnstile", status=Connection.Status.CONNECTED)
            .order_by("is_backup", "id").first())
    if conn is None:
        return None
    site_key = str((conn.config or {}).get("site_key", "")).strip()
    try:
        secret = vault.read_secrets(conn).get("secret_key", "")
    except Exception:  # noqa: BLE001 - a broken vault entry must not break the form
        log.exception("Turnstile secret could not be read")
        return None
    return Turnstile(site_key, secret) if site_key and secret else None


def stamp(now: float | None = None) -> str:
    return signing.dumps({"t": int(now if now is not None else time.time()), "s": connection.schema_name}, salt=SALT)


def stamp_ok(value: str, now: float | None = None) -> bool:
    """The form came from this business's page, between 3 seconds and 2 hours ago."""
    try:
        data = signing.loads(value or "", salt=SALT)
    except signing.BadSignature:
        return False
    if not isinstance(data, dict) or data.get("s") != connection.schema_name:
        return False
    age = (now if now is not None else time.time()) - int(data.get("t", 0))
    return MIN_SECONDS <= age <= MAX_SECONDS


def over_limit(address: str | None) -> bool:
    """Count this send; True when the visitor address or the business has sent too many."""
    schema = connection.schema_name
    keys = [(f"events:form:day:{schema}", PER_BUSINESS_PER_DAY, 86400)]
    if address:
        keys.append((f"events:form:ip:{schema}:{address}", PER_ADDRESS_PER_HOUR, 3600))
    over = False
    for key, limit, timeout in keys:
        cache.add(key, 0, timeout)
        try:
            count = cache.incr(key)
        except ValueError:  # the key ran out between add and incr
            cache.add(key, 1, timeout)
            count = 1
        over = over or count > limit
    return over


def check_turnstile(keys: Turnstile, token: str, *, address: str | None, host: str) -> tuple[bool, str]:
    """Ask Cloudflare. Returns (passed, reason). Refuses when Cloudflare cannot be reached."""
    token = (token or "").strip()
    if not token or len(token) > 2048:
        return False, "missing"
    data = {"secret": keys.secret_key, "response": token}
    if address:
        data["remoteip"] = address
    try:
        response = requests.post(vault_providers.TURNSTILE_VERIFY_URL, data=data, timeout=VERIFY_TIMEOUT, allow_redirects=False)
        body = response.json() if response.ok else {}
    except (requests.RequestException, ValueError):
        log.warning("Turnstile check could not reach Cloudflare")
        return False, "unreachable"
    if body.get("success") is not True:
        return False, ",".join(body.get("error-codes", [])) or "refused"
    if host and body.get("hostname") and body["hostname"].lower() != host.lower():
        return False, "wrong-hostname"
    return True, ""
