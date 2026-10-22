"""
The daily owner summary (task 2.7, D-155 and D-156).

- Every 5 minutes a scheduled job looks at each business. When the business's
  time (default 20:00) has passed and today's summary was not made yet, it is
  made once (DailySummary.day is unique).
- What it says (today, midnight until the time it is made): sales and
  completed orders (compared with the same day last week), orders confirmed,
  the top 3 products, orders still open, low stock, star feedback and chats
  waiting for staff. The same definitions as the dashboard.
- Sent by WhatsApp to the owner's numbers (an approved Utility template,
  because the owner rarely writes to the business number) and by email.
  Meta charges per template message. Nothing is sent on a closed day (a
  closed day or no opening hours) when there were no orders at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.orders.models import Order

from .models import DailySummary, DailySummarySettings

log = logging.getLogger(__name__)
D = DailySummary.Status
S = Order.Status
OPEN = [S.CONFIRMED, S.PREPARING, S.FINAL_SENT, S.FINAL_ACCEPTED, S.READY, S.OUT_FOR_DELIVERY]
# The template to create in Meta (category Utility, language English). Parameters cannot contain new lines.
TEMPLATE = ("Daily summary for {{1}}, {{2}}. Sales: ${{3}} from {{4}} completed orders ({{5}}). Orders confirmed: {{6}}. "
            "Top products: {{7}}. Still open: {{8}}. Low stock: {{9}}. Feedback: {{10}}. Chats waiting for staff: {{11}}.")


def current_settings() -> DailySummarySettings:
    return DailySummarySettings.objects.get_or_create(pk=1)[0]


def money(value) -> str:
    return f"{Decimal(value):,.2f}"


def _range(day, until: datetime | None = None) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = until or start + timedelta(days=1)
    return start, end


def closed_day(day) -> bool:
    """The business is closed: a closed day, or no pickup or delivery hours on that weekday."""
    from apps.fulfilment.models import ClosedDay, OpeningHours

    return ClosedDay.objects.filter(date=day).exists() or not OpeningHours.objects.filter(weekday=day.weekday()).exists()


def figures(day, until: datetime | None = None) -> dict:
    """The numbers for `day` (until `until`, or the whole day)."""
    from apps.ai.agent import waiting_chats
    from apps.catalog.stock import low_stock
    from apps.orders import feedback
    from apps.orders.models import OrderLine

    from .dashboard import _orders_confirmed, _sales

    start, end = _range(day, until)
    week_start, week_end = start - timedelta(days=7), end - timedelta(days=7)
    sales, before = _sales(start, end), _sales(week_start, week_end)
    top = list(OrderLine.objects.filter(order__status=S.COMPLETED, order__completed_at__gte=start, order__completed_at__lt=end)
               .values("product_name").annotate(sales=Sum("line_total")).order_by("-sales", "product_name")[:3])
    tomorrow_start, tomorrow_end = _range(day + timedelta(days=1))
    open_orders = Order.objects.filter(status__in=OPEN)

    return {
        "day": day,
        "sales": sales["total"], "completed": sales["count"], "unpaid": sales["unpaid"],
        "sales_before": before["total"],
        "confirmed": _orders_confirmed(start, end),
        "top": [{"name": t["product_name"], "sales": t["sales"]} for t in top],
        "open": open_orders.count(),
        "open_tomorrow": open_orders.filter(due_at__gte=tomorrow_start, due_at__lt=tomorrow_end).count(),
        "low_stock": [f"{r['name']} ({r['state_text'].lower()})" for r in low_stock()],
        "feedback": feedback.stats(start, end),
        "waiting_chats": waiting_chats().count(),
        "created": Order.objects.filter(created_at__gte=start, created_at__lt=end).count(),
    }


def parts(f: dict) -> dict:
    """The summary in short phrases (one per template parameter)."""
    fb = f["feedback"]
    if fb["count"]:
        feedback = f"{fb['count']} answer{'s' if fb['count'] != 1 else ''}, average {fb['average']} stars"
        if fb["low"]:
            feedback += f", {fb['low']} low ({', '.join('#%s %s stars' % (r['order'], r['stars']) for r in fb['low_orders'])})"
    else:
        feedback = "none today"
    return {
        "sales": money(f["sales"]),
        "completed": str(f["completed"]),
        "compared": f"same day last week ${money(f['sales_before'])}",
        "confirmed": str(f["confirmed"]),
        "top": ", ".join(f"{t['name']} ${money(t['sales'])}" for t in f["top"]) or "none",
        "open": f"{f['open']} order{'s' if f['open'] != 1 else ''}, {f['open_tomorrow']} due tomorrow" if f["open"] else "none",
        "low_stock": ", ".join(f["low_stock"]) or "none",
        "feedback": feedback,
        "waiting": str(f["waiting_chats"]),
    }


def text(f: dict, business: str) -> str:
    p = parts(f)
    unpaid = f" (not paid yet: ${money(f['unpaid'])})" if f["unpaid"] else ""
    return "\n".join([
        f"Daily summary for {business}, {f['day']:%a %d %b %Y}",
        "",
        f"Sales: ${p['sales']} from {p['completed']} completed orders{unpaid}",
        f"Same day last week: ${money(f['sales_before'])}",
        f"Orders confirmed: {p['confirmed']}",
        f"Top products: {p['top']}",
        f"Still open: {p['open']}",
        f"Low stock: {p['low_stock']}",
        f"Feedback: {p['feedback']}",
        f"Chats waiting for staff: {p['waiting']}",
    ])


def template_params(f: dict, business: str) -> list[str]:
    p = parts(f)
    return [business, f"{f['day']:%a %d %b}", p["sales"], p["completed"], p["compared"], p["confirmed"], p["top"], p["open"],
            p["low_stock"], p["feedback"], p["waiting"]]


def email_recipients(s: DailySummarySettings) -> list[str]:
    if s.email_list():
        return s.email_list()
    from apps.accounts.models import User
    from apps.rbac import policy

    return sorted({u.email for u in User.objects.filter(is_active=True, is_staff=True).exclude(email="")
                   if policy.has_perm(u, "orders.configure") and policy.has_perm(u, "reports.view")})


# ---------------------------------------------------------------------------
# Making and sending
# ---------------------------------------------------------------------------
def due(now=None) -> bool:
    now = now or timezone.now()
    s = current_settings()
    local = timezone.localtime(now)
    return s.enabled and local.time() >= s.send_at and not DailySummary.objects.filter(day=local.date()).exists()


def send_if_due(now=None) -> str:
    """The scheduled job, in one business."""
    now = now or timezone.now()
    if not due(now):
        return "not due"
    try:
        with transaction.atomic():
            return make(timezone.localdate(now), now=now).status
    except IntegrityError:  # another worker made it at the same time
        return "already made"


def make(day, *, now=None, force: bool = False) -> DailySummary:
    """Make and send the summary for `day` (once). `force`: also on a closed day without orders (the "Send now" button)."""
    from apps.audit.services import audit
    from apps.setup.services import business_name

    now = now or timezone.now()
    s = current_settings()
    row = DailySummary.objects.create(day=day, status=D.SKIPPED)
    until = min(now, _range(day)[1])
    f = figures(day, until)
    business = business_name()
    row.text = text(f, business)
    if not force and closed_day(day) and not f["created"] and not f["completed"] and not f["confirmed"]:
        row.note = "Closed today and no orders, so nothing was sent."
        row.save()
        return row
    results = []
    if s.by_whatsapp:
        row.whatsapp_result, ok = _send_whatsapp(s, f, business)
        results.append(ok)
    else:
        row.whatsapp_result = "Switched off."
    if s.by_email:
        row.email_result, ok = _send_email(s, row.text, f, business)
        results.append(ok)
    else:
        row.email_result = "Switched off."
    sent = [r for r in results if r is True]
    failed = [r for r in results if r is False]
    row.status = D.SENT if sent and not failed else D.PARTLY if sent else D.FAILED if failed else D.SKIPPED
    if row.status == D.SKIPPED:
        row.note = "No WhatsApp numbers or email addresses to send to."
    row.save()
    audit("reports.daily_summary", metadata={"day": day.isoformat(), "status": row.status})
    return row


def _send_whatsapp(s: DailySummarySettings, f: dict, business: str) -> tuple[str, bool | None]:
    """(result text, True sent / False failed / None nothing to do)."""
    from apps.inbox import whatsapp
    from apps.orders.notify import whatsapp_connected
    from apps.vault import services as vault
    from apps.vault.models import Connection

    numbers = s.phone_list()
    if not numbers:
        return "No numbers set.", None
    if not whatsapp_connected():
        return "WhatsApp is not connected.", False
    if not s.template_name:
        return "No template name set.", False
    conn = Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).order_by("is_backup", "id").first()
    params = [" ".join(p.split())[:1000] or "-" for p in template_params(f, business)]
    payload = {"type": "template", "template": {"name": s.template_name, "language": {"code": s.template_language},
                                                "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]}}
    ok, errors = 0, []
    for number in numbers:
        result = whatsapp.send_message(vault.read_secrets(conn), conn.config, number.lstrip("+"), payload)
        if result.ok:
            ok += 1
        else:
            errors.append(f"{number[:-4]}****: {result.error}"[:120])
    if errors:
        return (f"Sent to {ok} of {len(numbers)}. " + "; ".join(errors))[:300], False
    return f"Sent to {ok} number{'s' if ok != 1 else ''}.", True


def _send_email(s: DailySummarySettings, body: str, f: dict, business: str, *, test: bool = False) -> tuple[str, bool | None]:
    from django.core.mail import send_mail

    from apps.health.services import current_tenant
    from apps.tenants.domains import main_address, site_url

    recipients = email_recipients(s)
    if not recipients:
        return "No one to email.", None
    tenant = current_tenant()
    link = site_url(main_address(tenant), None, "/app/") if tenant else ""
    try:
        send_mail(f"{'TEST ' if test else ''}Daily summary: ${money(f['sales'])} sales ({business}, {f['day']:%a %d %b})",
                  f"{body}\n\nOpen the dashboard: {link}\n\nChange or switch off this email: Reports and dashboard → Daily summary settings.",
                  None, recipients)
    except Exception:  # noqa: BLE001 - the email must not break anything
        log.exception("Daily summary email could not be sent")
        return "The email could not be sent (check the email settings).", False
    return f"Emailed {len(recipients)} {'people' if len(recipients) != 1 else 'person'}.", True


def preview(now=None) -> str:
    from apps.setup.services import business_name

    now = now or timezone.now()
    return text(figures(timezone.localdate(now), now), business_name())


def send_test(*, actor=None, now=None) -> str:
    """The "Send a test now" button: today's summary so far, sent now, not saved as today's summary."""
    from apps.audit.services import audit
    from apps.setup.services import business_name

    now = now or timezone.now()
    s = current_settings()
    f = figures(timezone.localdate(now), now)
    business = business_name()
    body = "TEST\n" + text(f, business)
    results = []
    if s.by_whatsapp:
        results.append("WhatsApp: " + _send_whatsapp(s, f, business)[0])
    if s.by_email:
        results.append("Email: " + _send_email(s, body, f, business, test=True)[0])
    audit("reports.daily_summary_test", actor=actor, metadata={"results": len(results)})
    return " ".join(results) or "WhatsApp and email are both switched off."
