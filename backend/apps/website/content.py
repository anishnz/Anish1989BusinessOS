"""
What the one-page website says, and the draft / publish / history rules
(task 2.9, D-164 to D-167).

Texts are plain text: no HTML (the page escapes everything), new lines in
long texts become paragraphs. Every text has a length limit; SEO texts use
the limits search engines show.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import WebsiteDraft, WebsiteVersion

KEEP_VERSIONS = 20


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    limit: int
    long: bool = False
    help: str = ""


TEXTS = [
    Field("site_title", "Website name", 60, help="Shown at the top of the page and in the browser tab."),
    Field("tagline", "Short line under the name", 120),
    Field("hero_heading", "Main heading", 80),
    Field("hero_text", "Welcome text", 600, long=True),
    Field("about_heading", "About heading", 80),
    Field("about_text", "About text", 2000, long=True, help="Who you are, what you sell, what makes you different."),
    Field("products_heading", "Products heading", 80),
    Field("products_text", "Text above the products", 400, long=True),
    Field("contact_heading", "Contact heading", 80),
    Field("contact_text", "Contact text", 400, long=True),
    Field("seo_title", "Title in Google", 60, help="About 50 to 60 characters. Shown as the blue link in search results."),
    Field("seo_description", "Description in Google", 160, long=True, help="About 120 to 160 characters. Shown under the link."),
]
TEXT_KEYS = [f.key for f in TEXTS]
FIELDS = {f.key: f for f in TEXTS}
SWITCHES = {
    "show_products": "Show products and prices",
    "show_hours": "Show opening hours",
    "show_delivery": "Show delivery areas and fees",
    "show_whatsapp": "Show a WhatsApp button",
}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def defaults() -> dict:
    """A sensible first draft from the business details, so the site works before anyone edits it."""
    from apps.setup.models import BusinessProfile
    from apps.setup.services import business_name

    name = business_name()
    profile = BusinessProfile.objects.filter(pk=1).first()
    place = ", ".join(p for p in ((profile.suburb if profile else ""), (profile.city if profile else "")) if p) or "New Zealand"
    return {
        "site_title": name[:60],
        "tagline": f"Order on WhatsApp for pickup or delivery in {place}"[:120],
        "hero_heading": f"Welcome to {name}"[:80],
        "hero_text": "Send us your order on WhatsApp. We confirm it, prepare it fresh, and tell you when it is ready.",
        "about_heading": "About us",
        "about_text": f"{name} is a local business in {place}.",
        "products_heading": "Our products",
        "products_text": "Prices include GST. Products sold by weight are weighed when we pack your order.",
        "contact_heading": "Find us",
        "contact_text": "Message us on WhatsApp or visit us in store.",
        "seo_title": f"{name} – {place}"[:60],
        "seo_description": f"{name} in {place}. Order on WhatsApp for pickup or delivery."[:160],
        "whatsapp_number": profile.phone if profile else "",
        **{key: True for key in SWITCHES},
    }


def clean(data: dict) -> dict:
    """Check and tidy content sent by the editor. Unknown keys are dropped; missing ones keep their default."""
    from apps.customers.services import normalise_phone

    if not isinstance(data, dict):
        raise ValidationError("Send the website texts as an object.")
    result = defaults()
    errors = {}
    for f in TEXTS:
        if f.key not in data:
            continue
        value = data[f.key]
        if not isinstance(value, str):
            errors[f.key] = "Must be text."
            continue
        value = CONTROL.sub("", value.replace("\r\n", "\n")).strip()
        if not f.long:
            value = " ".join(value.split())
        else:
            value = re.sub(r"\n{3,}", "\n\n", value)
        if len(value) > f.limit:
            errors[f.key] = f"At most {f.limit} characters ({len(value)} now)."
        if f.key in ("site_title", "seo_title") and not value:
            errors[f.key] = "This cannot be empty."
        result[f.key] = value
    for key in SWITCHES:
        if key in data:
            result[key] = bool(data[key])
    if "whatsapp_number" in data:
        try:
            result["whatsapp_number"] = normalise_phone(str(data["whatsapp_number"] or ""))
        except ValidationError as exc:
            errors["whatsapp_number"] = " ".join(exc.messages)
    if errors:
        raise ValidationError(errors)
    return result


# ---------------------------------------------------------------------------
# Draft, publish, history
# ---------------------------------------------------------------------------
def draft() -> WebsiteDraft:
    row = WebsiteDraft.objects.filter(pk=1).first()
    if row is None:
        row, _ = WebsiteDraft.objects.get_or_create(pk=1, defaults={"content": defaults()})
    return row


def draft_content() -> dict:
    return {**defaults(), **draft().content}


def live() -> WebsiteVersion | None:
    return WebsiteVersion.objects.order_by("-number").first()


def live_content() -> dict:
    """What visitors see: the newest published version, or the first draft defaults before anything was published."""
    version = live()
    return {**defaults(), **version.content} if version else defaults()


def save_draft(data: dict, *, actor=None) -> WebsiteDraft:
    content = clean(data)
    row = draft()
    row.content = content
    row.updated_by_email = getattr(actor, "email", "") or ""
    row.save()
    return row


def unpublished_changes() -> bool:
    version = live()
    return version is None or {**defaults(), **version.content} != draft_content()


@transaction.atomic
def publish(*, actor=None, note: str = "") -> WebsiteVersion:
    from apps.audit.services import audit

    content = clean(draft_content())  # checked again: the rules may have changed since it was saved
    last = WebsiteVersion.objects.select_for_update().order_by("-number").first()
    version = WebsiteVersion.objects.create(number=(last.number + 1) if last else 1, content=content,
                                            published_by_email=getattr(actor, "email", "") or "", note=note[:120])
    keep = WebsiteVersion.objects.order_by("-number").values_list("pk", flat=True)[:KEEP_VERSIONS]
    WebsiteVersion.objects.exclude(pk__in=list(keep)).delete()
    audit("website.published", actor=actor, metadata={"version": version.number})
    return version


@transaction.atomic
def restore(number: int, *, actor=None) -> WebsiteDraft:
    """Copy an older published version into the draft (publish it to make it live)."""
    from apps.audit.services import audit

    version = WebsiteVersion.objects.filter(number=number).first()
    if version is None:
        raise ValidationError("That version is no longer kept.")
    row = draft()
    row.content = {**defaults(), **version.content}
    row.updated_by_email = getattr(actor, "email", "") or ""
    row.save()
    audit("website.restored", actor=actor, metadata={"version": number})
    return row
