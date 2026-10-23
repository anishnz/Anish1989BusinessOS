"""
Everything the public page shows (task 2.9): the published texts plus live
facts from the system (products and prices, opening hours, closed days,
delivery areas, contact details). Only public facts: nothing about orders,
customers, stock numbers or staff.
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.utils import timezone

from . import content

UNIT = {"kg": "per kg", "each": "each", "pack": "per pack"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCHEMA_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


def products() -> list[dict]:
    """Available products by category, in the category order; out-of-stock products are marked, not hidden."""
    from apps.catalog import stock
    from apps.catalog.models import Product

    groups: dict[str, list] = {}
    rows = (Product.objects.filter(is_archived=False, is_available=True).select_related("category")
            .order_by("category__sort_order", "category__name", "name"))
    for p in rows:
        name = p.category.name if p.category and p.category.is_active else "Other"
        groups.setdefault(name, []).append({
            "name": p.name, "description": p.description, "price": f"{p.price:.2f}", "unit": UNIT.get(p.unit, ""),
            "sold_out": stock.state(p) in ("out", "below_zero"),
        })
    return [{"name": name, "products": items} for name, items in groups.items()]


def _time(value) -> str:
    return value.strftime("%-I:%M %p").replace(":00", "").lower() if value else ""


def hours() -> dict:
    """Pickup and delivery hours per day, and the closed days in the next 30 days."""
    from apps.fulfilment import services as fulfilment
    from apps.fulfilment.models import ClosedDay

    s = fulfilment.current_settings()
    kinds = []
    for kind, label, enabled in (("pickup", "Pickup", s.pickup_enabled), ("delivery", "Delivery", s.delivery_enabled)):
        if not enabled:
            continue
        rows = list(s.hours.filter(kind=kind).order_by("weekday", "opens"))
        days = [{"day": DAY_NAMES[d], "times": ", ".join(f"{_time(r.opens)} – {_time(r.closes)}" for r in rows if r.weekday == d) or "Closed"}
                for d in range(7)]
        kinds.append({"label": label, "days": days, "rows": rows})
    today = timezone.localdate()
    closed = [{"date": c.date, "reason": c.reason}
              for c in ClosedDay.objects.filter(date__gte=today, date__lte=today + timedelta(days=30)).order_by("date")]
    return {"kinds": kinds, "closed": closed}


def delivery() -> list[dict]:
    from apps.fulfilment import services as fulfilment
    from apps.fulfilment.models import DeliveryArea

    if not fulfilment.current_settings().delivery_enabled:
        return []
    return [{"name": a.name, "fee": f"{a.fee:.2f}", "minimum": f"{a.minimum_order:.2f}" if a.minimum_order else "",
             "free_over": f"{a.free_over:.2f}" if a.free_over is not None else ""}
            for a in DeliveryArea.objects.filter(is_active=True).order_by("name")]


def contact() -> dict:
    from apps.setup.models import BusinessProfile

    p = BusinessProfile.objects.filter(pk=1).first()
    if p is None:
        return {}
    address = ", ".join(x for x in (p.address, p.suburb, p.city, p.postcode) if x)
    return {"address": address, "phone": p.phone, "email": p.email,
            "map": f"https://www.google.com/maps/search/?api=1&query={address.replace(' ', '+')}" if address else ""}


def build(texts: dict, *, url: str = "") -> dict:
    """The template context for one version of the texts (the live one, or the draft for the preview)."""
    from apps.setup.services import business_name

    c = contact()
    h = hours() if texts.get("show_hours") else {"kinds": [], "closed": []}
    whatsapp = "".join(ch for ch in texts.get("whatsapp_number", "") if ch.isdigit())
    data = {
        "t": texts,
        "hero": paragraphs(texts.get("hero_text", "")),
        "about": paragraphs(texts.get("about_text", "")),
        "products_intro": paragraphs(texts.get("products_text", "")),
        "contact_intro": paragraphs(texts.get("contact_text", "")),
        "groups": products() if texts.get("show_products") else [],
        "hours": h,
        "areas": delivery() if texts.get("show_delivery") else [],
        "contact": c,
        "whatsapp": f"https://wa.me/{whatsapp}" if texts.get("show_whatsapp") and whatsapp else "",
        "url": url,
        "year": timezone.localdate().year,
        "business": business_name(),
        "enquiry": enquiry_form_on(),
    }
    data["json_ld"] = json_ld(data, texts, url)
    return data


def json_ld(data: dict, texts: dict, url: str) -> str:
    """schema.org LocalBusiness facts for search engines (name, address, phone, opening hours)."""
    c = data["contact"]
    info = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": data["business"],
            "description": texts.get("seo_description", "")}
    if url:
        info["url"] = url
    if c.get("phone"):
        info["telephone"] = c["phone"]
    if c.get("address"):
        info["address"] = {"@type": "PostalAddress", "streetAddress": c["address"], "addressCountry": "NZ"}
    pickup = next((k for k in data["hours"]["kinds"] if k["label"] == "Pickup"), None)
    if pickup:
        info["openingHours"] = [f"{SCHEMA_DAYS[r.weekday]} {r.opens:%H:%M}-{r.closes:%H:%M}" for r in pickup["rows"]]
    # Safe inside <script>: "<" is escaped, so no text can close the tag.
    return json.dumps(info, ensure_ascii=False).replace("<", "\\u003c")


def enquiry_form_on() -> bool:
    """The "Ask for a quote" button links to the enquiry form (task 3.1) when it is open."""
    from apps.events.services import form_available

    return form_available()


def live_page(url: str = "") -> dict:
    return build(content.live_content(), url=url)
