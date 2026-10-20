"""Customer actions: phone checks, duplicates, consent, removing personal data, CSV. All audited."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import audit
from apps.core import csvtools

from .models import ConsentRecord, Customer

CSV_COLUMNS = ["name", "phone", "email", "address", "tags", "preferred_language", "marketing_consent", "notes"]


def normalise_phone(value: str) -> str:
    """Return the number as +6421..., or "" if empty. NZ numbers can be typed as 021 123 4567."""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        number = phonenumbers.parse(value, getattr(settings, "PHONE_DEFAULT_REGION", "NZ"))
    except phonenumbers.NumberParseException:
        raise ValidationError(f"'{value}' is not a valid phone number.") from None
    if not phonenumbers.is_valid_number(number):
        raise ValidationError(f"'{value}' is not a valid phone number. Numbers from other countries must start with + and the country code.")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def clean_email(value: str) -> str:
    value = (value or "").strip().lower()
    if value:
        try:
            validate_email(value)
        except ValidationError:
            raise ValidationError(f"'{value}' is not a valid email address.") from None
    return value


def find_duplicate(*, phone: str = "", email: str = "", exclude_pk=None) -> Customer | None:
    query = Q()
    if phone:
        query |= Q(phone=phone)
    if email:
        query |= Q(email__iexact=email)
    if not query:
        return None
    qs = Customer.objects.filter(query)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


def search(queryset, q: str):
    q = (q or "").strip()
    if not q:
        return queryset
    condition = Q(name__icontains=q) | Q(email__icontains=q) | Q(tags__icontains=q)
    digits = re.sub(r"\D", "", q)
    if len(digits) >= 4:
        condition |= Q(phone__contains=digits.lstrip("0"))
    return queryset.filter(condition)


@transaction.atomic
def set_marketing_consent(customer: Customer, given: bool, *, source: str, actor=None, channel: str = "all", note: str = "") -> Customer:
    if source not in ConsentRecord.Source.values:
        raise ValidationError("Unknown consent source.")
    if customer.is_anonymised:
        raise ValidationError("This customer's personal data was removed.")
    ConsentRecord.objects.create(customer=customer, channel=channel, given=given, source=source, note=note[:200], recorded_by=actor)
    customer.marketing_consent = given
    customer.marketing_consent_at = timezone.now()
    customer.save(update_fields=["marketing_consent", "marketing_consent_at", "updated_at"])
    audit("crm.consent_" + ("given" if given else "withdrawn"), target=customer, actor=actor, metadata={"source": source, "channel": channel})
    return customer


def archive(customer: Customer, *, actor=None) -> Customer:
    customer.is_archived = True
    customer.save()
    audit("crm.customer_archive", target=customer, actor=actor)
    return customer


def restore(customer: Customer, *, actor=None) -> Customer:
    customer.is_archived = False
    customer.save()
    audit("crm.customer_restore", target=customer, actor=actor)
    return customer


@transaction.atomic
def anonymise(customer: Customer, *, actor=None) -> Customer:
    """
    Remove a customer's personal details (for a privacy request) but keep the
    record, so past orders and sales totals stay correct.
    """
    customer.name = f"Removed customer #{customer.pk}"
    customer.phone = ""
    customer.email = ""
    customer.address = ""
    customer.notes = ""
    customer.tags = ""
    customer.preferred_language = ""
    customer.marketing_consent = False
    customer.is_archived = True
    customer.is_anonymised = True
    customer.save()
    customer.consent_records.update(note="")
    # Django's own admin history keeps the old name as a label; replace it.
    from django.contrib.admin.models import LogEntry
    from django.contrib.contenttypes.models import ContentType

    LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(Customer), object_id=str(customer.pk)).update(
        object_repr=customer.audit_label, change_message=""
    )
    # Other modules (for example the inbox) remove their copies too.
    from .signals import customer_anonymised

    customer_anonymised.send(sender=Customer, customer=customer)
    audit("crm.customer_anonymise", target=customer, actor=actor)
    return customer


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
@dataclass
class ImportResult:
    dry_run: bool
    created: int = 0
    updated: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"dry_run": self.dry_run, "ok": self.ok, "created": self.created, "updated": self.updated, "errors": self.errors}


def _parse_row(row: dict) -> dict:
    name = row.get("name", "")
    if not name:
        raise csvtools.RowError("name is required.")
    if len(name) > 150:
        raise csvtools.RowError("name is longer than 150 characters.")
    try:
        phone = normalise_phone(row.get("phone", ""))
        email = clean_email(row.get("email", ""))
    except ValidationError as exc:
        raise csvtools.RowError(exc.messages[0]) from None
    data = {"name": name, "phone": phone, "email": email}
    for key, limit in (("address", 1000), ("tags", 200), ("preferred_language", 30), ("notes", 5000)):
        if key in row:
            if len(row[key]) > limit:
                raise csvtools.RowError(f"{key} is longer than {limit} characters.")
            data[key] = row[key]
    if row.get("marketing_consent", "") != "":
        data["marketing_consent"] = csvtools.parse_bool(row["marketing_consent"], default=False)
    return data


@transaction.atomic
def import_customers(upload, *, actor=None, dry_run: bool = False) -> ImportResult:
    """
    Add or update customers from a CSV file. A row updates the customer with
    the same phone number (or, without one, the same email). Nothing is saved
    if any row has an error.
    """
    rows = csvtools.read_rows(upload, required={"name"}, allowed=set(CSV_COLUMNS))
    result = ImportResult(dry_run=dry_run)
    parsed, seen = [], set()
    for number, row in enumerate(rows, start=2):
        try:
            data = _parse_row(row)
            for key in ("phone", "email"):
                if data[key]:
                    if (key, data[key]) in seen:
                        raise csvtools.RowError(f"{key} '{data[key]}' is used twice in the file.")
                    seen.add((key, data[key]))
            parsed.append((number, data))
        except csvtools.RowError as exc:
            result.errors.append({"row": number, "error": str(exc)})
    if result.errors:
        return result

    sid = transaction.savepoint()
    for number, data in parsed:
        consent = data.pop("marketing_consent", None)
        customer = find_duplicate(phone=data["phone"]) if data["phone"] else find_duplicate(email=data["email"])
        try:
            if customer is not None and customer.is_anonymised:
                raise ValidationError("matches a customer whose personal data was removed.")
            if customer is None:
                customer = Customer(source=Customer.Source.IMPORT, created_by=actor, **data)
                result.created += 1
            else:
                for key, value in data.items():
                    if value != "" or key in ("address", "tags", "preferred_language", "notes"):
                        setattr(customer, key, value)
                result.updated += 1
            other = find_duplicate(phone=customer.phone, email=customer.email, exclude_pk=customer.pk)
            if other is not None:
                raise ValidationError(f"phone or email already belongs to {other.name}.")
            customer.full_clean()
            customer.save()
            if consent is not None and consent != customer.marketing_consent:
                set_marketing_consent(customer, consent, source=ConsentRecord.Source.IMPORT, actor=actor)
        except ValidationError as exc:
            result.errors.append({"row": number, "error": "; ".join(exc.messages)})
    if result.errors or dry_run:
        transaction.savepoint_rollback(sid)
        if result.errors:
            result.created = result.updated = 0
        return result
    transaction.savepoint_commit(sid)
    audit("crm.import", actor=actor, metadata={"created": result.created, "updated": result.updated})
    return result


def export_rows(queryset):
    for c in queryset:
        yield [c.name, c.phone, c.email, c.address, c.tags, c.preferred_language, "yes" if c.marketing_consent else "no", c.notes]
