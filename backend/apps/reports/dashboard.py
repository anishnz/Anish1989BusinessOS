"""
The simple dashboard: today's sales, orders, top products and what needs attention.

Definitions (shown on the page too):
- Sales = totals of orders **completed** (picked up) in the period, NZ$ incl. GST.
- Orders = orders **confirmed** in the period that were not cancelled or expired.
- Days run from midnight to midnight in the business's time zone (TIME_ZONE).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.orders.models import Order, OrderLine

S = Order.Status
ZERO = Decimal("0.00")
CANCELLED = {S.CANCELLED_CUSTOMER, S.CANCELLED_SHOP, S.EXPIRED}
ATTENTION = [S.AWAITING, S.CONFIRMED, S.PREPARING, S.FINAL_SENT, S.FINAL_ACCEPTED, S.READY]
MONEY = DecimalField(max_digits=14, decimal_places=2)


def _day_range(day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _sales(start, end) -> dict:
    raw = Order.objects.filter(status=S.COMPLETED, completed_at__gte=start, completed_at__lt=end).aggregate(
        sum_total=Coalesce(Sum("total"), ZERO, output_field=MONEY),
        sum_gst=Coalesce(Sum("gst_total"), ZERO, output_field=MONEY),
        n=Count("id"),
        sum_unpaid=Coalesce(Sum("total", filter=Q(is_paid=False)), ZERO, output_field=MONEY),
    )
    data = {"total": raw["sum_total"], "gst": raw["sum_gst"], "count": raw["n"], "unpaid": raw["sum_unpaid"]}
    data["average"] = (data["total"] / data["count"]).quantize(Decimal("0.01")) if data["count"] else ZERO
    return data


def _orders_confirmed(start, end) -> int:
    return Order.objects.filter(confirmed_at__gte=start, confirmed_at__lt=end).exclude(status__in=CANCELLED).count()


def _change(now: Decimal | int, before: Decimal | int) -> dict:
    """Difference against the same weekday last week."""
    diff = now - before
    percent = None if not before else round(float(diff) / float(before) * 100)
    return {"before": before, "difference": diff, "percent": percent}


def summary(day: date | None = None, *, include_inbox: bool = False) -> dict:
    day = day or timezone.localdate()
    start, end = _day_range(day)
    week_ago_start, week_ago_end = _day_range(day - timedelta(days=7))

    today = _sales(start, end)
    last_week = _sales(week_ago_start, week_ago_end)
    orders_today = _orders_confirmed(start, end)
    orders_last_week = _orders_confirmed(week_ago_start, week_ago_end)

    # Sales per day for the 7 days ending on `day`.
    first_start, _ = _day_range(day - timedelta(days=6))
    per_day = dict(
        Order.objects.filter(status=S.COMPLETED, completed_at__gte=first_start, completed_at__lt=end)
        .annotate(day=TruncDate("completed_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(day_total=Sum("total")).values_list("day", "day_total")
    )
    week = [
        {"date": d.isoformat(), "label": d.strftime("%a %d"), "total": per_day.get(d, ZERO) or ZERO, "is_today": d == day}
        for d in (day - timedelta(days=offset) for offset in range(6, -1, -1))
    ]

    # Top products over the same 7 days (completed orders), by sales.
    top = list(
        OrderLine.objects.filter(order__status=S.COMPLETED, order__completed_at__gte=first_start, order__completed_at__lt=end)
        .values("product_id", "unit")
        .annotate(
            sales=Sum("line_total"),
            quantity=Sum(Coalesce("final_quantity", "quantity")),
            orders=Count("order_id", distinct=True),
        )
        .order_by("-sales", "product_id")[:5]
    )
    names = dict(
        OrderLine.objects.filter(product_id__in=[t["product_id"] for t in top]).order_by("product_id", "-id")
        .distinct("product_id").values_list("product_id", "product_name")
    )
    for item in top:
        item["name"] = names.get(item["product_id"], "")
        item["quantity"] = format(item["quantity"].normalize(), "f")  # 20, not 2E+1

    attention_counts = dict(Order.objects.filter(status__in=ATTENTION).values("status").annotate(n=Count("id")).values_list("status", "n"))
    attention = [{"status": s, "label": S(s).label, "count": attention_counts.get(s, 0)} for s in ATTENTION]
    pickups_due = Order.objects.filter(pickup_at__gte=start, pickup_at__lt=end).exclude(status__in=CANCELLED | {S.COMPLETED}).count()

    result = {
        "date": day.isoformat(),
        "sales": {**today, "change": _change(today["total"], last_week["total"])},
        "orders": {"count": orders_today, "change": _change(orders_today, orders_last_week)},
        "week": week,
        "week_total": sum((w["total"] for w in week), ZERO),
        "top_products": top,
        "attention": attention,
        "pickups_due_today": pickups_due,
        "definitions": {
            "sales": "Totals of orders completed (picked up) that day, NZ$ incl. GST.",
            "orders": "Orders confirmed that day that were not cancelled or expired.",
            "compared_with": (day - timedelta(days=7)).isoformat(),
        },
    }
    if include_inbox:
        from apps.inbox.models import Conversation

        result["unread_conversations"] = Conversation.objects.filter(status=Conversation.Status.OPEN, unread_count__gt=0).count()
    return result
