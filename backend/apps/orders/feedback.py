"""
Star feedback after an order (task 2.7, D-157 and D-158).

- One hour after an order is completed (picked up or delivered), the customer
  is asked once for 1 to 5 stars on WhatsApp. A scheduled job (every 10
  minutes) finds these orders; orders completed more than 24 hours ago are
  never asked.
- Not asked: no customer or phone, WhatsApp not connected, the customer never
  wrote to the business on WhatsApp, the customer sent STOP, or the customer
  was asked in the last 7 days. The reason is kept on the feedback row.
- Inside the 24-hour window: a list with 5 choices (no approval needed).
  Later: the approved template named in the settings, with 5 quick-reply
  buttons. No template name = not asked.
- The answer: a choice from the list or a button, or a typed 1 to 5 when this
  is the only question open in the chat. 4-5 stars: thank you. 3: thank you.
  1-2: "Sorry ... what went wrong?", and the chat goes to "Needs staff"; the
  customer's next message (within 24 hours) is kept as the comment.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.inbox import services as inbox
from apps.inbox.models import Message

from . import notify
from .models import Order, OrderFeedback, OrderMessage

log = logging.getLogger(__name__)
F = OrderFeedback.Status
ASK_AFTER = timedelta(hours=1)
ASK_UNTIL = timedelta(hours=24)  # an old order is never asked
ONCE_PER = timedelta(days=7)  # at most one question per customer per week
COMMENT_WITHIN = timedelta(hours=24)
LOW = 2  # 1 or 2 stars is a low rating
PAYLOAD = re.compile(r"^feedback:(\d+):([0-9a-f]{16}):([1-5])$")
CHOICES = [(5, "5 ★★★★★ Excellent"), (4, "4 ★★★★ Good"), (3, "3 ★★★ OK"), (2, "2 ★★ Poor"), (1, "1 ★ Very poor")]
TEMPLATE_BUTTONS = ["5 Excellent", "4 Good", "3 OK", "2 Poor", "1 Very poor"]
# The template to create in Meta (category Utility), with the 5 quick-reply buttons above, in that order.
TEMPLATE = "Thank you for your order #{{1}} from {{2}}. How was it? Please choose 1 to 5 stars."
THANKS = "Thank you for your feedback!"
SORRY = ("Sorry that your order #{n} was not good. What went wrong? Please write a few words. "
         "A staff member will read your answer and reply to you.")


def ask_text(order: Order) -> str:
    from apps.setup.services import business_name

    return f"Thank you for your order #{order.number} from {business_name()}. How was it? Please choose 1 to 5 stars."


def payload(feedback: OrderFeedback, stars: int) -> str:
    return f"feedback:{feedback.pk}:{feedback.token}:{stars}"


def due_orders(now=None):
    """Completed orders that are ready to be asked (1 to 24 hours ago) and have no feedback row yet."""
    now = now or timezone.now()
    return (Order.objects.filter(status=Order.Status.COMPLETED, completed_at__lte=now - ASK_AFTER, completed_at__gt=now - ASK_UNTIL,
                                 feedback__isnull=True)
            .select_related("customer").order_by("completed_at"))


def ask_due(now=None) -> dict:
    """Ask every order that is due (the scheduled job). Returns how many were asked, skipped or failed."""
    counts = {F.ASKED: 0, F.SKIPPED: 0, F.FAILED: 0}
    if not notify.current_settings().ask_feedback:
        return counts
    for order in due_orders(now):
        try:
            with transaction.atomic():
                row = ask(order, now=now)
        except IntegrityError:  # another worker created it at the same time
            continue
        except Exception:  # noqa: BLE001 - one order must not stop the others
            log.exception("Could not ask for feedback")
            continue
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def why_not(order: Order, now=None) -> str:
    """Why this customer is not asked ("" = ask)."""
    from apps.customers.models import ConsentRecord

    now = now or timezone.now()
    customer = order.customer
    if customer is None or customer.is_anonymised or not customer.phone:
        return "No customer with a phone number."
    if not notify.whatsapp_connected():
        return "WhatsApp is not connected."
    wrote = Message.objects.filter(conversation__external_id=customer.phone.lstrip("+"), direction=Message.Direction.IN).exists()
    if not wrote:
        return "The customer has never written to the business on WhatsApp."
    last = ConsentRecord.objects.filter(customer=customer, channel__in=["all", "whatsapp"]).first()
    if last is not None and last.source == ConsentRecord.Source.STOP and not last.given:
        return "The customer sent STOP."
    if OrderFeedback.objects.filter(customer=customer, asked_at__gt=now - ONCE_PER).exists():
        return "This customer was asked in the last 7 days."
    return ""


def ask(order: Order, now=None) -> OrderFeedback:
    """Create the feedback row and send the question (or record why not)."""
    order = Order.objects.select_for_update(of=("self",)).select_related("customer").get(pk=order.pk)
    row = OrderFeedback.objects.create(order=order, customer=order.customer, status=F.SKIPPED, token=secrets.token_hex(8))
    reason = why_not(order, now)
    if reason:
        return _finish(row, F.SKIPPED, reason)
    try:
        conversation = inbox.conversation_for_customer(order.customer)
        if inbox.can_reply_freely(conversation):
            sent = inbox.send_list(conversation, ask_text(order), "Choose stars", [(payload(row, n), title) for n, title in CHOICES])
            via = OrderMessage.Via.MESSAGE
        else:
            s = notify.current_settings()
            if not s.template_feedback:
                return _finish(row, F.SKIPPED, "More than 24 hours since the customer's last message, and no template is set.")
            from apps.setup.services import business_name

            sent = inbox.send_template(conversation, name=s.template_feedback, language=s.template_language,
                                       params=[str(order.number), business_name()], buttons=[payload(row, n) for n, _ in CHOICES])
            via = OrderMessage.Via.TEMPLATE
    except ValidationError as exc:
        return _finish(row, F.FAILED, " ".join(exc.messages))
    if sent.status == Message.Status.FAILED:
        return _finish(row, F.FAILED, f"WhatsApp refused the message: {sent.error}"[:300], sent)
    row.via = via
    row.asked_at = timezone.now()
    return _finish(row, F.ASKED, "", sent)


def _finish(row: OrderFeedback, status: str, note: str, sent: Message | None = None) -> OrderFeedback:
    row.status, row.note = status, note[:300]
    if sent is not None:
        row.inbox_message = sent
    row.save()
    return row


# ---------------------------------------------------------------------------
# Answers (inside the incoming message's transaction)
# ---------------------------------------------------------------------------
def on_message_received(sender, message, reply_id: str = "", **kwargs) -> None:
    """Stars from a list, a button or a typed 1-5, or the comment after a low rating. Never raises."""
    if message.direction != Message.Direction.IN or getattr(message, "answered_question", False):
        return
    try:
        with transaction.atomic():
            _answer(message, reply_id)
    except Exception:  # noqa: BLE001 - an answer must never lose the customer's message
        log.exception("Could not apply a feedback answer")


def _open_in(conversation):
    return OrderFeedback.objects.filter(status=F.ASKED, inbox_message__conversation=conversation)


def _answer(message: Message, reply_id: str) -> None:
    conversation = message.conversation
    match = PAYLOAD.match(reply_id or "")
    if match:
        pk, token, stars = match.groups()
        row = OrderFeedback.objects.filter(pk=int(pk), token=token).select_related("inbox_message").first()
        if row is None or row.inbox_message is None or row.inbox_message.conversation_id != conversation.pk:
            return  # not a question we sent to this chat
        apply_stars(row, int(stars))
        message.answered_question = True  # the AI assistant leaves this message alone
        return
    text = (message.text or "").strip()
    typed = re.fullmatch(r"([1-5])(\s*(stars?|★+))?", text.lower())
    if typed:
        rows = list(_open_in(conversation)[:2])
        if len(rows) == 1 and not OrderMessage.objects.filter(is_open=True, inbox_message__conversation=conversation).exists():
            apply_stars(rows[0], int(typed.group(1)))
            message.answered_question = True
        return
    if message.kind == "text" and text:
        _keep_comment(conversation, text)


def apply_stars(row: OrderFeedback, stars: int) -> str:
    """Save the stars (the first answer counts). Returns what happened."""
    row = OrderFeedback.objects.select_for_update(of=("self",)).select_related("order", "inbox_message__conversation").get(pk=row.pk)
    if row.status != F.ASKED:
        return "already answered"
    row.stars, row.status, row.answered_at = stars, F.ANSWERED, timezone.now()
    row.save(update_fields=["stars", "status", "answered_at"])
    conversation = row.inbox_message.conversation
    if stars <= LOW:
        notify.queue_reply(row.order, SORRY.format(n=row.order.number))
        _needs_staff(conversation, f"Low rating: {stars} star{'s' if stars > 1 else ''} for order #{row.order.number}")
        return "low"
    notify.queue_reply(row.order, THANKS)
    return "thanks"


def _needs_staff(conversation, reason: str) -> None:
    from apps.ai import agent
    from apps.ai.models import AIChat

    chat, _ = AIChat.objects.get_or_create(conversation=conversation)
    agent.hand_over(chat, reason, tell=False)  # the customer already got the "what went wrong?" question


def _keep_comment(conversation, text: str) -> None:
    """After 1 or 2 stars, the customer's next message is the comment."""
    since = timezone.now() - COMMENT_WITHIN
    row = (OrderFeedback.objects.select_for_update()
           .filter(status=F.ANSWERED, stars__lte=LOW, comment="", answered_at__gt=since, inbox_message__conversation=conversation)
           .order_by("-answered_at").first())
    if row is not None:
        row.comment = text[:1000]
        row.save(update_fields=["comment"])


def forget_customer(sender, customer, **kwargs) -> None:
    """When a customer's personal data is removed, their comments go too (the stars stay, for the averages)."""
    OrderFeedback.objects.filter(customer=customer).update(comment="")


# ---------------------------------------------------------------------------
# Numbers (the daily summary and the dashboard)
# ---------------------------------------------------------------------------
def stats(start, end) -> dict:
    from django.db.models import Avg, Count, Q

    rows = OrderFeedback.objects.filter(status=F.ANSWERED, answered_at__gte=start, answered_at__lt=end)
    raw = rows.aggregate(n=Count("id"), avg=Avg("stars"), low=Count("id", filter=Q(stars__lte=LOW)))
    low = [{"order": r.order.number, "order_id": r.order_id, "stars": r.stars, "comment": r.comment}
           for r in rows.filter(stars__lte=LOW).select_related("order").order_by("answered_at")[:5]]
    return {"count": raw["n"], "average": round(raw["avg"], 1) if raw["avg"] is not None else None, "low": raw["low"], "low_orders": low}
