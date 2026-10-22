"""
WhatsApp messages to customers about their orders (task 2.3, D-135 to D-139).

- A status change queues a message (services._move calls after_move): please
  confirm (with Yes and No buttons), confirmed, final price (Yes and No),
  ready, out for delivery, cancelled by the shop. Each one can be switched off
  in the business's settings. Messages are in English for now (D-138).
- The worker sends it (tasks.send_order_message). Inside the 24-hour window
  (the customer wrote in the last 24 hours) it is a normal message with reply
  buttons, which needs no approval from Meta; outside the window it is the
  approved template named in the settings (D-136).
- Answers (D-137): pressing a button, or typing yes / no when exactly one
  question is open in that chat.
    please confirm + Yes  -> Confirmed (every customer rule applies: slots,
                             areas, stock). If a rule stops it: back to Draft
                             and the customer is told staff will call.
    please confirm + No   -> back to Draft; staff see it on the order.
    final price + Yes     -> Final price accepted.
    final price + No      -> back to Being prepared; staff see it (D-139).
- Questions close when the order moves on, so an old button can never change
  a newer order state.
- No message text is stored here: the text is made when it is sent and kept
  only in the inbox (which forgets it when the customer's data is removed).
"""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.inbox import services as inbox

from .models import CustomerMessageSettings, Order, OrderMessage

log = logging.getLogger(__name__)
K = OrderMessage.Kind
M = OrderMessage.Status
S = Order.Status

SETTING = {
    K.CONFIRM_REQUEST: "ask_to_confirm", K.CONFIRMED: "on_confirmed", K.FINAL_PRICE: "on_final_price",
    K.READY: "on_ready", K.OUT_FOR_DELIVERY: "on_out_for_delivery", K.CANCELLED: "on_cancelled",
}
TEMPLATE_FIELD = {
    K.CONFIRM_REQUEST: "template_confirm_request", K.CONFIRMED: "template_confirmed", K.FINAL_PRICE: "template_final_price",
    K.READY: "template_ready", K.OUT_FOR_DELIVERY: "template_out_for_delivery", K.CANCELLED: "template_cancelled",
}
# A question is only answered while the order is still in this status.
QUESTIONS = {K.CONFIRM_REQUEST: S.AWAITING, K.FINAL_PRICE: S.FINAL_SENT}
BUTTONS = {K.CONFIRM_REQUEST: ("Yes, confirm", "No"), K.FINAL_PRICE: ("Yes, accept", "No")}
YES_WORDS = {"yes", "y", "yeah", "yep", "yes please", "ok", "okay", "confirm", "accept", "ho", "hunchha", "huncha", "हो", "हुन्छ"}
NO_WORDS = {"no", "n", "nope", "no thanks", "hoina", "haina", "hoeina", "होइन", "हैन"}
# Notes on the order when a customer says No (warnings() shows them to staff).
SAID_NO = "Customer said No on WhatsApp"
SAID_NO_PRICE = "Customer said No to the final price"
COULD_NOT_CONFIRM = "Customer said Yes on WhatsApp, but the order could not be confirmed"

# The templates to create in Meta (category Utility, language English). {{n}} are the parameters.
TEMPLATES = {
    K.CONFIRM_REQUEST: "Hello {{1}}, please check your order #{{2}} from {{3}}: {{4}}. {{5}}. Estimated total: ${{6}}. Is this correct?",
    K.CONFIRMED: "Thank you {{1}}. Your order #{{2}} from {{3}} is confirmed. {{4}}. Estimated total: ${{5}}. We will tell you when it is ready.",
    K.FINAL_PRICE: "Hello {{1}}, your order #{{2}} has been weighed. The final price is ${{3}} (estimate: ${{4}}). Do you accept the final price?",
    K.READY: "Hello {{1}}, your order #{{2}} from {{3}} is {{4}}. Total: ${{5}}. See you soon!",
    K.OUT_FOR_DELIVERY: "Hello {{1}}, your order #{{2}} from {{3}} is on the way. Total: ${{4}}. Thank you!",
    K.CANCELLED: "Hello {{1}}, sorry, your order #{{2}} from {{3}} was cancelled. Reason: {{4}}. Please contact us if you have questions.",
}


def current_settings() -> CustomerMessageSettings:
    return CustomerMessageSettings.objects.get_or_create(pk=1)[0]


def whatsapp_connected() -> bool:
    from apps.vault.models import Connection

    return Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).exists()


# ---------------------------------------------------------------------------
# Queueing (inside the status change's transaction)
# ---------------------------------------------------------------------------
def after_move(order: Order, from_status: str, to_status: str, note: str = "") -> OrderMessage | None:
    """Called by services._move after every status change."""
    OrderMessage.objects.filter(order=order, is_open=True).update(is_open=False)  # old buttons stop working
    kind = None
    if to_status == S.AWAITING:
        kind = K.CONFIRM_REQUEST
    elif to_status == S.CONFIRMED:
        kind = K.CONFIRMED
    elif to_status == S.FINAL_SENT:
        kind = K.FINAL_PRICE
    elif to_status == S.READY and from_status != S.OUT_FOR_DELIVERY:  # not again after a delivery that did not happen
        kind = K.READY
    elif to_status == S.OUT_FOR_DELIVERY:
        kind = K.OUT_FOR_DELIVERY
    elif to_status == S.CANCELLED_SHOP:
        kind = K.CANCELLED
    return queue(order, kind, extra=note) if kind else None


def _skip(order: Order, kind: str, why: str) -> OrderMessage:
    return OrderMessage.objects.create(order=order, kind=kind, status=M.SKIPPED, note=why[:300])


def queue(order: Order, kind: str, *, extra: str = "") -> OrderMessage | None:
    """Queue one message for the worker. Nothing is queued when the message is switched off."""
    if kind != K.REPLY and not getattr(current_settings(), SETTING[kind]):
        return None
    customer = order.customer
    if customer is None or customer.is_anonymised or not customer.phone:
        return _skip(order, kind, "The customer has no phone number. Call or tell them.") if kind in QUESTIONS else None
    if not whatsapp_connected():
        # Staff rely on the questions, so those say why nothing was sent; other messages are just not sent.
        return _skip(order, kind, "WhatsApp is not connected. Call the customer.") if kind in QUESTIONS else None
    message = OrderMessage.objects.create(order=order, kind=kind, status=M.QUEUED, extra=(extra or "")[:300],
                                          token=secrets.token_hex(8) if kind in QUESTIONS else "")
    schema = connection.schema_name

    def start():
        from .tasks import send_order_message

        send_order_message.delay(schema, message.pk)

    transaction.on_commit(start)
    return message


def queue_reply(order: Order, text: str) -> OrderMessage | None:
    """A short answer to the customer after they pressed Yes or No (they just wrote, so the window is open)."""
    return queue(order, K.REPLY, extra=text)


# ---------------------------------------------------------------------------
# Sending (the worker)
# ---------------------------------------------------------------------------
@dataclass
class Content:
    text: str
    params: list[str] = field(default_factory=list)


def money(value) -> str:
    return f"{value:.2f}"


def _items(order: Order, limit: int = 12) -> list[str]:
    rows = []
    for line in order.lines.all():
        amount = f"{line.quantity.normalize():f}"
        rows.append(f"{amount} kg {line.product_name}" if line.unit == "kg" else f"{amount} x {line.product_name}")
    if len(rows) > limit:
        rows = rows[:limit] + [f"and {len(rows) - limit} more"]
    return rows


def _where_and_when(order: Order) -> str:
    from apps.setup.models import BusinessProfile

    from . import services

    when = services.due_text(order)
    if order.is_delivery:
        place = ", ".join(p for p in (order.delivery_address, order.delivery_suburb) if p)
        return f"Delivery to {place}, {when}" if place else f"Delivery, {when}"
    profile = BusinessProfile.objects.filter(pk=1).first()
    address = ", ".join(p for p in ((profile.address, profile.suburb) if profile else ()) if p)
    return f"Pickup at {address}, {when}" if address else f"Pickup, {when}"


def build(message: OrderMessage) -> Content:
    """The text of a normal message and the parameters of the template, made from the order as it is now."""
    from apps.setup.services import business_name

    order = message.order
    name = (order.customer.name if order.customer else "") or "there"
    shop = business_name()
    n = str(order.number)
    kind = message.kind
    if kind == K.CONFIRM_REQUEST:
        items = _items(order)
        place = _where_and_when(order)
        weigh = "\n(Products sold by weight are weighed when packed, so the final price can change a little.)" if any(
            line.unit == "kg" for line in order.lines.all()) else ""
        text = (f"Hello {name}, please check your order #{n} from {shop}:\n" + "\n".join(f"- {row}" for row in items)
                + f"\n{place}\nEstimated total: ${money(order.estimated_total)}{weigh}\n\nIs this correct?")
        return Content(text, [name, n, shop, ", ".join(items), place, money(order.estimated_total)])
    if kind == K.CONFIRMED:
        place = _where_and_when(order)
        text = (f"Thank you {name}. Your order #{n} from {shop} is confirmed.\n{place}\n"
                f"Estimated total: ${money(order.estimated_total)}\nWe will tell you when it is ready.")
        return Content(text, [name, n, shop, place, money(order.estimated_total)])
    if kind == K.FINAL_PRICE:
        text = (f"Hello {name}, your order #{n} has been weighed. The final price is ${money(order.total)} "
                f"(estimate: ${money(order.estimated_total)}).\n\nDo you accept the final price?")
        return Content(text, [name, n, money(order.total), money(order.estimated_total)])
    if kind == K.READY:
        what = "ready for delivery" if order.is_delivery else "ready for pickup"
        paid = " (paid)" if order.is_paid else ""
        text = f"Hello {name}, your order #{n} from {shop} is {what}.\nTotal: ${money(order.total)}{paid}\nSee you soon!"
        return Content(text, [name, n, shop, what, money(order.total)])
    if kind == K.OUT_FOR_DELIVERY:
        paid = " (paid)" if order.is_paid else " (pay on delivery)"
        text = f"Hello {name}, your order #{n} from {shop} is on the way.\nTotal: ${money(order.total)}{paid}\nThank you!"
        return Content(text, [name, n, shop, money(order.total)])
    if kind == K.CANCELLED:
        reason = message.extra or "not given"
        text = (f"Hello {name}, sorry, your order #{n} from {shop} was cancelled.\nReason: {reason}\n"
                "Please contact us if you have questions.")
        return Content(text, [name, n, shop, reason])
    return Content(message.extra)  # K.REPLY


def _payload(message: OrderMessage, answer: str) -> str:
    return f"order:{message.pk}:{message.token}:{answer}"


def _still_wanted(message: OrderMessage) -> str:
    """Why the message should no longer be sent ("" = send it)."""
    order = message.order
    if message.kind in QUESTIONS and order.status != QUESTIONS[message.kind]:
        return "The order moved on before the message was sent."
    if message.kind in (K.CONFIRMED, K.READY, K.OUT_FOR_DELIVERY) and order.status in (S.CANCELLED_CUSTOMER, S.CANCELLED_SHOP, S.EXPIRED):
        return "The order was cancelled before the message was sent."
    customer = order.customer
    if customer is None or customer.is_anonymised or not customer.phone:
        return "The customer has no phone number."
    return ""


@transaction.atomic
def deliver(message: OrderMessage) -> OrderMessage:
    """Send one queued message (safe to call twice: only a queued message is sent)."""
    message = OrderMessage.objects.select_for_update(of=("self",)).select_related("order", "order__customer").get(pk=message.pk)
    if message.status != M.QUEUED:
        return message
    why = _still_wanted(message)
    if why:
        return _finish(message, M.SKIPPED, why)
    try:
        conversation = inbox.conversation_for_customer(message.order.customer)
    except ValidationError as exc:
        return _finish(message, M.SKIPPED, " ".join(exc.messages))
    content = build(message)
    buttons = BUTTONS.get(message.kind)
    try:
        if inbox.can_reply_freely(conversation):
            via = OrderMessage.Via.MESSAGE
            if buttons:
                sent = inbox.send_buttons(conversation, content.text[:inbox.MAX_BUTTON_TEXT], [
                    (_payload(message, "yes"), buttons[0]), (_payload(message, "no"), buttons[1])])
            else:
                sent = inbox.send_text(conversation, content.text)
        else:
            if message.kind == K.REPLY:
                return _finish(message, M.SKIPPED, "More than 24 hours since the customer's last message.")
            s = current_settings()
            name = getattr(s, TEMPLATE_FIELD[message.kind])
            if not name:
                return _finish(message, M.SKIPPED, "More than 24 hours since the customer's last message, and no template is set "
                                                    "for this message. Call the customer, or set the template in the settings.")
            via = OrderMessage.Via.TEMPLATE
            sent = inbox.send_template(conversation, name=name, language=s.template_language, params=content.params,
                                       buttons=[_payload(message, "yes"), _payload(message, "no")] if buttons else None)
    except ValidationError as exc:
        return _finish(message, M.FAILED, " ".join(exc.messages))
    message.inbox_message = sent
    message.via = via
    if sent.status == sent.Status.FAILED:
        return _finish(message, M.FAILED, sent.error)
    if message.kind in QUESTIONS:
        message.is_open = True
        message.asked_total = message.order.total
    return _finish(message, M.SENT)


def _finish(message: OrderMessage, status: str, note: str = "") -> OrderMessage:
    message.status = status
    message.note = (note or "")[:300]
    message.sent_at = timezone.now() if status == M.SENT else None
    message.save()
    return message


# ---------------------------------------------------------------------------
# Answers (called by the inbox for every incoming message)
# ---------------------------------------------------------------------------
PAYLOAD = re.compile(r"^order:(\d{1,18}):([0-9a-f]{16}):(yes|no)$")


def _word(text: str) -> str:
    return " ".join(re.sub(r"[!.,?\s]+", " ", (text or "").lower()).split())


def on_message_received(sender, message, reply_id: str = "", **kwargs) -> None:
    """Find the question a Yes or No answers, and apply it. Never raises (the message is already stored)."""
    if message.direction != message.Direction.IN:
        return
    try:
        with transaction.atomic():
            _answer(message, reply_id)
    except Exception:  # noqa: BLE001 - an answer must never lose the customer's message
        log.exception("Could not apply a customer's answer")


def _answer(message, reply_id: str) -> None:
    conversation = message.conversation
    match = PAYLOAD.match(reply_id or "")
    if match:
        pk, token, answer = match.groups()
        question = OrderMessage.objects.filter(pk=int(pk), token=token, kind__in=list(QUESTIONS)).select_related("inbox_message").first()
        if question is None or question.inbox_message is None or question.inbox_message.conversation_id != conversation.pk:
            return  # not a button we sent to this chat
        apply_answer(question, answer, pressed=True)
        return
    word = _word(message.text)
    answer = "yes" if word in YES_WORDS else "no" if word in NO_WORDS else ""
    if not answer:
        return
    open_questions = list(OrderMessage.objects.filter(is_open=True, inbox_message__conversation=conversation)[:2])
    if len(open_questions) == 1:  # with two open questions a typed "yes" is not clear: staff answer in the inbox
        apply_answer(open_questions[0], answer, pressed=False)


def apply_answer(question: OrderMessage, answer: str, *, pressed: bool) -> str:
    """Apply Yes or No. Returns what happened (for tests and the log)."""
    from . import services

    question = OrderMessage.objects.select_for_update().get(pk=question.pk)
    order = services._lock(question.order)
    n = order.number
    if not question.is_open or order.status != QUESTIONS[question.kind]:
        if pressed:
            queue_reply(order, f"Thank you. This question about order #{n} was already answered or has changed. "
                               "If something is not right, please send us a message.")
        return "closed"
    question.is_open = False
    question.answer = answer
    question.answered_at = timezone.now()
    question.save(update_fields=["is_open", "answer", "answered_at"])
    if question.kind == K.CONFIRM_REQUEST:
        if answer == "no":
            services.change_status(order, S.DRAFT, note=SAID_NO)
            queue_reply(order, f"OK, order #{n} is not confirmed. We will contact you to change it.")
            return "draft"
        try:
            services.change_status(order, S.CONFIRMED, strict=True, note="Customer said Yes on WhatsApp")
        except ValidationError as exc:
            reasons = " ".join(exc.messages)
            services.change_status(order, S.DRAFT, note=f"{COULD_NOT_CONFIRM}: {reasons}")
            queue_reply(order, f"Sorry, we could not confirm order #{n}: {reasons} We will contact you soon.")
            return "could_not_confirm"
        if not current_settings().on_confirmed:
            queue_reply(order, f"Thank you, order #{n} is confirmed.")
        return "confirmed"
    # K.FINAL_PRICE
    total = money(order.total)
    if question.asked_total is not None and question.asked_total != order.total:
        return "closed"  # cannot happen today (weights change only while preparing), but never accept a price nobody saw
    if answer == "no":
        services.change_status(order, S.PREPARING, note=f"{SAID_NO_PRICE} (${total}) on WhatsApp")
        queue_reply(order, f"OK. Our staff will contact you about order #{n}.")
        return "preparing"
    services.change_status(order, S.FINAL_ACCEPTED, note=f"Customer accepted the final price (${total}) on WhatsApp")
    queue_reply(order, f"Thank you. We will tell you when order #{n} is ready.")
    return "accepted"


def answer_warning(order: Order) -> str:
    """When the customer said No (or Yes could not be applied), tell staff until the order moves on."""
    last = order.events.order_by("-at", "-id").first()
    if last is None or last.actor_id is not None or last.to_status != order.status:
        return ""
    if last.note.startswith((SAID_NO, SAID_NO_PRICE, COULD_NOT_CONFIRM)):
        return f"{last.note}. Call the customer."
    return ""


# ---------------------------------------------------------------------------
# For the order pages
# ---------------------------------------------------------------------------
def status_text(message: OrderMessage) -> str:
    """For example "Read · answered Yes" or "Not sent: WhatsApp is not connected. Call the customer."."""
    if message.status == M.SENT:
        sent = message.inbox_message
        if sent is not None and sent.status == sent.Status.FAILED:
            text = f"Not delivered: {sent.error or 'WhatsApp could not deliver it'}"
        else:
            text = sent.get_status_display() if sent is not None else "Sent"
    elif message.status == M.QUEUED:
        text = "Waiting to send"
    else:
        text = f"Not sent: {message.note}" if message.note else "Not sent"
    if message.answer:
        text += f" · answered {message.get_answer_display()}"
    elif message.is_open:
        text += " · waiting for the answer"
    return text


def label(message: OrderMessage) -> str:
    if message.kind == K.REPLY:
        return f"Answer: {message.extra[:80]}"
    if message.kind == K.CANCELLED and message.extra:
        return f"Cancelled ({message.extra[:60]})"
    return message.get_kind_display()
