"""
The live order board for the counter and the kitchen (task 2.6, D-151 to D-154).

Four columns of confirmed orders that are not finished: To prepare, Being
prepared (with "final price sent" and "final price accepted"), Ready, and
Out for delivery. The board shows orders due today, late orders from earlier
days and orders without a time; with `tomorrow` it also shows tomorrow's.

Each card says the one next step staff can take from the board, or why there
is none (weights to enter, waiting for the customer). The step itself is the
normal status change (POST /api/orders/<id>/status/) with all its rules.

The board may be on a screen customers can see, so a card has the customer's
short name ("Sita R.") and, for delivery, only the suburb, never the street
address or the phone number (D-153).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.fulfilment import services as fulfilment

from . import services
from .models import Order

S = Order.Status
COLUMNS = [
    ("to_prepare", "To prepare", (S.CONFIRMED,)),
    ("preparing", "Being prepared", (S.PREPARING, S.FINAL_SENT, S.FINAL_ACCEPTED)),
    ("ready", "Ready", (S.READY,)),
    ("out", "Out for delivery", (S.OUT_FOR_DELIVERY,)),
]
ON_BOARD = tuple(status for _, _, statuses in COLUMNS for status in statuses)


def next_step(order: Order) -> dict:
    """The one forward move the board offers: {"to", "label"}, or {"note"} when staff must do something else first."""
    if order.status == S.CONFIRMED:
        return {"to": S.PREPARING, "label": "Start preparing"}
    if order.status == S.PREPARING:
        if order.needs_weighing:
            return {"note": "Enter the real weights on the order page"}
        if order.total != order.estimated_total:
            return {"to": S.FINAL_SENT, "label": "Send final price"}
        return {"to": S.READY, "label": services.status_label(order, S.READY)}
    if order.status == S.FINAL_SENT:
        return {"note": "Waiting for the customer to accept the price"}
    if order.status == S.FINAL_ACCEPTED:
        return {"to": S.READY, "label": services.status_label(order, S.READY)}
    if order.status == S.READY:
        if order.is_delivery:
            return {"to": S.OUT_FOR_DELIVERY, "label": "Out for delivery"}
        return {"to": S.COMPLETED, "label": "Picked up"}
    if order.status == S.OUT_FOR_DELIVERY:
        return {"to": S.COMPLETED, "label": "Delivered"}
    return {}


def short_name(order: Order) -> str:
    """ "Sita Rai" -> "Sita R."; a walk-in or removed customer has no name."""
    customer = order.customer
    if customer is None:
        return "Walk-in"
    if customer.is_anonymised:
        return "Customer"
    parts = customer.name.split()
    if not parts:
        return "Customer"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def time_text(order: Order, today) -> str:
    """Today: "10:00–10:30". Tomorrow: "Tomorrow 10:00". Another day: "Tue 21 Oct 10:00"."""
    if order.due_at is None:
        return "No time"
    day = timezone.localdate(order.due_at)
    start = fulfilment.time_text(order.due_at)
    span = f"{start}–{fulfilment.time_text(order.due_until)}" if order.due_until else start
    if day == today:
        return span
    if day == today + timedelta(days=1):
        return f"Tomorrow {span}"
    return f"{fulfilment.day_text(day)} {span}"


def _card(order: Order, now, today) -> dict:
    lines = [{"name": line.product_name, "amount": f"{line.effective_quantity.normalize():f}", "unit": line.unit,
              "note": line.note, "weighed": line.final_quantity is not None} for line in order.lines.all()]
    end = order.due_until or order.due_at
    return {
        "id": order.pk, "number": order.number, "status": order.status, "status_label": order.status_text,
        "customer": short_name(order), "fulfilment": order.fulfilment,
        "suburb": (order.delivery_suburb or (order.delivery_area.name if order.delivery_area else "")) if order.is_delivery else "",
        "due_at": order.due_at, "time_text": time_text(order, today), "late": bool(end and end < now),
        "lines": lines, "notes": order.notes, "is_paid": order.is_paid, "total": f"{order.total:.2f}",
        "next": next_step(order), "confirmed_at": order.confirmed_at,
    }


def _sort_key(card: dict, now):
    # Late orders first, then by time; orders without a time last.
    return (not card["late"], card["due_at"] is None, card["due_at"] or now, card["number"])


def board(*, tomorrow: bool = False, now=None) -> dict:
    now = now or timezone.now()
    today = timezone.localdate(now)
    last_day = today + timedelta(days=1 if tomorrow else 0)
    until = timezone.make_aware(datetime.combine(last_day + timedelta(days=1), time.min))
    orders = (Order.objects.filter(status__in=ON_BOARD).filter(Q(due_at__isnull=True) | Q(due_at__lt=until))
              .select_related("customer", "delivery_area").prefetch_related("lines"))
    cards = [_card(order, now, today) for order in orders]
    columns = []
    for key, label, statuses in COLUMNS:
        column = sorted((c for c in cards if c["status"] in statuses), key=lambda c: _sort_key(c, now))
        columns.append({"key": key, "label": label, "orders": column})
    return {"now": now, "today": today, "tomorrow": tomorrow, "count": len(cards), "late": sum(c["late"] for c in cards),
            "columns": columns}
