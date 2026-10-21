"""
Pickup and delivery rules (task 2.1, D-120 to D-122).

- Slots come from the opening hours: a day from 9:00 to 12:00 with 30-minute
  slots has six slots (9:00, 9:30 ... 11:30). Closed days have none.
- A slot is full when the orders in it (from "Awaiting customer confirmation"
  on, not cancelled or expired) reach the "orders per slot" number.
- Customers (the WhatsApp AI and the website) can only choose a free slot
  that starts after the preparation time and within the days ahead.
- Staff may book outside these rules; the order then shows the problems as
  warnings (D-121). A delivery order always needs an address, an area and a
  time (D-122).
- Delivery areas are found by postcode first, then by suburb name.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import WEEKDAYS, ClosedDay, DeliveryArea, FulfilmentSettings, Kind, OpeningHours

ZERO = Decimal("0.00")
POSTCODE = re.compile(r"(?<!\d)(\d{4})(?!\d)")

# Order statuses that take a place in a slot (D-120). Strings, so this module
# does not import the orders app (which imports this one).
COUNTING_STATUSES = (
    "awaiting_confirmation", "confirmed", "preparing", "final_price_sent", "final_price_accepted", "ready", "out_for_delivery", "completed",
)


def current_settings() -> FulfilmentSettings:
    row = FulfilmentSettings.objects.order_by("pk").first()
    return row if row is not None else FulfilmentSettings.objects.create()


# ---------------------------------------------------------------------------
# Words for people
# ---------------------------------------------------------------------------
def day_text(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def time_text(value: datetime) -> str:
    return timezone.localtime(value).strftime("%H:%M")


def when_text(value: datetime) -> str:
    local = timezone.localtime(value)
    return f"{day_text(local.date())} {local:%H:%M}"


def minutes_text(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} hour{'s' if hours > 1 else ''}" if hours else f"{mins} minutes"


@dataclass
class Slot:
    kind: str
    start: datetime
    end: datetime
    taken: int = 0
    capacity: int = 0  # 0 = no limit

    @property
    def full(self) -> bool:
        return self.capacity > 0 and self.taken >= self.capacity

    @property
    def label(self) -> str:
        return f"{day_text(timezone.localtime(self.start).date())} {time_text(self.start)}–{time_text(self.end)}"

    def as_json(self) -> dict:
        return {
            "kind": self.kind, "start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label,
            "taken": self.taken, "capacity": self.capacity, "full": self.full,
        }


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------
def _aware(day: date, at: time) -> datetime | None:
    """Local date and time to an aware datetime; None when the time does not exist (clocks going forward)."""
    tz = timezone.get_current_timezone()
    value = datetime.combine(day, at).replace(tzinfo=tz)
    back = value.astimezone(dt_timezone.utc).astimezone(tz)
    return value if back.replace(tzinfo=None) == value.replace(tzinfo=None) else None


def _counting_times(kind: str, start: datetime, end: datetime, exclude_order_id=None) -> list[datetime]:
    from apps.orders.models import Order

    qs = Order.objects.filter(fulfilment=kind, status__in=COUNTING_STATUSES, due_at__gte=start, due_at__lt=end)
    if exclude_order_id:
        qs = qs.exclude(pk=exclude_order_id)
    return list(qs.values_list("due_at", flat=True))


def slots(kind: str, first_day: date, days: int = 1, *, exclude_order_id=None) -> list[Slot]:
    """Every slot from the opening hours (free or full), for `days` days from `first_day`."""
    s = current_settings()
    length = timedelta(minutes=s.slot_minutes(kind))
    capacity = s.capacity(kind)
    hours = defaultdict(list)
    for row in OpeningHours.objects.filter(settings=s, kind=kind):
        hours[row.weekday].append(row)
    closed = set(ClosedDay.objects.filter(date__gte=first_day, date__lt=first_day + timedelta(days=days)).values_list("date", flat=True))
    found: list[Slot] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        if day in closed:
            continue
        for row in sorted(hours.get(day.weekday(), []), key=lambda r: r.opens):
            at, limit = datetime.combine(day, row.opens), datetime.combine(day, row.closes)
            while at + length <= limit:
                start, end = _aware(day, at.time()), _aware(day, (at + length).time())
                if start and end and end > start:
                    found.append(Slot(kind, start, end, 0, capacity))
                at += length
    if found:
        times = _counting_times(kind, found[0].start, found[-1].end, exclude_order_id)
        for slot in found:
            slot.taken = sum(1 for t in times if slot.start <= t < slot.end)
    return found


def bookable_slots(kind: str, *, now: datetime | None = None, exclude_order_id=None, include_full: bool = False) -> list[Slot]:
    """The slots a customer can choose now: after the preparation time, within the days ahead, not full."""
    s = current_settings()
    if not s.enabled(kind):
        return []
    now = now or timezone.now()
    earliest = now + timedelta(minutes=s.lead_minutes)
    found = slots(kind, timezone.localdate(now), s.days_ahead, exclude_order_id=exclude_order_id)
    return [slot for slot in found if slot.start >= earliest and (include_full or not slot.full)]


def time_problems(kind: str, due_at: datetime, *, exclude_order_id=None, now: datetime | None = None, exact: bool = False) -> list[str]:
    """Why `due_at` breaks the slot rules (empty list = fine). `exact`: it must be the start of a slot."""
    s = current_settings()
    now = now or timezone.now()
    problems = []
    word = "delivery" if kind == Kind.DELIVERY else "pickup"
    if due_at < now:
        problems.append(f"{when_text(due_at)} is in the past.")
    elif due_at < now + timedelta(minutes=s.lead_minutes):
        problems.append(f"{when_text(due_at)} is too soon: orders need {minutes_text(s.lead_minutes)} to prepare.")
    day = timezone.localtime(due_at).date()
    if day >= timezone.localdate(now) + timedelta(days=s.days_ahead):
        problems.append(f"{day_text(day)} is too far ahead: customers can choose up to {s.days_ahead} day{'s' if s.days_ahead > 1 else ''} ahead.")
    closed = ClosedDay.objects.filter(date=day).first()
    if closed:
        problems.append(f"Closed on {day_text(day)}{f' ({closed.reason})' if closed.reason else ''}.")
        return problems
    slot = next((x for x in slots(kind, day, 1, exclude_order_id=exclude_order_id) if x.start <= due_at < x.end), None)
    if slot is None:
        problems.append(f"{time_text(due_at)} is outside the {word} hours on {day:%A}.")
        return problems
    if exact and slot.start != due_at:
        problems.append(f"Choose one of the {word} times (for example {time_text(slot.start)}).")
    if slot.full:
        problems.append(f"The {slot.label} {word} slot is full ({slot.taken} of {slot.capacity} orders).")
    return problems


def lock_bookings() -> None:
    """Customer bookings take turns (inside the caller's transaction), so two customers never take the last place in a slot at once."""
    FulfilmentSettings.objects.select_for_update().get(pk=current_settings().pk)


def slot_end_for(kind: str, due_at: datetime | None) -> datetime | None:
    """The end of the slot that starts exactly at `due_at` (None for any other time)."""
    if due_at is None:
        return None
    day = timezone.localtime(due_at).date()
    return next((x.end for x in slots(kind, day, 1) if x.start == due_at), None)


# ---------------------------------------------------------------------------
# Delivery areas
# ---------------------------------------------------------------------------
def normalise_suburb(name: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip().lower())
    name = re.sub(r"\bmt\.?(?=\s)", "mount", name)
    return re.sub(r"\bst\.?(?=\s)", "saint", name)


def postcode_in(text: str) -> str:
    """The last 4-digit number in an address (New Zealand postcodes have 4 digits)."""
    found = POSTCODE.findall(text or "")
    return found[-1] if found else ""


def find_area(*, postcode: str = "", suburb: str = "", address: str = "") -> DeliveryArea | None:
    """The active delivery area for a postcode (first) or suburb name."""
    areas = list(DeliveryArea.objects.filter(is_active=True))
    code = (postcode or "").strip() or postcode_in(address)
    if code:
        for area in areas:
            if code in area.postcode_list():
                return area
    wanted = normalise_suburb(suburb)
    if wanted:
        for area in areas:
            if wanted in {normalise_suburb(x) for x in area.suburb_list()}:
                return area
    return None


def delivery_fee(area: DeliveryArea, products_total: Decimal) -> Decimal:
    if area.free_over is not None and products_total >= area.free_over:
        return ZERO
    return area.fee


def check_area(area: DeliveryArea) -> None:
    """Postcodes must have 4 digits, and a postcode or suburb can only be in one active area."""
    problems = []
    codes = area.postcode_list()
    bad = [c for c in codes if not re.fullmatch(r"\d{4}", c)]
    if bad:
        problems.append(f"Postcodes have 4 digits: {', '.join(bad)}.")
    if not codes and not area.suburb_list():
        problems.append("Add at least one postcode or suburb.")
    if area.is_active:
        others = DeliveryArea.objects.filter(is_active=True).exclude(pk=area.pk)
        for other in others:
            same = sorted(set(codes) & set(other.postcode_list()))
            if same:
                problems.append(f"{', '.join(same)} {'is' if len(same) == 1 else 'are'} already in the area “{other.name}”.")
            mine = {normalise_suburb(x) for x in area.suburb_list()}
            same_suburbs = sorted(x for x in other.suburb_list() if normalise_suburb(x) in mine)
            if same_suburbs:
                problems.append(f"{', '.join(same_suburbs)} {'is' if len(same_suburbs) == 1 else 'are'} already in the area “{other.name}”.")
    if problems:
        raise ValidationError(problems)


def check_hours(rows: list[tuple[str, int, time, time]]) -> None:
    """Opening hours of the same kind and day must not overlap."""
    by_day = defaultdict(list)
    for kind, weekday, opens, closes in rows:
        if opens >= closes:
            raise ValidationError(f"{Kind(kind).label}, {dict(WEEKDAYS)[weekday]}: “Until” must be later than “From”.")
        by_day[(kind, weekday)].append((opens, closes))
    for (kind, weekday), periods in by_day.items():
        periods.sort()
        for (_, end), (start, _) in zip(periods, periods[1:]):
            if start < end:
                raise ValidationError(f"{Kind(kind).label}, {dict(WEEKDAYS)[weekday]}: two periods overlap. Join them or change the times.")


# ---------------------------------------------------------------------------
# Problems with an order (used by the order rules)
# ---------------------------------------------------------------------------
def required_problems(order) -> list[str]:
    """What every delivery order needs, also when staff book it (D-122)."""
    if order.fulfilment != Kind.DELIVERY:
        return []
    problems = []
    if not (order.delivery_address or "").strip():
        problems.append("Add the delivery address.")
    if order.delivery_area_id is None:
        problems.append("Choose the delivery area (we could not find one for this postcode or suburb).")
    if order.due_at is None:
        problems.append("Choose a delivery time.")
    return problems


def rule_problems(order, products_total: Decimal, *, now: datetime | None = None, exact: bool = False) -> list[str]:
    """Slot, area and minimum-order rules. Customers must follow them; for staff they are warnings (D-121)."""
    s = current_settings()
    kind = order.fulfilment
    problems = []
    if not s.enabled(kind):
        problems.append(f"{Kind(kind).label} is switched off in the pickup and delivery settings.")
    if kind == Kind.DELIVERY and order.delivery_area_id is not None:
        area = order.delivery_area
        if not area.is_active:
            problems.append(f"You do not deliver to “{area.name}” at the moment.")
        elif products_total < area.minimum_order:
            problems.append(f"The minimum order for delivery to “{area.name}” is ${area.minimum_order} of products; this order has ${products_total}.")
    if order.due_at is not None:
        problems += time_problems(kind, order.due_at, exclude_order_id=order.pk, now=now, exact=exact)
    elif exact:
        problems.append("Choose a pickup time.")
    return problems
