"""
Order rules. Every change goes through these functions, so the API, the
admin and (later) the WhatsApp AI all follow the same rules:

- prices always come from the product on the server, never from the request;
- amounts must follow the product's minimum and steps (for example 0.5 kg);
- lines can only change while the order is a draft or awaiting confirmation;
- the status can only move along the allowed paths below;
- everything is recorded in the order history and the audit log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import audit
from apps.catalog.models import Product, gst_in
from apps.customers.models import Customer

from .models import CLOSED_STATUSES, EDITABLE_STATUSES, Order, OrderCounter, OrderEvent, OrderLine

S = Order.Status
CENT = Decimal("0.01")
MAX_QUANTITY = Decimal("10000")
MAX_LINES = 100

# Allowed status moves. Cancelling is possible from any open status (see cancel()).
TRANSITIONS: dict[str, set[str]] = {
    S.DRAFT: {S.AWAITING, S.CONFIRMED},
    S.AWAITING: {S.CONFIRMED, S.DRAFT, S.EXPIRED},
    S.CONFIRMED: {S.PREPARING},
    S.PREPARING: {S.FINAL_SENT, S.READY},
    S.FINAL_SENT: {S.FINAL_ACCEPTED, S.PREPARING},
    S.FINAL_ACCEPTED: {S.READY},
    S.READY: {S.COMPLETED},
}
CANCEL_STATUSES = {S.CANCELLED_CUSTOMER, S.CANCELLED_SHOP}


@dataclass
class LineInput:
    product_id: int
    quantity: Decimal
    note: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _amount(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001 - any bad input is a validation error
        raise ValidationError(f"'{value}' is not a valid amount.") from None
    if not number.is_finite():
        raise ValidationError(f"'{value}' is not a valid amount.")
    return number


def check_quantity(product: Product, quantity) -> Decimal:
    """The amount must be at least the minimum and go up in the product's steps."""
    quantity = _amount(quantity)
    unit = "kg" if product.unit == Product.Unit.KG else ""
    if quantity <= 0 or quantity > MAX_QUANTITY:
        raise ValidationError(f"{product.name}: the amount must be more than 0 and at most {MAX_QUANTITY:f}.")
    if quantity != quantity.quantize(Decimal("0.001")):
        raise ValidationError(f"{product.name}: use at most 3 decimal places.")
    if quantity < product.min_quantity:
        raise ValidationError(f"{product.name}: the smallest amount is {product.min_quantity.normalize():f}{unit}.")
    if (quantity - product.min_quantity) % product.quantity_step != 0:
        raise ValidationError(
            f"{product.name}: the amount must go up in steps of {product.quantity_step.normalize():f}{unit} "
            f"from {product.min_quantity.normalize():f}{unit}."
        )
    return quantity


def _orderable_product(product_id) -> Product:
    product = Product.objects.filter(pk=product_id).first()
    if product is None or product.is_archived:
        raise ValidationError(f"Product {product_id} does not exist.")
    if not product.is_available:
        raise ValidationError(f"{product.name} is not available to order right now.")
    return product


def _next_number() -> int:
    counter, _ = OrderCounter.objects.select_for_update().get_or_create(pk=1)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number


def _event(order: Order, from_status: str, to_status: str, actor=None, note: str = "") -> None:
    OrderEvent.objects.create(order=order, from_status=from_status, to_status=to_status, actor=actor, note=(note or "")[:300])


def recalculate(order: Order) -> Order:
    """Work out line totals, the estimated total, the final total and the GST included."""
    estimated = total = gst = Decimal("0")
    for line in order.lines.all():
        line.line_total = money(line.unit_price * line.effective_quantity)
        line.save(update_fields=["line_total"])
        estimated += money(line.unit_price * line.quantity)
        total += line.line_total
        if line.gst_applies:
            gst += gst_in(line.line_total)
    order.estimated_total, order.total, order.gst_total = estimated, total, gst
    order.save(update_fields=["estimated_total", "total", "gst_total", "updated_at"])
    return order


def _lock(order: Order) -> Order:
    return Order.objects.select_for_update().get(pk=order.pk)


def _replace_lines(order: Order, lines: list[LineInput]) -> None:
    if not lines:
        raise ValidationError("Add at least one product.")
    if len(lines) > MAX_LINES:
        raise ValidationError(f"An order can have at most {MAX_LINES} lines.")
    prepared = []
    for line in lines:
        product = _orderable_product(line.product_id)
        quantity = check_quantity(product, line.quantity)
        prepared.append((product, quantity, (line.note or "").strip()[:200]))
    order.lines.all().delete()
    for position, (product, quantity, note) in enumerate(prepared):
        OrderLine.objects.create(
            order=order, product=product, product_name=product.name, unit=product.unit, unit_price=product.price,
            gst_applies=product.gst_applies, quantity=quantity, note=note, position=position,
        )


# ---------------------------------------------------------------------------
# Creating and changing orders
# ---------------------------------------------------------------------------
@transaction.atomic
def create_order(*, lines: list[LineInput], customer: Customer | None = None, channel: str = Order.Channel.COUNTER,
                 notes: str = "", pickup_at=None, actor=None) -> Order:
    if channel not in Order.Channel.values:
        raise ValidationError("Unknown channel.")
    if customer is not None and customer.is_anonymised:
        raise ValidationError("This customer's personal data was removed. Choose another customer.")
    order = Order.objects.create(
        number=_next_number(), customer=customer, channel=channel, notes=(notes or "").strip(), pickup_at=pickup_at, created_by=actor,
    )
    _replace_lines(order, lines)
    recalculate(order)
    _event(order, "", S.DRAFT, actor, "Order created")
    audit("orders.create", target=order, actor=actor, metadata={"lines": len(lines), "total": str(order.total), "channel": channel})
    return order


@transaction.atomic
def update_order(order: Order, *, lines: list[LineInput] | None = None, actor=None, **fields) -> Order:
    """Change lines (draft / awaiting confirmation only) and details (customer, notes, pickup time) while open."""
    order = _lock(order)
    if not order.is_open:
        raise ValidationError(f"Order #{order.number} is {order.get_status_display().lower()} and cannot be changed.")
    allowed = {"customer", "notes", "pickup_at", "channel"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValidationError(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    if "customer" in fields and fields["customer"] is not None and fields["customer"].is_anonymised:
        raise ValidationError("This customer's personal data was removed. Choose another customer.")
    if "channel" in fields and fields["channel"] not in Order.Channel.values:
        raise ValidationError("Unknown channel.")
    for key, value in fields.items():
        setattr(order, key, value.strip() if isinstance(value, str) else value)
    order.save()
    if lines is not None:
        if order.status not in EDITABLE_STATUSES:
            raise ValidationError("Products can only be changed while the order is a draft or awaiting confirmation.")
        _replace_lines(order, lines)
        recalculate(order)
        audit("orders.lines_changed", target=order, actor=actor, metadata={"lines": len(lines), "total": str(order.total)})
        if order.status == S.AWAITING:
            # The customer agreed to a different order, so they must confirm again.
            _move(order, S.DRAFT, actor, "Products changed; the customer must confirm again")
    return order


@transaction.atomic
def delete_draft(order: Order, *, actor=None) -> None:
    order = _lock(order)
    if order.status != S.DRAFT:
        raise ValidationError("Only draft orders can be deleted. Cancel the order instead.")
    audit("orders.delete_draft", target=order, actor=actor)
    order.delete()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def allowed_moves(order: Order) -> list[str]:
    if not order.is_open:
        return []
    return sorted(TRANSITIONS.get(order.status, set())) + sorted(CANCEL_STATUSES)


def _move(order: Order, to_status: str, actor=None, note: str = "") -> Order:
    from_status = order.status
    order.status = to_status
    now = timezone.now()
    if to_status == S.CONFIRMED:
        order.confirmed_at = now
    elif to_status == S.COMPLETED:
        order.completed_at = now
    elif to_status in CANCEL_STATUSES or to_status == S.EXPIRED:
        order.cancelled_at = now
    order.save()
    _event(order, from_status, to_status, actor, note)
    audit("orders.status", target=order, actor=actor, metadata={"from": from_status, "to": to_status})
    return order


@transaction.atomic
def change_status(order: Order, to_status: str, *, actor=None, note: str = "") -> Order:
    order = _lock(order)
    if to_status not in S.values:
        raise ValidationError("Unknown status.")
    if to_status in CANCEL_STATUSES:
        return _cancel(order, to_status, actor=actor, note=note)
    if to_status not in TRANSITIONS.get(order.status, set()):
        raise ValidationError(f"Order #{order.number} cannot go from '{order.get_status_display()}' to '{S(to_status).label}'.")
    if to_status in (S.AWAITING, S.CONFIRMED) and not order.lines.exists():
        raise ValidationError("Add at least one product first.")
    if to_status == S.AWAITING and order.customer is None:
        raise ValidationError("Choose the customer who must confirm the order.")
    if to_status in (S.FINAL_SENT, S.READY) and order.needs_weighing:
        raise ValidationError("Enter the real weight of every product sold by weight first.")
    if to_status == S.FINAL_SENT and order.total == order.estimated_total:
        raise ValidationError("The final price is the same as the estimate, so the order can go straight to 'Ready for pickup'.")
    if to_status == S.READY and order.status == S.PREPARING and order.total != order.estimated_total:
        raise ValidationError(
            f"The final price (${order.total}) differs from the estimate (${order.estimated_total}). "
            "Send the final price to the customer first."
        )
    return _move(order, to_status, actor, note)


def _cancel(order: Order, to_status: str, *, actor=None, note: str = "") -> Order:
    if not order.is_open:
        raise ValidationError(f"Order #{order.number} is already {order.get_status_display().lower()}.")
    if not (note or "").strip():
        raise ValidationError("Give a reason for cancelling.")
    if order.is_paid:
        raise ValidationError("This order is paid. Record the refund first (mark it as not paid), then cancel it.")
    return _move(order, to_status, actor, note)


@transaction.atomic
def set_weights(order: Order, weights: dict[int, object], *, actor=None) -> Order:
    """Enter the real weights (kg) after packing. Only while the order is being prepared."""
    order = _lock(order)
    if order.status != S.PREPARING:
        raise ValidationError("Weights can only be entered while the order is being prepared.")
    lines = {line.pk: line for line in order.lines.all()}
    for line_id, value in weights.items():
        line = lines.get(int(line_id))
        if line is None:
            raise ValidationError(f"Line {line_id} is not part of order #{order.number}.")
        if line.unit != Product.Unit.KG:
            raise ValidationError(f"{line.product_name} is not sold by weight.")
        weight = _amount(value)
        if weight <= 0 or weight > MAX_QUANTITY or weight != weight.quantize(Decimal("0.001")):
            raise ValidationError(f"{line.product_name}: enter a weight in kg with at most 3 decimal places.")
        line.final_quantity = weight
        line.save(update_fields=["final_quantity"])
    recalculate(order)
    audit("orders.weights", target=order, actor=actor, metadata={"lines": len(weights), "total": str(order.total), "estimate": str(order.estimated_total)})
    return order


@transaction.atomic
def set_paid(order: Order, paid: bool, *, method: str = "", actor=None) -> Order:
    order = _lock(order)
    if paid:
        if method not in Order.PaymentMethod.values or not method:
            raise ValidationError("Choose how the customer paid.")
        if order.status in (S.DRAFT, S.AWAITING) or order.status in CANCEL_STATUSES or order.status == S.EXPIRED:
            raise ValidationError("Only confirmed orders can be marked as paid.")
        order.is_paid, order.payment_method, order.paid_at = True, method, timezone.now()
    else:
        order.is_paid, order.payment_method, order.paid_at = False, "", None
    order.save()
    _event(order, order.status, order.status, actor, f"Marked as paid ({order.get_payment_method_display()})" if paid else "Marked as not paid")
    audit("orders.paid" if paid else "orders.unpaid", target=order, actor=actor, metadata={"method": method, "total": str(order.total)})
    return order


def expire_unconfirmed(*, minutes: int = 60) -> int:
    """Orders waiting for the customer's confirmation longer than `minutes` become Expired."""
    cutoff = timezone.now() - timedelta(minutes=minutes)
    count = 0
    for order in Order.objects.filter(status=S.AWAITING, updated_at__lt=cutoff):
        with transaction.atomic():
            locked = _lock(order)
            if locked.status == S.AWAITING:
                _move(locked, S.EXPIRED, None, f"Not confirmed within {minutes} minutes")
                count += 1
    return count
