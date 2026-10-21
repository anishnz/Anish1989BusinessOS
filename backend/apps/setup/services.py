"""
First-login setup (task 1.16): business details, backups to the business's
own Google Drive, the most useful connections, done.

The wizard opens when a System Admin or IT Admin (Settings - Configure) of a
business opens the admin home page and setup is not finished. "Later" keeps
it closed for the rest of that sign-in. A reminder about backups stays on
every admin page until backups are set up, whatever happens to the wizard.
"""
from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name

from apps.audit.services import audit
from apps.rbac import policy

from .models import BusinessProfile, SetupProgress

STEPS = [("business", "Business details"), ("backups", "Backups"), ("connections", "Connections"), ("done", "Done")]
STEP_KEYS = [key for key, _ in STEPS]
LATER_SESSION_KEY = "setup_later"
PROFILE_FIELDS = ("trading_name", "phone", "email", "address", "suburb", "city", "postcode", "gst_number", "website")


def on_business_site() -> bool:
    return connection.schema_name != get_public_schema_name()


def can_configure(user) -> bool:
    return on_business_site() and policy.has_perm(user, "settings.configure")


def profile() -> BusinessProfile:
    return BusinessProfile.objects.get_or_create(pk=1)[0]


def progress() -> SetupProgress:
    return SetupProgress.objects.get_or_create(pk=1)[0]


def business_name() -> str:
    from apps.health.services import current_tenant

    tenant = current_tenant()
    p = BusinessProfile.objects.filter(pk=1).first()
    return (p.trading_name if p and p.trading_name else "") or (tenant.name if tenant else connection.schema_name)


# ---------------------------------------------------------------------------
# Business details
# ---------------------------------------------------------------------------
PHONE = re.compile(r"^\+?[0-9 ()-]{6,20}$")
GST = re.compile(r"^\d{2,3}-?\d{3}-?\d{3}$")  # NZ GST number: 8 or 9 digits, for example 123-456-789
POSTCODE = re.compile(r"^\d{4}$")  # NZ postcodes have 4 digits


def clean_profile(data: dict) -> dict:
    clean = {f: " ".join(str(data.get(f, "") or "").split()) for f in PROFILE_FIELDS}
    errors = {}
    if clean["phone"] and not PHONE.match(clean["phone"]):
        errors["phone"] = "Use numbers only, for example 09 123 4567 or +64 21 123 4567."
    if clean["gst_number"] and not GST.match(clean["gst_number"]):
        errors["gst_number"] = "A GST number has 8 or 9 digits, for example 123-456-789."
    if clean["postcode"] and not POSTCODE.match(clean["postcode"]):
        errors["postcode"] = "A New Zealand postcode has 4 digits."
    if clean["email"]:
        from django.core.validators import validate_email

        try:
            validate_email(clean["email"])
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    if clean["website"]:
        if not clean["website"].startswith(("https://", "http://")):
            clean["website"] = "https://" + clean["website"]
        from django.core.validators import URLValidator

        try:
            URLValidator(schemes=["http", "https"])(clean["website"])
        except ValidationError:
            errors["website"] = "Enter a web address, for example www.gorkhabutchery.co.nz."
    limits = {f.name: f.max_length for f in BusinessProfile._meta.fields if f.name in PROFILE_FIELDS}
    for name, value in clean.items():
        if limits.get(name) and len(value) > limits[name]:
            errors[name] = f"At most {limits[name]} characters."
    if errors:
        raise ValidationError(errors)
    return clean


@transaction.atomic
def save_profile(data: dict, *, actor=None) -> BusinessProfile:
    clean = clean_profile(data)
    p = profile()
    changed = sorted(f for f in PROFILE_FIELDS if getattr(p, f) != clean[f])
    for name, value in clean.items():
        setattr(p, name, value)
    p.updated_by_email = getattr(actor, "email", "") or ""
    p.save()
    prog = progress()
    if prog.business_done_at is None:
        prog.business_done_at = timezone.now()
        prog.save(update_fields=["business_done_at"])
    audit("setup.business_details", target_type="setup.businessprofile", target_id="1", actor=actor, metadata={"changed": changed})
    return p


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def backup_state() -> dict:
    from apps.backups import services as backups

    from apps.backups.google_connect import sign_in_app

    good = backups.latest_good_backup()
    return {
        "can_connect": sign_in_app() is not None,
        "passphrase": backups.site_settings().has_passphrase,
        "drive": backups.drive_connection(),
        "set_up": backups.is_set_up(),
        "good": good,
        "active": backups.active_run(),
        "last": backups.latest("backup"),
    }


def connection_state() -> list[dict]:
    """The connections most businesses need first, and whether they are there."""
    from apps.vault.models import Connection

    def have(**filters) -> Connection | None:
        return Connection.objects.filter(**filters).exclude(status=Connection.Status.DISABLED).order_by("is_backup", "id").first()

    return [
        {"key": "email", "label": "Email sending (Gmail or your own mail server)", "why": "Invitations, password resets and notices come from your own address.",
         "connection": have(category="email"), "add": "gmail"},
        {"key": "whatsapp", "label": "WhatsApp Business", "why": "Customers can message and order on WhatsApp (user guide chapter 7).",
         "connection": have(provider="whatsapp_cloud"), "add": "whatsapp_cloud"},
        {"key": "ai", "label": "AI model (optional, for later)", "why": "Used by the AI ordering assistant in Step 2. You can add it later.",
         "connection": have(category="ai"), "add": "openai"},
    ]


def step_done(key: str) -> bool:
    prog = progress()
    if key == "business":
        return prog.business_done_at is not None
    if key == "backups":
        state = backup_state()
        return state["set_up"] and state["good"] is not None
    if key == "connections":
        return prog.keys_seen_at is not None
    return prog.completed_at is not None


def first_open_step() -> str:
    for key in STEP_KEYS[:-1]:
        if not step_done(key) and not (key == "backups" and progress().backups_skipped_at):
            return key
    return "done"


def next_step(key: str) -> str:
    i = STEP_KEYS.index(key)
    return STEP_KEYS[min(i + 1, len(STEP_KEYS) - 1)]


@transaction.atomic
def skip(key: str, *, actor=None) -> None:
    prog = progress()
    if key == "backups":
        prog.backups_skipped_at = timezone.now()
    elif key == "connections":
        prog.keys_seen_at = prog.keys_seen_at or timezone.now()
    prog.save()
    audit("setup.step_skipped", target_type="setup.progress", target_id="1", actor=actor, metadata={"step": key})


@transaction.atomic
def mark_connections_seen(*, actor=None) -> None:
    prog = progress()
    if prog.keys_seen_at is None:
        prog.keys_seen_at = timezone.now()
        prog.save(update_fields=["keys_seen_at"])


@transaction.atomic
def finish(*, actor=None) -> None:
    prog = progress()
    if prog.completed_at is None:
        prog.completed_at = timezone.now()
        prog.completed_by_email = getattr(actor, "email", "") or ""
        prog.save()
        audit("setup.completed", target_type="setup.progress", target_id="1", actor=actor,
              metadata={step: step_done(step) for step in STEP_KEYS[:-1]})


def should_open_wizard(request) -> bool:
    """Open the wizard on the admin home page for admins of a business that has not finished setup."""
    user = request.user
    if not (user.is_authenticated and user.is_staff and on_business_site()):
        return False
    if request.session.get(LATER_SESSION_KEY):
        return False
    if not can_configure(user):
        return False
    prog = SetupProgress.objects.filter(pk=1).first()
    return prog is None or prog.completed_at is None


def backups_reminder(request) -> dict | None:
    """The reminder shown on admin pages while backups to the business's Google Drive are not set up."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_staff and on_business_site()):
        return None
    if request.path.startswith(("/setup/", "/backups/")) or not policy.has_perm(user, "settings.view"):
        return None
    from apps.backups import services as backups

    if backups.is_set_up():
        return None
    return {"can_fix": can_configure(user)}
