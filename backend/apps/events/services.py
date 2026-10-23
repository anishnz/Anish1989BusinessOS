"""
Enquiry actions (task 3.1). Staff, the website form and the AI all use these,
so the same checks apply everywhere. Every change is audited, with field
names only: the details themselves are personal data.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.services import audit
from apps.customers import services as customers
from apps.customers.models import Customer

from .models import Enquiry, EnquiryActivity, EnquirySettings

log = logging.getLogger(__name__)
S = Enquiry.Status

MAX_GUESTS = 10000
MAX_BUDGET = Decimal("1000000")
DAYS_AHEAD = 3 * 365
AI_ENQUIRY_DAYS = 14  # the AI keeps working on its New enquiry from the same chat for this long

# Field name: (label, longest text). Order = the order on screens.
TEXT_FIELDS = {
    "contact_name": ("Name", 150),
    "venue": ("Venue", 300),
    "menu": ("Food and drinks", 2000),
    "dietary_needs": ("Dietary needs", 1000),
    "message": ("Message", 3000),
}
LABELS = {
    "contact_name": "Name", "contact_phone": "Phone", "contact_email": "Email", "event_type": "Type of event",
    "event_date": "Date", "start_time": "Start time", "end_time": "End time", "venue": "Venue", "guests": "Guests",
    "menu": "Food and drinks", "dietary_needs": "Dietary needs", "budget": "Budget", "message": "Message",
}
DETAIL_FIELDS = tuple(LABELS)


def current_settings() -> EnquirySettings:
    row, _ = EnquirySettings.objects.get_or_create(pk=1)
    return row


def module_on() -> bool:
    from apps.rbac.policy import module_enabled

    return module_enabled("events")


def form_available() -> bool:
    """The website form is open: the events module is on and the business has not switched the form off."""
    return module_on() and current_settings().form_enabled


# ---------------------------------------------------------------------------
# Checking the details
# ---------------------------------------------------------------------------
def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ValidationError({"event_date": "Use a date like 2026-12-24."}) from None


def _time(value, key: str) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value).strip()[:5])
    except ValueError:
        raise ValidationError({key: "Use a time like 18:30."}) from None


def _whole(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValidationError({"guests": "Use a number of guests, for example 80."}) from None
    if number != number.to_integral_value() or number < 1 or number > MAX_GUESTS:
        raise ValidationError({"guests": f"Use a whole number from 1 to {MAX_GUESTS}."})
    return int(number)


def _money(value) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("$", "").replace(",", "").replace("NZ", "").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValidationError({"budget": "Use an amount in NZ$, for example 2500."}) from None
    if not amount.is_finite() or amount < 0 or amount > MAX_BUDGET:
        raise ValidationError({"budget": f"Use an amount from 0 to {MAX_BUDGET:,.0f}."})
    return amount.quantize(Decimal("0.01"))


def clean_details(data: dict, *, partial: bool = False, today: date | None = None, existing: Enquiry | None = None) -> dict:
    """
    Check the event details. `partial`: only the fields given are checked
    (staff and AI changes). Returns the cleaned values; raises a
    ValidationError with a message per field.
    """
    data = data or {}
    today = today or timezone.localdate()
    out: dict = {}
    errors: dict[str, str] = {}

    def run(key, fn):
        if partial and key not in data:
            return
        try:
            out[key] = fn(data.get(key))
        except ValidationError as exc:
            errors.update({k: " ".join(v) for k, v in exc.message_dict.items()} if hasattr(exc, "message_dict") else {key: " ".join(exc.messages)})

    for key, (label, limit) in TEXT_FIELDS.items():
        def text(value, key=key, label=label, limit=limit):
            value = str(value or "").strip()
            if len(value) > limit:
                raise ValidationError({key: f"{label}: at most {limit} characters."})
            return value
        run(key, text)

    def phone(value):
        try:
            return customers.normalise_phone(str(value or ""))
        except ValidationError as exc:
            raise ValidationError({"contact_phone": " ".join(exc.messages)}) from None

    def email(value):
        try:
            return customers.clean_email(str(value or ""))
        except ValidationError as exc:
            raise ValidationError({"contact_email": " ".join(exc.messages)}) from None

    def event_type(value):
        value = str(value or "").strip()
        if value and value not in Enquiry.EventType.values:
            raise ValidationError({"event_type": "Choose a type of event from the list."})
        return value

    def event_date(value):
        value = _date(value)
        if value is not None:
            unchanged = existing is not None and existing.event_date == value
            if value < today and not unchanged:
                raise ValidationError({"event_date": "The date has already passed."})
            if value > today + timedelta(days=DAYS_AHEAD):
                raise ValidationError({"event_date": "The date is more than 3 years away."})
        return value

    run("contact_phone", phone)
    run("contact_email", email)
    run("event_type", event_type)
    run("event_date", event_date)
    run("start_time", lambda v: _time(v, "start_time"))
    run("end_time", lambda v: _time(v, "end_time"))
    run("guests", _whole)
    run("budget", _money)
    if errors:
        raise ValidationError(errors)
    return out


def _check_whole(enquiry: Enquiry) -> None:
    """Rules that need more than one field."""
    if enquiry.start_time and enquiry.end_time and enquiry.end_time == enquiry.start_time:
        raise ValidationError({"end_time": "The end time is the same as the start time."})


# ---------------------------------------------------------------------------
# Creating and changing
# ---------------------------------------------------------------------------
def _actor_email(actor) -> str:
    return getattr(actor, "email", "") if actor is not None and getattr(actor, "is_authenticated", False) else ""


def _log(enquiry: Enquiry, kind: str, text: str = "", actor=None) -> EnquiryActivity:
    return EnquiryActivity.objects.create(enquiry=enquiry, kind=kind, text=text[:2000], by_email=_actor_email(actor))


def customer_for(name: str, phone: str, email: str, *, source: str) -> Customer | None:
    """The customer with this phone or email, or a new one. None when neither was given."""
    if not phone and not email:
        return None
    found = customers.find_duplicate(phone=phone, email=email)
    if found is not None:
        changed = []
        if phone and not found.phone and not Customer.objects.filter(phone=phone).exists():
            found.phone = phone
            changed.append("phone")
        if email and not found.email and not Customer.objects.filter(email__iexact=email).exists():
            found.email = email
            changed.append("email")
        if changed:
            found.save(update_fields=[*changed, "updated_at"])
        return found
    customer = Customer.objects.create(name=(name or "Unknown")[:150], phone=phone, email=email, source=source)
    audit("crm.customer_create", target=customer, metadata={"source": source})
    return customer


@transaction.atomic
def create(data: dict, *, source: str, actor=None, customer: Customer | None = None, conversation=None,
           marketing_consent: bool = False, notify: bool = True) -> Enquiry:
    if source not in Enquiry.Source.values:
        raise ValidationError("Unknown source.")
    if not module_on():
        raise ValidationError("Catering and events is switched off for this business.")
    values = clean_details(data)
    if customer is not None and customer.is_anonymised:
        raise ValidationError("This customer's personal data was removed.")
    if customer is None:
        customer = customer_for(values.get("contact_name", ""), values.get("contact_phone", ""), values.get("contact_email", ""),
                                source=Customer.Source.WEBSITE if source == Enquiry.Source.WEBSITE else
                                Customer.Source.WHATSAPP if source == Enquiry.Source.WHATSAPP else Customer.Source.MANUAL)
    if source == Enquiry.Source.WEBSITE and customer is None:
        raise ValidationError({"contact_phone": "Give a phone number or an email address, so we can reply."})
    enquiry = Enquiry(source=source, customer=customer, conversation=conversation, created_by=actor if _actor_email(actor) else None, **values)
    if customer is not None:  # fill the contact details from the customer when they were not given
        enquiry.contact_name = enquiry.contact_name or customer.name
        enquiry.contact_phone = enquiry.contact_phone or customer.phone
        enquiry.contact_email = enquiry.contact_email or customer.email
    _check_whole(enquiry)
    enquiry.save()
    _log(enquiry, EnquiryActivity.Kind.CREATED, Enquiry.Source(source).label, actor)
    audit("events.enquiry_create", target=enquiry, actor=actor, metadata={"source": source, "customer": customer.pk if customer else None})
    if marketing_consent and customer is not None and not customer.marketing_consent:
        customers.set_marketing_consent(customer, True, source="website", note="Ticked on the enquiry form")
    if notify and source != Enquiry.Source.STAFF:
        schedule_staff_email(enquiry)
    return enquiry


@transaction.atomic
def update(enquiry: Enquiry, data: dict, *, actor=None) -> list[str]:
    """Change the details given in `data`. Returns the labels of the fields that changed."""
    enquiry = Enquiry.objects.select_for_update(of=("self",)).get(pk=enquiry.pk)
    values = clean_details(data or {}, partial=True, existing=enquiry)  # only the detail fields are read
    changed = [k for k, v in values.items() if getattr(enquiry, k) != v]
    if not changed:
        return []
    for key in changed:
        setattr(enquiry, key, values[key])
    _check_whole(enquiry)
    enquiry.save()
    labels = [LABELS[k] for k in changed]
    _log(enquiry, EnquiryActivity.Kind.CHANGED, ", ".join(labels), actor)
    audit("events.enquiry_update", target=enquiry, actor=actor, metadata={"fields": changed})
    return labels


@transaction.atomic
def set_status(enquiry: Enquiry, status: str, *, reason: str = "", actor=None) -> Enquiry:
    enquiry = Enquiry.objects.select_for_update(of=("self",)).get(pk=enquiry.pk)
    if status not in S.values:
        raise ValidationError("Unknown status.")
    reason = (reason or "").strip()
    if status == enquiry.status:
        raise ValidationError(f"The enquiry is already {enquiry.get_status_display()}.")
    if status == S.LOST and not reason:
        raise ValidationError({"reason": "Give a short reason, for example “booked another caterer” or “too expensive”."})
    if len(reason) > 200:
        raise ValidationError({"reason": "At most 200 characters."})
    before = enquiry.status
    enquiry.status = status
    enquiry.lost_reason = reason if status == S.LOST else ""
    enquiry.status_changed_at = timezone.now()
    enquiry.save(update_fields=["status", "lost_reason", "status_changed_at", "updated_at"])
    label = S(status).label
    _log(enquiry, EnquiryActivity.Kind.STATUS, f"{label}: {reason}" if reason and status == S.LOST else label, actor)
    audit("events.enquiry_status", target=enquiry, actor=actor, changes={"status": [before, status]})
    return enquiry


def add_note(enquiry: Enquiry, text: str, *, actor=None) -> EnquiryActivity:
    text = (text or "").strip()
    if not text:
        raise ValidationError({"text": "Write a note."})
    if len(text) > 2000:
        raise ValidationError({"text": "At most 2000 characters."})
    note = _log(enquiry, EnquiryActivity.Kind.NOTE, text, actor)
    Enquiry.objects.filter(pk=enquiry.pk).update(updated_at=timezone.now())
    audit("events.enquiry_note", target=enquiry, actor=actor)
    return note


def from_conversation(conversation, *, actor=None) -> Enquiry:
    """Staff: "Make enquiry" in the inbox. Uses the chat's customer; the details are filled in afterwards."""
    if conversation.customer_id is None:
        raise ValidationError("This chat has no customer.")
    return create({}, source=Enquiry.Source.WHATSAPP, actor=actor, customer=conversation.customer, conversation=conversation, notify=False)


def open_for_chat(conversation) -> Enquiry | None:
    """The New enquiry the AI is filling in for this chat (made in the last 14 days), if any."""
    since = timezone.now() - timedelta(days=AI_ENQUIRY_DAYS)
    return (Enquiry.objects.filter(conversation=conversation, status=S.NEW, created_at__gte=since)
            .order_by("-created_at").first())


def missing(enquiry: Enquiry) -> list[str]:
    """What a quote still needs (shown to staff and told to the AI)."""
    need = {"event_type": "type of event", "event_date": "date", "start_time": "start time", "venue": "venue",
            "guests": "number of guests", "menu": "food and drinks"}
    return [label for key, label in need.items() if not getattr(enquiry, key)]


# ---------------------------------------------------------------------------
# Telling staff
# ---------------------------------------------------------------------------
def staff_recipients() -> list[str]:
    from apps.accounts.models import User
    from apps.rbac import policy

    return sorted({u.email for u in User.objects.filter(is_active=True, is_staff=True).exclude(email="")
                   if policy.has_perm(u, "events.edit")})


def schedule_staff_email(enquiry: Enquiry) -> None:
    if not current_settings().email_staff:
        return
    schema, pk = connection.schema_name, enquiry.pk

    def start():
        from .tasks import staff_email_task

        staff_email_task.delay(schema, pk)

    transaction.on_commit(start)


def send_staff_email(enquiry: Enquiry) -> bool:
    """One short email: who, when, how many guests and a link. Never the message or dietary needs."""
    from django.core.mail import send_mail

    from apps.health.services import current_tenant
    from apps.setup.services import business_name
    from apps.tenants.domains import main_address, site_url

    recipients = staff_recipients()
    if not recipients:
        return False
    tenant = current_tenant()
    link = site_url(main_address(tenant), None, f"/app/enquiries/{enquiry.pk}") if tenant else ""
    when = f"{enquiry.event_date:%A %d %B %Y}" if enquiry.event_date else "date not given"
    guests = f"{enquiry.guests} guests" if enquiry.guests else "guests not given"
    kind = enquiry.get_event_type_display() if enquiry.event_type else "Event"
    body = (f"New enquiry from {enquiry.name or 'a customer'} ({enquiry.get_source_display()}).\n\n"
            f"{kind}, {when}, {guests}.\n\nOpen it: {link}\n")
    try:
        send_mail(f"New enquiry #{enquiry.pk} ({business_name()})", body, None, recipients)
    except Exception:  # noqa: BLE001 - the email must not break anything
        log.exception("Enquiry email could not be sent")
        return False
    audit("events.enquiry_email", target=enquiry, metadata={"recipients": len(recipients)})
    return True


# ---------------------------------------------------------------------------
# Removing personal data
# ---------------------------------------------------------------------------
def forget_customer(sender, customer, **kwargs) -> None:
    """When a customer's personal data is removed, remove it from their enquiries too (the numbers stay for reports)."""
    rows = Enquiry.objects.filter(customer=customer)
    EnquiryActivity.objects.filter(enquiry__in=rows, kind=EnquiryActivity.Kind.NOTE).update(text="")
    EnquiryActivity.objects.filter(enquiry__in=rows, kind=EnquiryActivity.Kind.STATUS, text__startswith="Lost:").update(text="Lost")
    rows.update(contact_name="", contact_phone="", contact_email="", venue="", menu="", dietary_needs="", message="",
                lost_reason="", conversation=None)
