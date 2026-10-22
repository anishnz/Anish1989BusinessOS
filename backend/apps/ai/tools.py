"""
What the AI may do (task 2.4, D-142). Every tool runs on the server with the
same rules as staff and customers:

- products, prices, stock, times, areas and fees always come from the
  database, never from the AI's text;
- the AI only works on the order of the chat it is answering, for that
  chat's customer;
- the AI cannot confirm an order. send_for_confirmation sends the customer the
  summary with Yes and No buttons (task 2.3); only the customer's Yes confirms
  it, with every customer rule (slots, areas, stock);
- a tool that fails returns {"error": "..."} so the AI can explain or try again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog import stock
from apps.catalog.models import Product
from apps.fulfilment import services as fulfilment
from apps.fulfilment.models import ClosedDay, DeliveryArea, Kind, OpeningHours
from apps.orders import notify
from apps.orders import services as orders
from apps.orders.models import Order

S = Order.Status
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class Context:
    """The chat the AI is answering."""

    chat: object  # AIChat
    customer: object  # Customer
    handover: str = ""
    steps: list = field(default_factory=list)

    @property
    def order(self) -> Order | None:
        """The order the AI is building, while the customer can still change it."""
        order = self.chat.order
        if order is not None:
            order.refresh_from_db()
            if order.status in (S.DRAFT, S.AWAITING):
                return order
        return None


SPECS = [
    {"name": "search_products", "description": "Find products the shop sells, with price, unit and stock. Use one or two short words "
     "(English or Nepali), for example 'goat', 'khasi', 'momo'. An empty query lists products.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Short search words"}}, "required": ["query"]}},
    {"name": "shop_info", "description": "The shop's address, phone, opening hours for pickup and delivery, delivery areas with fees and "
     "minimum orders, closed days and how customers pay.", "parameters": {"type": "object", "properties": {}}},
    {"name": "available_times", "description": "Free pickup or delivery times on one day. Times are New Zealand time.",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["pickup", "delivery"]},
         "date": {"type": "string", "description": "YYYY-MM-DD"}}, "required": ["kind", "date"]}},
    {"name": "check_delivery_address", "description": "Whether the shop delivers to an address, and the delivery fee and minimum order.",
     "parameters": {"type": "object", "properties": {
         "address": {"type": "string"}, "suburb": {"type": "string"}, "postcode": {"type": "string"}}, "required": ["address"]}},
    {"name": "set_order", "description": "Create or change the customer's order in this chat. Give 'lines' to replace all products. "
     "Give only the fields that change. Returns the order and any problems still to fix.",
     "parameters": {"type": "object", "properties": {
         "lines": {"type": "array", "description": "All products of the order", "items": {"type": "object", "properties": {
             "product_id": {"type": "integer"}, "quantity": {"type": "number", "description": "kg for products sold by kg, otherwise items or packs"},
             "note": {"type": "string", "description": "For example 'cut small'"}}, "required": ["product_id", "quantity"]}},
         "fulfilment": {"type": "string", "enum": ["pickup", "delivery"]},
         "due_at": {"type": "string", "description": "Start of the chosen time, YYYY-MM-DDTHH:MM, New Zealand time"},
         "delivery_address": {"type": "string", "description": "Street, number and unit"},
         "delivery_suburb": {"type": "string"}, "delivery_postcode": {"type": "string"},
         "notes": {"type": "string", "description": "Customer requests for the whole order"}}}},
    {"name": "send_for_confirmation", "description": "When the order is complete and has no problems: send the customer the order summary "
     "with Yes and No buttons. Only the customer's Yes confirms the order.", "parameters": {"type": "object", "properties": {}}},
    {"name": "past_orders", "description": "The customer's last 3 orders (for \"same as last time\"). Show them briefly and let the "
     "customer choose one; then call reorder.", "parameters": {"type": "object", "properties": {}}},
    {"name": "reorder", "description": "Copy one of the customer's past orders into a new order at today's prices. The time is not copied: "
     "ask for it. Only when no order is in progress in this chat.",
     "parameters": {"type": "object", "properties": {"order_number": {"type": "integer"}}, "required": ["order_number"]}},
    {"name": "cancel_draft", "description": "Throw away the order the customer has not confirmed, when they no longer want it.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "hand_over", "description": "Pass the chat to a staff member: complaints, refunds, problems with an order, changes to a "
     "confirmed order, anything the tools cannot answer, or when the customer asks for a person or is upset.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
]


def run(ctx: Context, name: str, args: dict) -> dict:
    func = TOOLS.get(name)
    if func is None:
        return {"error": f"There is no tool called {name}."}
    try:
        with transaction.atomic():
            return func(ctx, **{k: v for k, v in (args or {}).items() if isinstance(k, str)})
    except ValidationError as exc:
        return {"error": " ".join(exc.messages)}
    except TypeError:
        return {"error": f"Wrong details for {name}."}


# ---------------------------------------------------------------------------
# Products and shop facts
# ---------------------------------------------------------------------------
def _money(value) -> str:
    return f"{Decimal(value):.2f}"


def _product(p: Product) -> dict:
    unit = {"kg": "kg", "pack": "pack", "each": "item"}[p.unit]
    state = stock.state(p)
    return {
        "product_id": p.pk, "name": p.name, "unit": unit, "price": f"${_money(p.price)} per {unit}",
        "smallest_amount": f"{p.min_quantity.normalize():f}", "steps_of": f"{p.quantity_step.normalize():f}",
        "stock": {"not_counted": "available", "ok": "in stock", "low": "in stock (low)", "out": "out of stock",
                  "below_zero": "out of stock"}[state],
        **({"in_stock": stock.amount_text(max(p.stock_quantity, Decimal("0")), p)} if state in ("low", "out", "below_zero") else {}),
        **({"description": p.description[:200]} if p.description else {}),
    }


def search_products(ctx: Context, query: str = "") -> dict:
    products = Product.objects.filter(is_available=True, is_archived=False)
    words = [w for w in re.split(r"[\s,]+", (query or "").lower()) if len(w) >= 2][:5]
    if words:
        match = Q()
        for word in words:
            match |= Q(name__icontains=word) | Q(search_terms__icontains=word) | Q(sku__iexact=word)
        found = list(products.filter(match)[:50])
        found.sort(key=lambda p: -sum(w in f"{p.name} {p.search_terms}".lower() for w in words))
    else:
        found = list(products.order_by("category__sort_order", "name")[:20])
    return {"products": [_product(p) for p in found[:10]]} if found else {"products": [], "note": "No product matches. Try other words."}


def shop_info(ctx: Context) -> dict:
    from apps.setup.models import BusinessProfile
    from apps.setup.services import business_name

    s = fulfilment.current_settings()
    profile = BusinessProfile.objects.filter(pk=1).first()
    info = {"name": business_name(), "payment": "Customers pay at pickup or on delivery: cash, card (EFTPOS) or bank transfer. No payment in the chat."}
    if profile:
        info["address"] = ", ".join(p for p in (profile.address, profile.suburb, profile.city, profile.postcode) if p)
        info["phone"] = profile.phone
    for kind in (Kind.PICKUP, Kind.DELIVERY):
        if not s.enabled(kind):
            info[kind] = "not offered"
            continue
        hours: dict[str, list[str]] = {}
        for row in OpeningHours.objects.filter(settings=s, kind=kind).order_by("weekday", "opens"):
            hours.setdefault(WEEKDAYS[row.weekday], []).append(f"{row.opens:%H:%M}–{row.closes:%H:%M}")
        info[f"{kind}_hours"] = {day: ", ".join(times) for day, times in hours.items()} or "no hours set"
    if s.delivery_enabled:
        info["delivery_areas"] = [{"area": a.name, "postcodes": a.postcodes, "suburbs": a.suburbs, "fee": f"${_money(a.fee)}",
                                   "minimum_order": f"${_money(a.minimum_order)}",
                                   **({"free_delivery_from": f"${_money(a.free_over)}"} if a.free_over else {})}
                                  for a in DeliveryArea.objects.filter(is_active=True).order_by("sort_order", "name")]
    today = timezone.localdate()
    info["order_ahead"] = f"Orders need {s.lead_minutes} minutes to prepare and can be booked up to {s.days_ahead} days ahead."
    closed = ClosedDay.objects.filter(date__gte=today, date__lte=today + timedelta(days=30)).order_by("date")
    if closed:
        info["closed_days"] = [f"{fulfilment.day_text(d.date)}{f' ({d.reason})' if d.reason else ''}" for d in closed]
    return info


def available_times(ctx: Context, kind: str = "pickup", date: str = "") -> dict:
    if kind not in Kind.values:
        return {"error": "kind must be pickup or delivery."}
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"error": "date must look like 2026-10-23."}
    if not fulfilment.current_settings().enabled(kind):
        return {"error": f"The shop does not offer {kind}."}
    order = ctx.order
    times = [slot for slot in fulfilment.bookable_slots(kind, exclude_order_id=order.pk if order else None)
             if timezone.localtime(slot.start).date() == day]
    if not times:
        return {"date": date, "times": [], "note": "No free times that day (closed, full, too soon or too far ahead)."}
    return {"date": date, "kind": kind, "times": [{"start": timezone.localtime(t.start).strftime("%Y-%m-%dT%H:%M"),
                                                    "label": f"{fulfilment.time_text(t.start)}–{fulfilment.time_text(t.end)}"} for t in times[:24]]}


def check_delivery_address(ctx: Context, address: str = "", suburb: str = "", postcode: str = "") -> dict:
    if not fulfilment.current_settings().delivery_enabled:
        return {"delivers": False, "note": "The shop does not deliver."}
    area = fulfilment.find_area(postcode=(postcode or "").strip(), suburb=suburb or "", address=address or "")
    if area is None:  # find_area only looks at active areas
        return {"delivers": False, "note": "No delivery to this address. Offer pickup."}
    return {"delivers": True, "area": area.name, "fee": f"${_money(area.fee)}", "minimum_order": f"${_money(area.minimum_order)}",
            **({"free_delivery_from": f"${_money(area.free_over)}"} if area.free_over else {})}


# ---------------------------------------------------------------------------
# The order
# ---------------------------------------------------------------------------
def summary(order: Order) -> dict:
    lines = []
    for line in order.lines.all():
        amount = f"{line.quantity.normalize():f}"
        lines.append({"product": line.product_name, "amount": f"{amount} kg" if line.unit == "kg" else amount,
                      "price": f"${_money(line.unit_price)}{' per kg' if line.unit == 'kg' else ''}", "line_total": f"${_money(line.line_total)}"})
    data = {"order_number": order.number, "status": order.status_text, "lines": lines,
            "pickup_or_delivery": order.fulfilment, "time": orders.due_text(order) if order.due_at else "not chosen yet",
            "estimated_total": f"${_money(order.estimated_total)}"}
    if order.is_delivery:
        data["delivery_address"] = ", ".join(p for p in (order.delivery_address, order.delivery_suburb, order.delivery_postcode) if p) or "missing"
        data["delivery_fee"] = f"${_money(order.delivery_fee)}"
    if any(line.unit == "kg" for line in order.lines.all()):
        data["weighed"] = "Products sold by kg are weighed when packed; the final price can change a little."
    if order.notes:
        data["notes"] = order.notes
    return data


def _when(value: str):
    try:
        moment = datetime.strptime(value.strip()[:16], "%Y-%m-%dT%H:%M")
    except (AttributeError, ValueError):
        raise ValidationError("due_at must look like 2026-10-23T10:00 (New Zealand time).") from None
    return timezone.make_aware(moment, timezone.get_current_timezone())


def _lines(lines) -> list:
    if not isinstance(lines, list) or not lines:
        raise ValidationError("Give at least one product line.")
    result = []
    for item in lines[:30]:
        if not isinstance(item, dict):
            raise ValidationError("Each line needs product_id and quantity.")
        try:
            quantity = Decimal(str(item.get("quantity")))
            product_id = int(item.get("product_id"))
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError("Each line needs a product_id (number) and a quantity (number).") from None
        result.append(orders.LineInput(product_id, quantity, str(item.get("note") or "")[:200]))
    return result


def set_order(ctx: Context, lines=None, fulfilment=None, due_at=None, delivery_address=None, delivery_suburb=None,
              delivery_postcode=None, notes=None) -> dict:
    from apps.rbac.policy import module_enabled

    if not module_enabled("orders"):
        return {"error": "Ordering is switched off for this shop. Hand the chat over to staff."}
    fields = {}
    if fulfilment is not None:
        fields["fulfilment"] = fulfilment
    if due_at:
        fields["due_at"] = _when(due_at)
    for name, value in (("delivery_address", delivery_address), ("delivery_suburb", delivery_suburb), ("delivery_postcode", delivery_postcode)):
        if value is not None:
            fields[name] = str(value)[:200]
    if notes is not None:
        fields["notes"] = str(notes)[:500]
    order = ctx.order
    new_lines = _lines(lines) if lines is not None else None
    if order is None:
        if new_lines is None:
            return {"error": "Add the products first (lines)."}
        order = orders.create_order(lines=new_lines, customer=ctx.customer, channel=Order.Channel.WHATSAPP, actor=None, **fields)
        ctx.chat.order = order
        ctx.chat.save(update_fields=["order", "updated_at"])
    else:
        order = orders.update_order(order, lines=new_lines, actor=None, **fields)
    order.refresh_from_db()
    return {"order": summary(order), "problems": orders.warnings(order) or "none"}


def send_for_confirmation(ctx: Context) -> dict:
    order = ctx.order
    if order is None:
        return {"error": "There is no order to send yet."}
    if order.status == S.AWAITING:
        return {"note": "The summary was already sent. The customer must press Yes (or No) on it."}
    if not notify.current_settings().ask_to_confirm:
        return {"error": "The shop switched off confirmation messages. Hand the chat over to staff."}
    orders.change_status(order, S.AWAITING, strict=True, note="Sent to the customer by the AI assistant")
    return {"sent": True, "note": "The customer got the summary with Yes and No buttons. Tell them to press Yes to confirm."}


def past_orders(ctx: Context) -> dict:
    found = Order.objects.filter(customer=ctx.customer, status__in=orders.REORDER_FROM).order_by("-created_at")[:3]
    rows = []
    for order in found:
        items = ", ".join(f"{line.quantity.normalize():f}{' kg' if line.unit == 'kg' else ' x'} {line.product_name}" for line in order.lines.all())
        rows.append({"order_number": order.number, "date": timezone.localtime(order.created_at).strftime("%d %b %Y"), "items": items,
                     "total": f"${_money(order.total)}", "pickup_or_delivery": order.fulfilment})
    return {"orders": rows} if rows else {"orders": [], "note": "This customer has no past orders yet."}


def reorder(ctx: Context, order_number=None) -> dict:
    try:
        number = int(order_number)
    except (TypeError, ValueError):
        return {"error": "order_number must be a number."}
    source = Order.objects.filter(customer=ctx.customer, number=number, status__in=orders.REORDER_FROM).first()
    if source is None:
        return {"error": f"#{number} is not one of this customer's past orders. Use past_orders."}
    if ctx.order is not None:
        return {"error": "An order is already being made in this chat. Change it with set_order, or throw it away with cancel_draft first."}
    order, left_out = orders.reorder(source, channel=Order.Channel.WHATSAPP)
    ctx.chat.order = order
    ctx.chat.save(update_fields=["order", "updated_at"])
    order.refresh_from_db()
    result = {"order": summary(order), "problems": orders.warnings(order) or "none",
              "note": "Prices are today's prices. Ask for the time (and check the address for delivery), then send it for confirmation."}
    if left_out:
        result["left_out"] = left_out
    return result


def cancel_draft(ctx: Context) -> dict:
    order = ctx.order
    if order is None:
        return {"note": "There is no unconfirmed order."}
    if order.status == S.AWAITING:
        order = orders.change_status(order, S.DRAFT, note="Customer no longer wants it (AI assistant)")
    orders.delete_draft(order)
    ctx.chat.order = None
    ctx.chat.save(update_fields=["order", "updated_at"])
    return {"done": True}


def hand_over(ctx: Context, reason: str = "") -> dict:
    ctx.handover = (reason or "The AI asked for help").strip()[:200]
    return {"done": True, "note": "A staff member will answer. Tell the customer this in one short sentence."}


TOOLS = {"search_products": search_products, "shop_info": shop_info, "available_times": available_times,
         "check_delivery_address": check_delivery_address, "set_order": set_order, "send_for_confirmation": send_for_confirmation,
         "past_orders": past_orders, "reorder": reorder, "cancel_draft": cancel_draft, "hand_over": hand_over}
