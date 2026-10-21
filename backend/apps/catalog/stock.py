"""
Stock (task 2.2, D-130 to D-134).

- A product's stock is counted only when "Count stock" is on, in the
  product's unit (kg for products sold by weight, packs or items otherwise).
- Every change is a StockMovement (which cannot be changed or deleted).
- Orders: stock is taken off when an order is confirmed (the ordered amount),
  corrected by the difference when the real weight is entered, and put back
  when a confirmed order is cancelled. Drafts and orders waiting for the
  customer hold no stock.
- Not enough stock: customers (WhatsApp AI, website) cannot confirm; staff may
  confirm anyway (stock goes below zero) and see a warning (D-132).
- Changing stock by hand needs Products - Edit (received, counted, waste,
  correction).
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import audit

from .models import Product, StockMovement

R = StockMovement.Reason
MAX_STOCK = Decimal("1000000")
MANUAL_REASONS = (R.RECEIVED, R.COUNTED, R.WASTE, R.CORRECTION)


def number_text(quantity: Decimal) -> str:
    """40.000 -> "40", 2.500 -> "2.5" (normalize() alone would give "4E+1")."""
    return f"{quantity.normalize():f}"


def amount_text(quantity: Decimal, product: Product) -> str:
    text = number_text(quantity)
    if product.unit == Product.Unit.KG:
        return f"{text} kg"
    if product.unit == Product.Unit.PACK:
        return f"{text} pack{'' if quantity == 1 else 's'}"
    return text


def state(product: Product) -> str:
    """not_counted, below_zero, out, low or ok."""
    if not product.track_stock:
        return "not_counted"
    if product.stock_quantity < 0:
        return "below_zero"
    if product.stock_quantity < product.min_quantity:
        return "out"
    if product.low_stock_level is not None and product.stock_quantity <= product.low_stock_level:
        return "low"
    return "ok"


STATE_TEXT = {"not_counted": "Not counted", "below_zero": "Below zero: count again", "out": "Out of stock", "low": "Low", "ok": "In stock"}


def _number(value) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(f"'{value}' is not a number.") from None
    if not number.is_finite() or number != number.quantize(Decimal("0.001")) or abs(number) > MAX_STOCK:
        raise ValidationError("Use a number with at most 3 decimal places.")
    return number


def _record(product: Product, change: Decimal, reason: str, *, actor=None, note: str = "", order=None) -> StockMovement:
    """Change the stock of a locked product and write the movement."""
    product.stock_quantity += change
    product.save(update_fields=["stock_quantity", "updated_at"])
    return StockMovement.objects.create(
        product=product, change=change, quantity_after=product.stock_quantity, reason=reason, note=(note or "").strip()[:200],
        order_id=order.pk if order is not None else None, order_number=order.number if order is not None else None,
        actor=actor if getattr(actor, "pk", None) else None, actor_email=getattr(actor, "email", "") or "",
    )


@transaction.atomic
def adjust(product: Product, *, reason: str, quantity, note: str = "", actor=None) -> StockMovement:
    """
    A change by hand. received: quantity is added; waste: taken off;
    counted: quantity is the new stock; correction: added (use a minus sign to take off).
    """
    if reason not in MANUAL_REASONS:
        raise ValidationError("Choose received, counted, waste or correction.")
    product = Product.objects.select_for_update().get(pk=product.pk)
    if not product.track_stock:
        raise ValidationError(f"Stock is not counted for {product.name}. Switch on “Count stock” first.")
    number = _number(quantity)
    if reason == R.COUNTED:
        if number < 0:
            raise ValidationError("A counted amount cannot be below zero.")
        change = number - product.stock_quantity
        if change == 0:
            raise ValidationError(f"The stock of {product.name} is already {amount_text(number, product)}.")
    elif reason == R.CORRECTION:
        if number == 0:
            raise ValidationError("A correction cannot be 0.")
        change = number
    else:
        if number <= 0:
            raise ValidationError("Enter an amount more than 0.")
        change = number if reason == R.RECEIVED else -number
    if reason in (R.WASTE, R.CORRECTION) and not (note or "").strip():
        raise ValidationError("Write a short note (for example: out of date, dropped, counted wrong).")
    movement = _record(product, change, reason, actor=actor, note=note)
    audit("products.stock_adjusted", target=product, actor=actor,
          metadata={"reason": reason, "change": number_text(change), "after": number_text(product.stock_quantity)})
    return movement


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def _needs(order, *, final: bool = False) -> "OrderedDict[int, Decimal]":
    """Amount per counted product in the order (ordered amount, or the real weight when `final`)."""
    needs: OrderedDict[int, Decimal] = OrderedDict()
    for line in order.lines.select_related("product").order_by("product_id"):
        if line.product.track_stock:
            qty = line.effective_quantity if final else line.quantity
            needs[line.product_id] = needs.get(line.product_id, Decimal("0")) + qty
    return needs


def _locked(ids) -> dict[int, Product]:
    return {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=list(ids)).order_by("pk")}


def shortages(order, *, lock: bool = False) -> list[str]:
    """Products in the order that do not have enough stock (counted products only)."""
    needs = _needs(order)
    if not needs:
        return []
    products = _locked(needs) if lock else Product.objects.in_bulk(list(needs))
    problems = []
    for pid, need in needs.items():
        product = products[pid]
        if product.stock_quantity < need:
            have = max(product.stock_quantity, Decimal("0"))
            problems.append(f"Only {amount_text(have, product)} of {product.name} in stock (this order needs {amount_text(need, product)}).")
    return problems


def take_for_order(order, *, actor=None) -> None:
    """When the order is confirmed: take the ordered amounts off (inside the caller's transaction)."""
    needs = _needs(order)
    products = _locked(needs)
    for pid, need in needs.items():
        _record(products[pid], -need, R.ORDER, actor=actor, order=order, note=f"Order #{order.number} confirmed")
    order.stock_taken = True
    order.save(update_fields=["stock_taken", "updated_at"])


def weight_changed(order, before: dict[int, Decimal], *, actor=None) -> None:
    """After real weights: take off (or put back) the difference. `before`: line id -> amount counted until now."""
    if not order.stock_taken:
        return
    diffs: OrderedDict[int, Decimal] = OrderedDict()
    for line in order.lines.select_related("product").order_by("product_id"):
        if line.product.track_stock and line.pk in before:
            diff = line.effective_quantity - before[line.pk]
            if diff:
                diffs[line.product_id] = diffs.get(line.product_id, Decimal("0")) + diff
    products = _locked(diffs)
    for pid, diff in diffs.items():
        _record(products[pid], -diff, R.WEIGHT, actor=actor, order=order, note=f"Real weight of order #{order.number}")


def give_back(order, *, actor=None) -> None:
    """When a confirmed order is cancelled: put back what it took (the real weight when entered)."""
    if not order.stock_taken:
        return
    needs = _needs(order, final=True)
    products = _locked(needs)
    for pid, qty in needs.items():
        _record(products[pid], qty, R.CANCELLED, actor=actor, order=order, note=f"Order #{order.number} cancelled")
    order.stock_taken = False
    order.save(update_fields=["stock_taken", "updated_at"])


def low_stock(limit: int = 10) -> list[dict]:
    """Counted products that are low, out of stock or below zero (for the dashboard), worst first."""
    found = []
    for product in Product.objects.filter(track_stock=True, is_archived=False).order_by("name"):
        s = state(product)
        if s in ("below_zero", "out", "low"):
            found.append({"product_id": product.pk, "name": product.name, "unit": product.unit, "state": s, "state_text": STATE_TEXT[s],
                          "stock": number_text(product.stock_quantity),
                          "warn_at": number_text(product.low_stock_level) if product.low_stock_level is not None else None})
    order = {"below_zero": 0, "out": 1, "low": 2}
    return sorted(found, key=lambda r: (order[r["state"]], r["name"]))[:limit]
