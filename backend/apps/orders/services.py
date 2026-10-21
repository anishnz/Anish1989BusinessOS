"""
Order rules. Every change goes through these functions, so the API, the
admin and (later) the WhatsApp AI all follow the same rules:

- prices always come from the product on the server, never from the request;
- amounts must follow the product's minimum and steps (for example 0.5 kg);
- lines can only change while the order is a draft or awaiting confirmation;
- the status can only move along the allowed paths below;
- pickup or delivery (task 2.1): a delivery order needs an address, an area
  and a time before it is sent to the customer or confirmed; the delivery fee
  comes from the area and is part of the total. Slot, area and minimum-order
  rules are strict for customers and warnings for staff (D-121);
- stock (task 2.2): confirming takes the ordered amounts off counted
  products, real weights correct it, cancelling a confirmed order puts it
  back. Customers cannot confirm more than the stock; staff get a warning;
- everything is recorded in the order history and the audit log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import audit
from apps.catalog import stock
from apps.catalog.models import Product, gst_in
from apps.customers.models import Customer
from apps.fulfilment import services as fulfilment
from apps.fulfilment.models import Kind

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
    S.READY: {S.COMPLETED, S.OUT_FOR_DELIVERY},  # pickup orders are completed, delivery orders go out first (D-123)
    S.OUT_FOR_DELIVERY: {S.COMPLETED, S.READY},
}
CANCEL_STATUSES = {S.CANCELLED_CUSTOMER, S.CANCELLED_SHOP}
# Until the order is ready, a wrong time or address can still be fixed: show warnings.
BEFORE_READY = {S.DRAFT, S.AWAITING, S.CONFIRMED, S.PREPARING, S.FINAL_SENT, S.FINAL_ACCEPTED}
FULFILMENT_FIELDS = {"fulfilment", "due_at", "delivery_address", "delivery_suburb", "delivery_postcode", "delivery_area"}
ADDRESS_FIELDS = {"delivery_address", "delivery_suburb", "delivery_postcode"}


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


def recalculate(order: Order, *, refresh_fee: bool = False) -> Order:
    """Work out line totals, the estimated total, the final total and the GST included.

    `refresh_fee`: work out the delivery fee again from the area (when the
    products, pickup or delivery, or the area changed). Otherwise the fee on
    the order stays, so later fee changes never change a confirmed order.
    """
    estimated = total = gst = Decimal("0")
    for line in order.lines.all():
        line.line_total = money(line.unit_price * line.effective_quantity)
        line.save(update_fields=["line_total"])
        estimated += money(line.unit_price * line.quantity)
        total += line.line_total
        if line.gst_applies:
            gst += gst_in(line.line_total)
    if refresh_fee:
        area = order.delivery_area if order.fulfilment == Kind.DELIVERY else None
        order.delivery_fee = fulfilment.delivery_fee(area, estimated) if area is not None else Decimal("0.00")
        order.delivery_fee_gst = fulfilment.current_settings().delivery_fee_gst
    if order.delivery_fee and order.delivery_fee_gst:
        gst += gst_in(order.delivery_fee)
    order.estimated_total, order.total, order.gst_total = estimated + order.delivery_fee, total + order.delivery_fee, gst
    order.save(update_fields=["estimated_total", "total", "gst_total", "delivery_fee", "delivery_fee_gst", "updated_at"])
    return order


# ---------------------------------------------------------------------------
# Pickup or delivery
# ---------------------------------------------------------------------------
def due_text(order: Order) -> str:
    """For example "Thu 23 Oct 10:00–10:30" (a slot) or "Thu 23 Oct 07:30" (a time staff typed)."""
    if order.due_at is None:
        return "no time yet"
    text = fulfilment.when_text(order.due_at)
    return f"{text}–{fulfilment.time_text(order.due_until)}" if order.due_until else text


def fulfilment_text(order: Order) -> str:
    """For example "Delivery to Central Auckland (fee $8.00), Thu 23 Oct 16:00–17:00"."""
    if order.fulfilment == Kind.DELIVERY:
        where = f" to {order.delivery_area.name}" if order.delivery_area_id else ""
        return f"Delivery{where} (fee ${order.delivery_fee}), {due_text(order)}"
    return f"Pickup, {due_text(order)}"


def _clean_fulfilment(order: Order) -> None:
    if order.fulfilment not in Kind.values:
        raise ValidationError("Choose pickup or delivery.")
    order.delivery_address = " ".join((order.delivery_address or "").split())[:200]
    order.delivery_suburb = " ".join((order.delivery_suburb or "").split())[:100]
    order.delivery_postcode = (order.delivery_postcode or "").strip()
    if order.delivery_postcode and not re.fullmatch(r"\d{4}", order.delivery_postcode):
        raise ValidationError("The postcode must have 4 digits.")
    if order.fulfilment == Kind.PICKUP:
        # A pickup order keeps no delivery address (less personal data to look after).
        order.delivery_address = order.delivery_suburb = order.delivery_postcode = ""
        order.delivery_area = None
    elif order.delivery_area_id is None:
        order.delivery_area = fulfilment.find_area(
            postcode=order.delivery_postcode, suburb=order.delivery_suburb, address=order.delivery_address)
    order.due_until = fulfilment.slot_end_for(order.fulfilment, order.due_at)


def booking_problems(order: Order, *, strict: bool = False) -> list[str]:
    """What stops the order being sent to the customer or confirmed. Staff: only the must-haves (D-121, D-122, D-132)."""
    problems = fulfilment.required_problems(order)
    if strict:
        fulfilment.lock_bookings()
        problems += fulfilment.rule_problems(order, order.products_estimate, exact=True)
        if not order.stock_taken:  # a confirmed order (new time, say) already holds its stock
            problems += stock.shortages(order, lock=True)
    return problems


def warnings(order: Order) -> list[str]:
    """Rules this order breaks, shown to staff until the order is ready (empty list = all fine)."""
    if order.status not in BEFORE_READY:
        return []
    found = fulfilment.required_problems(order) + fulfilment.rule_problems(order, order.products_estimate)
    if not order.stock_taken:
        found += stock.shortages(order)  # once confirmed, the stock is already taken (it may be below zero)
    return list(dict.fromkeys(found))


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
                 notes: str = "", actor=None, **details) -> Order:
    """A new draft. `details`: fulfilment, due_at, delivery_address, delivery_suburb, delivery_postcode, delivery_area."""
    if channel not in Order.Channel.values:
        raise ValidationError("Unknown channel.")
    if customer is not None and customer.is_anonymised:
        raise ValidationError("This customer's personal data was removed. Choose another customer.")
    unknown = set(details) - FULFILMENT_FIELDS
    if unknown:
        raise ValidationError(f"Unknown order details: {', '.join(sorted(unknown))}.")
    order = Order(number=_next_number(), customer=customer, channel=channel, notes=(notes or "").strip(), created_by=actor, **details)
    _clean_fulfilment(order)
    order.save()
    _replace_lines(order, lines)
    recalculate(order, refresh_fee=True)
    _event(order, "", S.DRAFT, actor, f"Order created ({fulfilment_text(order)})")
    audit("orders.create", target=order, actor=actor,
          metadata={"lines": len(lines), "total": str(order.total), "channel": channel, "fulfilment": order.fulfilment})
    return order


@transaction.atomic
def update_order(order: Order, *, lines: list[LineInput] | None = None, actor=None, strict: bool = False, **fields) -> Order:
    """Change lines (draft / awaiting confirmation only), pickup or delivery, the time and other details while open.

    - A change to what the customer agreed (products, pickup or delivery, address, time)
      while the order awaits their confirmation sends it back to Draft.
    - The delivery fee can only change while the order is not paid.
    - After confirmation, a delivery order must keep its address, area and time.
    """
    order = _lock(order)
    if not order.is_open:
        raise ValidationError(f"Order #{order.number} is {order.get_status_display().lower()} and cannot be changed.")
    allowed = {"customer", "notes", "channel"} | FULFILMENT_FIELDS
    unknown = set(fields) - allowed
    if unknown:
        raise ValidationError(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    if "customer" in fields and fields["customer"] is not None and fields["customer"].is_anonymised:
        raise ValidationError("This customer's personal data was removed. Choose another customer.")
    if "channel" in fields and fields["channel"] not in Order.Channel.values:
        raise ValidationError("Unknown channel.")
    touches_fulfilment = bool(set(fields) & FULFILMENT_FIELDS)
    if touches_fulfilment and order.status == S.OUT_FOR_DELIVERY:
        raise ValidationError("The order is out for delivery. Move it back to “Ready for delivery” first.")
    if lines is not None and order.status not in EDITABLE_STATUSES:
        raise ValidationError("Products can only be changed while the order is a draft or awaiting confirmation.")
    before = {"fulfilment": order.fulfilment, "area": order.delivery_area_id, "due_at": order.due_at, "fee": order.delivery_fee,
              "address": (order.delivery_address, order.delivery_suburb, order.delivery_postcode)}
    for key, value in fields.items():
        setattr(order, key, value.strip() if isinstance(value, str) else value)
    if set(fields) & ADDRESS_FIELDS and "delivery_area" not in fields:
        order.delivery_area = None  # found again from the new address
    if touches_fulfilment:
        _clean_fulfilment(order)
    order.save()
    if lines is not None:
        _replace_lines(order, lines)
    price_changed = lines is not None or order.fulfilment != before["fulfilment"] or order.delivery_area_id != before["area"]
    if price_changed:
        recalculate(order, refresh_fee=True)
    if order.is_paid and order.delivery_fee != before["fee"]:
        raise ValidationError("This order is paid, and this change would change the delivery fee. Record the refund first (mark it as not paid).")
    if lines is not None:
        audit("orders.lines_changed", target=order, actor=actor, metadata={"lines": len(lines), "total": str(order.total)})
    changed_fulfilment = (order.fulfilment != before["fulfilment"] or order.delivery_area_id != before["area"] or order.due_at != before["due_at"]
                          or (order.delivery_address, order.delivery_suburb, order.delivery_postcode) != before["address"])
    if changed_fulfilment:
        if order.status not in EDITABLE_STATUSES:
            problems = booking_problems(order, strict=strict)
            if problems:
                raise ValidationError(problems)
        _event(order, order.status, order.status, actor, f"Changed to: {fulfilment_text(order)}")
    if order.status == S.AWAITING and (lines is not None or changed_fulfilment):
        # The customer agreed to a different order, so they must confirm again.
        _move(order, S.DRAFT, actor, "Order changed; the customer must confirm again")
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
def status_label(order: Order, status: str) -> str:
    """A status in words for this order ("Ready for pickup" or "Ready for delivery")."""
    if status == S.READY:
        return "Ready for delivery" if order.fulfilment == Kind.DELIVERY else "Ready for pickup"
    return S(status).label


def next_moves(order: Order) -> set[str]:
    """The forward moves for this order: a pickup order is never "Out for delivery"; a delivery order goes out before it is completed."""
    moves = set(TRANSITIONS.get(order.status, set()))
    if order.status == S.READY:
        moves.discard(S.COMPLETED if order.fulfilment == Kind.DELIVERY else S.OUT_FOR_DELIVERY)
    return moves


def allowed_moves(order: Order) -> list[str]:
    if not order.is_open:
        return []
    return sorted(next_moves(order)) + sorted(CANCEL_STATUSES)


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
def change_status(order: Order, to_status: str, *, actor=None, note: str = "", strict: bool = False) -> Order:
    """Move the order on. `strict`: the customer (or the AI for them) does it, so every slot and area rule applies (D-121)."""
    order = _lock(order)
    if to_status not in S.values:
        raise ValidationError("Unknown status.")
    if to_status in CANCEL_STATUSES:
        return _cancel(order, to_status, actor=actor, note=note)
    if to_status not in next_moves(order):
        raise ValidationError(f"Order #{order.number} cannot go from '{order.status_text}' to '{status_label(order, to_status)}'.")
    if to_status in (S.AWAITING, S.CONFIRMED) and not order.lines.exists():
        raise ValidationError("Add at least one product first.")
    if to_status == S.AWAITING and order.customer is None:
        raise ValidationError("Choose the customer who must confirm the order.")
    if to_status in (S.AWAITING, S.CONFIRMED):
        problems = booking_problems(order, strict=strict)
        if problems:
            raise ValidationError(problems)
    if order.status == S.OUT_FOR_DELIVERY and to_status == S.READY and not (note or "").strip():
        raise ValidationError("Give the reason the delivery did not happen.")
    if to_status in (S.FINAL_SENT, S.READY) and order.needs_weighing:
        raise ValidationError("Enter the real weight of every product sold by weight first.")
    if to_status == S.FINAL_SENT and order.total == order.estimated_total:
        raise ValidationError(f"The final price is the same as the estimate, so the order can go straight to '{status_label(order, S.READY)}'.")
    if to_status == S.READY and order.status == S.PREPARING and order.total != order.estimated_total:
        raise ValidationError(
            f"The final price (${order.total}) differs from the estimate (${order.estimated_total}). "
            "Send the final price to the customer first."
        )
    if to_status == S.CONFIRMED and not order.stock_taken:
        stock.take_for_order(order, actor=actor)
    return _move(order, to_status, actor, note)


def _cancel(order: Order, to_status: str, *, actor=None, note: str = "") -> Order:
    if not order.is_open:
        raise ValidationError(f"Order #{order.number} is already {order.get_status_display().lower()}.")
    if not (note or "").strip():
        raise ValidationError("Give a reason for cancelling.")
    if order.is_paid:
        raise ValidationError("This order is paid. Record the refund first (mark it as not paid), then cancel it.")
    stock.give_back(order, actor=actor)
    return _move(order, to_status, actor, note)


@transaction.atomic
def set_weights(order: Order, weights: dict[int, object], *, actor=None) -> Order:
    """Enter the real weights (kg) after packing. Only while the order is being prepared."""
    order = _lock(order)
    if order.status != S.PREPARING:
        raise ValidationError("Weights can only be entered while the order is being prepared.")
    lines = {line.pk: line for line in order.lines.all()}
    counted_before = {pk: line.effective_quantity for pk, line in lines.items()}
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
    stock.weight_changed(order, counted_before, actor=actor)
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
