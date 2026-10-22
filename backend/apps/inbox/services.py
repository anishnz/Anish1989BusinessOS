"""
Inbox rules: storing incoming messages, sending replies, assigning and closing.

WhatsApp rules (check Meta's current documentation when they change):
- A business can reply freely for 24 hours after the customer's last message
  (the customer service window). After that, only approved templates.
- Marketing messages need the customer's consent; a customer who writes STOP
  is opted out and this is recorded in the consent history.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import logging

import phonenumbers
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.dispatch import Signal
from django.utils import timezone

from apps.audit.services import audit
from apps.customers.models import ConsentRecord, Customer
from apps.customers.services import set_marketing_consent
from apps.vault import services as vault

from . import whatsapp
from .models import Conversation, Message

REPLY_WINDOW = timedelta(hours=24)
MAX_TEXT = 4096
MAX_BUTTON_TEXT = 1024  # body of a message with reply buttons
log = logging.getLogger(__name__)

# Sent after an incoming message is stored (inside the same transaction), with
# message= and reply_id= (the id of the reply button the customer pressed, or "").
# Orders listen to it for Yes and No answers (task 2.3); the inbox knows nothing about orders.
message_received = Signal()
STOP_WORDS = {"STOP", "STOP ALL", "UNSUBSCRIBE", "OPT OUT", "OPTOUT"}
STATUS_ORDER = {Message.Status.QUEUED: 0, Message.Status.SENT: 1, Message.Status.DELIVERED: 2, Message.Status.READ: 3}


# ---------------------------------------------------------------------------
# Incoming
# ---------------------------------------------------------------------------
def _phone_from_wa_id(wa_id: str) -> str:
    try:
        number = phonenumbers.parse("+" + wa_id, None)
        if phonenumbers.is_valid_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return ""


def _when(timestamp) -> datetime:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return timezone.now()


def _content(msg: dict) -> tuple[str, str, str]:
    """(kind, text, media_id) of an incoming WhatsApp message."""
    kind = str(msg.get("type") or "unsupported")[:20]
    if kind == "text":
        return kind, str(msg.get("text", {}).get("body", "")), ""
    if kind == "button":
        return kind, str(msg.get("button", {}).get("text", "")), ""
    if kind == "interactive":
        inter = msg.get("interactive", {})
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return kind, str(reply.get("title", "")), ""
    if kind in ("image", "video", "audio", "document", "sticker"):
        media = msg.get(kind, {}) or {}
        return kind, str(media.get("caption", "") or media.get("filename", "")), str(media.get("id", ""))[:128]
    if kind == "location":
        loc = msg.get("location", {})
        return kind, f"Location: {loc.get('name', '')} {loc.get('latitude', '')},{loc.get('longitude', '')}".strip(), ""
    if kind == "reaction":
        return kind, str(msg.get("reaction", {}).get("emoji", "")), ""
    return "unsupported", "", ""


def _reply_id(msg: dict) -> str:
    """The id we gave the reply button the customer pressed (normal messages and templates), or ""."""
    kind = msg.get("type")
    if kind == "interactive":
        reply = (msg.get("interactive") or {}).get("button_reply") or {}
        return str(reply.get("id", ""))[:256]
    if kind == "button":
        return str((msg.get("button") or {}).get("payload", ""))[:256]
    return ""


def _customer_for(wa_id: str, profile_name: str) -> Customer | None:
    phone = _phone_from_wa_id(wa_id)
    if not phone:
        return None
    customer = Customer.objects.filter(phone=phone).first()
    if customer is not None:
        return customer
    try:
        with transaction.atomic():
            return Customer.objects.create(name=(profile_name or phone)[:150], phone=phone, source=Customer.Source.WHATSAPP)
    except IntegrityError:  # created at the same moment by another delivery
        return Customer.objects.filter(phone=phone).first()


@transaction.atomic
def receive_whatsapp_message(msg: dict, profile_name: str = "") -> Message | None:
    """Store one incoming WhatsApp message. Safe to call twice with the same message (Meta may resend)."""
    provider_id = str(msg.get("id") or "")[:128]
    wa_id = "".join(ch for ch in str(msg.get("from") or "") if ch.isdigit())[:64]
    if not provider_id or not wa_id:
        return None
    if Message.objects.filter(provider_message_id=provider_id).exists():
        return None
    kind, text, media_id = _content(msg)
    when = _when(msg.get("timestamp"))
    conversation = Conversation.objects.select_for_update().filter(channel=Conversation.Channel.WHATSAPP, external_id=wa_id).first()
    if conversation is None:
        conversation = Conversation.objects.create(channel=Conversation.Channel.WHATSAPP, external_id=wa_id, customer=_customer_for(wa_id, profile_name))
    elif conversation.customer is None:
        conversation.customer = _customer_for(wa_id, profile_name)
    message = Message.objects.create(
        conversation=conversation, direction=Message.Direction.IN, kind=kind, text=text[:MAX_TEXT], media_id=media_id,
        provider_message_id=provider_id, status=Message.Status.RECEIVED, provider_timestamp=when,
    )
    conversation.status = Conversation.Status.OPEN
    conversation.unread_count += 1
    conversation.last_message_at = timezone.now()
    conversation.last_inbound_at = max(when, conversation.last_inbound_at) if conversation.last_inbound_at else when
    conversation.last_message_preview = (text or f"[{kind}]")[:120]
    conversation.save()
    if kind in ("text", "button") and text.strip().upper() in STOP_WORDS and conversation.customer and not conversation.customer.is_anonymised:
        set_marketing_consent(conversation.customer, False, source=ConsentRecord.Source.STOP, channel="whatsapp", note="Customer sent STOP on WhatsApp")
    for receiver, result in message_received.send_robust(sender=Message, message=message, reply_id=_reply_id(msg)):
        if isinstance(result, Exception):
            log.error("A listener failed on an incoming WhatsApp message: %s", type(result).__name__)
    return message


@transaction.atomic
def update_whatsapp_status(status: dict) -> Message | None:
    """Apply a delivery status (sent, delivered, read, failed) to a message we sent. Never moves backwards."""
    message = Message.objects.select_for_update().filter(provider_message_id=str(status.get("id") or "")[:128], direction=Message.Direction.OUT).first()
    if message is None:
        return None
    new = str(status.get("status") or "")
    if new == Message.Status.FAILED:
        errors = status.get("errors") or [{}]
        first = errors[0] if isinstance(errors, list) and errors else {}
        message.status = Message.Status.FAILED
        message.error = f"{first.get('code', '')} {first.get('title', '') or first.get('message', '')}".strip()[:300]
    elif new in STATUS_ORDER and message.status != Message.Status.FAILED and STATUS_ORDER[new] > STATUS_ORDER.get(message.status, -1):
        message.status = new
    else:
        return message
    message.save(update_fields=["status", "error"])
    return message


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def can_reply_freely(conversation: Conversation) -> bool:
    return bool(conversation.last_inbound_at and timezone.now() - conversation.last_inbound_at < REPLY_WINDOW)


def _whatsapp_connection():
    from apps.vault.models import Connection

    conn = Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).order_by("is_backup", "id").first()
    if conn is None:
        raise ValidationError("WhatsApp is not connected. Add it on the Integrations page.")
    return conn


def _send(conversation: Conversation, payload: dict, *, text: str, kind: str, template_name: str = "", actor=None, bot: bool = False) -> Message:
    if conversation.channel != Conversation.Channel.WHATSAPP or not conversation.external_id:
        raise ValidationError("This conversation cannot receive messages.")
    if conversation.customer is not None and conversation.customer.is_anonymised:
        raise ValidationError("This customer's personal data was removed.")
    conn = _whatsapp_connection()
    message = Message.objects.create(
        conversation=conversation, direction=Message.Direction.OUT, kind=kind, text=text, template_name=template_name,
        status=Message.Status.QUEUED, sent_by=actor, bot=bot,
    )
    result = whatsapp.send_message(vault.read_secrets(conn), conn.config, conversation.external_id, payload)
    if result.ok:
        message.provider_message_id = result.message_id
        message.status = Message.Status.SENT
    else:
        message.status = Message.Status.FAILED
        message.error = result.error[:300]
    message.save(update_fields=["provider_message_id", "status", "error"])
    conversation.last_message_at = timezone.now()
    conversation.last_message_preview = (text or f"[{kind}]")[:120]
    conversation.save(update_fields=["last_message_at", "last_message_preview"])
    audit("inbox.send", target=conversation, actor=actor, metadata={"kind": kind, "template": template_name, "ok": result.ok})
    return message


def send_text(conversation: Conversation, text: str, *, actor=None, bot: bool = False) -> Message:
    """A normal message (only inside the 24-hour window). `bot`: written by the AI assistant (task 2.4)."""
    text = (text or "").strip()
    if not text:
        raise ValidationError("Write a message.")
    if len(text) > MAX_TEXT:
        raise ValidationError(f"A message can have at most {MAX_TEXT} characters.")
    if not can_reply_freely(conversation):
        raise ValidationError("More than 24 hours have passed since the customer's last message. Send an approved template instead.")
    payload = {"type": "text", "text": {"preview_url": False, "body": text}}
    return _send(conversation, payload, text=text, kind="text", actor=actor, bot=bot)


def send_buttons(conversation: Conversation, text: str, buttons: list[tuple[str, str]], *, actor=None) -> Message:
    """
    A normal message with reply buttons (task 2.3). Only inside the 24-hour
    window. `buttons`: up to 3 (id, title); the id comes back when the customer
    presses the button; titles have at most 20 characters.
    """
    text = (text or "").strip()
    if not text:
        raise ValidationError("Write a message.")
    if len(text) > MAX_BUTTON_TEXT:
        raise ValidationError(f"A message with buttons can have at most {MAX_BUTTON_TEXT} characters.")
    if not 1 <= len(buttons) <= 3 or any(not bid or len(bid) > 256 or not title or len(title) > 20 for bid, title in buttons):
        raise ValidationError("Use 1 to 3 buttons with a title of at most 20 characters.")
    if not can_reply_freely(conversation):
        raise ValidationError("More than 24 hours have passed since the customer's last message. Send an approved template instead.")
    payload = {"type": "interactive", "interactive": {
        "type": "button", "body": {"text": text},
        "action": {"buttons": [{"type": "reply", "reply": {"id": bid, "title": title}} for bid, title in buttons]},
    }}
    shown = text + "\n" + " | ".join(f"[{title}]" for _, title in buttons)
    return _send(conversation, payload, text=shown, kind="buttons", actor=actor)


def send_template(conversation: Conversation, *, name: str, language: str = "en", params: list[str] | None = None,
                  category: str = "utility", buttons: list[str] | None = None, actor=None) -> Message:
    """
    Send an approved WhatsApp template. Marketing templates need the customer's consent.
    `buttons`: the payloads of the template's quick-reply buttons, in order (they come back when pressed).
    """
    import re

    if not re.fullmatch(r"[a-z0-9_]{1,100}", name or ""):
        raise ValidationError("Template names use lower-case letters, numbers and _ (as approved in Meta).")
    if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", language or ""):
        raise ValidationError("Language looks like en or en_US.")
    if category not in ("utility", "marketing", "authentication"):
        raise ValidationError("Category must be utility, marketing or authentication.")
    # Meta refuses parameters with new lines, tabs or more than 4 spaces in a row.
    params = [" ".join(str(p).split())[:1000] or "-" for p in (params or [])][:20]
    buttons = [str(b)[:128] for b in (buttons or [])][:3]
    if category == "marketing":
        customer = conversation.customer
        if customer is None or not customer.marketing_consent:
            raise ValidationError("This customer has not agreed to marketing messages.")
    template = {"name": name, "language": {"code": language}}
    components = []
    if params:
        components.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in params]})
    for index, payload in enumerate(buttons):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(index), "parameters": [{"type": "payload", "payload": payload}]})
    if components:
        template["components"] = components
    preview = f"[template {name}] " + " | ".join(params)
    return _send(conversation, {"type": "template", "template": template}, text=preview, kind="template", template_name=name, actor=actor)


@transaction.atomic
def conversation_for_customer(customer: Customer) -> Conversation:
    """Find or start the WhatsApp conversation with a customer (to send a template first)."""
    if customer.is_anonymised or not customer.phone:
        raise ValidationError("This customer has no phone number.")
    wa_id = customer.phone.lstrip("+")
    conversation, _ = Conversation.objects.get_or_create(channel=Conversation.Channel.WHATSAPP, external_id=wa_id, defaults={"customer": customer})
    return conversation


# ---------------------------------------------------------------------------
# Handling conversations
# ---------------------------------------------------------------------------
def mark_read(conversation: Conversation) -> Conversation:
    conversation.unread_count = 0
    conversation.save(update_fields=["unread_count"])
    return conversation


def assign(conversation: Conversation, user, *, actor=None) -> Conversation:
    if user is not None and not (user.is_active and user.is_staff):
        raise ValidationError("Conversations can only be assigned to active staff.")
    conversation.assigned_to = user
    conversation.save(update_fields=["assigned_to"])
    audit("inbox.assign", target=conversation, actor=actor, metadata={"to": user.email if user else None})
    return conversation


def set_closed(conversation: Conversation, closed: bool, *, actor=None) -> Conversation:
    conversation.status = Conversation.Status.CLOSED if closed else Conversation.Status.OPEN
    if closed:
        conversation.unread_count = 0
    conversation.save(update_fields=["status", "unread_count"])
    audit("inbox.close" if closed else "inbox.reopen", target=conversation, actor=actor)
    return conversation


def forget_customer(sender, customer, **kwargs) -> None:
    """When a customer's personal data is removed, delete their messages and the phone id."""
    for conversation in Conversation.objects.filter(customer=customer):
        conversation.messages.all().delete()
        conversation.external_id = ""
        conversation.last_message_preview = ""
        conversation.status = Conversation.Status.CLOSED
        conversation.unread_count = 0
        conversation.save()
