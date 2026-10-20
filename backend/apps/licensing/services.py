"""
Licence logic: create licences, work out access, switch modules, enforce limits,
and the Super Admin's lifecycle actions (suspend, reactivate, extend trial,
invite the business's first System Admin).
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import connection, transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit

from .models import Licence, TenantModule
from .templates_catalogue import CORE_MODULES, OPTIONAL_MODULES, default_limits, modules_for_industry

ALLOWED_STATES = {"trial", "active", "grace"}
_CACHE_ATTR = "_licensing_cache"


class LimitReached(ValidationError):
    """Raised when an action would go over a licence limit."""


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def create_licence(tenant, *, trial_days: int | None = None) -> Licence:
    trial_days = settings.LICENCE_TRIAL_DAYS if trial_days is None else trial_days
    now = timezone.now()
    licence, created = Licence.objects.get_or_create(
        tenant=tenant,
        defaults={"starts_at": now, "trial_ends_at": now + timedelta(days=trial_days), **default_limits()},
    )
    if created:
        chosen = modules_for_industry(tenant.industry)
        for module in OPTIONAL_MODULES:
            on = module in chosen
            TenantModule.objects.get_or_create(tenant=tenant, module=module, defaults={"entitled": on, "enabled": on})
    return licence


# ---------------------------------------------------------------------------
# Access checks (used by the permission policy and middleware)
# ---------------------------------------------------------------------------
def _real_tenant():
    """The Tenant row for the current schema (the connection may hold a lightweight stand-in)."""
    from apps.tenants.models import Tenant

    tenant = getattr(connection, "tenant", None)
    if isinstance(tenant, Tenant):
        return tenant
    # The tenants table lives in `public`, which is always on the search path.
    return Tenant.objects.filter(schema_name=connection.schema_name).first()


def _cache(tenant) -> dict:
    cache = getattr(tenant, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(tenant, _CACHE_ATTR, cache)
    return cache


def access_state(tenant=None) -> str:
    tenant = tenant or _real_tenant()
    if tenant is None:
        return "unknown"
    if tenant.schema_name == get_public_schema_name():
        return "active"
    cache = _cache(tenant)
    if "state" not in cache:
        licence = Licence.objects.filter(tenant_id=tenant.pk).select_related("tenant").first()
        cache["state"] = licence.state() if licence else "unlicensed"
    return cache["state"]


def is_access_allowed(tenant=None) -> bool:
    return access_state(tenant) in ALLOWED_STATES


def active_modules(tenant=None) -> set[str]:
    tenant = tenant or _real_tenant()
    if tenant is None:
        return set()
    if tenant.schema_name == get_public_schema_name():
        return set()
    cache = _cache(tenant)
    if "modules" not in cache:
        cache["modules"] = set(CORE_MODULES) | set(
            TenantModule.objects.filter(tenant_id=tenant.pk, entitled=True, enabled=True).values_list("module", flat=True)
        )
    return cache["modules"]


def module_is_active(module: str, tenant=None) -> bool:
    tenant = tenant or _real_tenant()
    if tenant is None:
        return False
    if tenant.schema_name == get_public_schema_name():
        return True  # platform modules are not licensed per tenant
    return module in active_modules(tenant)


def clear_cache(tenant) -> None:
    if hasattr(tenant, _CACHE_ATTR):
        delattr(tenant, _CACHE_ATTR)


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
@transaction.atomic
def set_entitlements(tenant, modules: set[str], *, actor=None) -> None:
    """Platform side: which optional modules this business may use."""
    unknown = set(modules) - set(OPTIONAL_MODULES)
    if unknown:
        raise ValidationError(f"Unknown or core module(s): {', '.join(sorted(unknown))}")
    changes = {}
    for module in OPTIONAL_MODULES:
        row, _ = TenantModule.objects.get_or_create(tenant=tenant, module=module)
        want = module in modules
        if row.entitled != want:
            changes[module] = want
            row.entitled = want
            if want and not row.enabled:
                row.enabled = True  # newly licensed modules start switched on
            row.save()
    if changes:
        audit("licence.modules_entitled", target=tenant, actor=actor, changes=changes)
    clear_cache(tenant)


@transaction.atomic
def set_module_enabled(tenant, module: str, enabled: bool, *, actor=None) -> TenantModule:
    """Business side: switch a licensed module on or off."""
    if module in CORE_MODULES:
        raise ValidationError(f"'{module}' is a core module and is always on.")
    row = TenantModule.objects.filter(tenant=tenant, module=module).first()
    if row is None or not row.entitled:
        raise ValidationError(f"Your licence does not include '{module}'. Contact the platform to add it.")
    if row.enabled != enabled:
        row.enabled = enabled
        row.save(update_fields=["enabled", "updated_at"])
        audit("licence.module_switched", target=tenant, actor=actor, changes={module: enabled})
    clear_cache(tenant)
    return row


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def count_active_users(tenant) -> int:
    from django.contrib.auth import get_user_model

    with schema_context(tenant.schema_name):
        return get_user_model().objects.filter(is_active=True).count()


def check_can_add_active_user(tenant=None) -> None:
    tenant = tenant or _real_tenant()
    if tenant is None or tenant.schema_name == get_public_schema_name():
        return
    licence = Licence.objects.filter(tenant_id=tenant.pk).first()
    if licence is None:
        return
    if count_active_users(tenant) >= licence.max_users:
        raise LimitReached(
            f"Your licence allows {licence.max_users} active users. Deactivate a user or upgrade your plan to add more."
        )


def usage(tenant) -> dict:
    licence = tenant.licence
    return {
        "users": {"used": count_active_users(tenant), "limit": licence.max_users},
        "websites": {"used": 0, "limit": licence.max_websites},
        "storage_mb": {"used": 0, "limit": licence.storage_mb},
        "ai_credits_monthly": {"used": 0, "limit": licence.ai_credits_monthly},
        "api_calls_monthly": {"used": 0, "limit": licence.api_calls_monthly},
    }


# ---------------------------------------------------------------------------
# Lifecycle (Super Admin)
# ---------------------------------------------------------------------------
@transaction.atomic
def suspend(tenant, reason: str, *, actor=None) -> None:
    if not reason.strip():
        raise ValidationError("A reason is required to suspend a business.")
    if tenant.status == "suspended":
        return
    Licence.objects.filter(tenant=tenant).update(suspension_reason=reason.strip()[:300], status_before_suspension=tenant.status)
    tenant.status = "suspended"
    tenant.save(update_fields=["status", "updated_at"])
    audit("tenant.suspend", target=tenant, actor=actor, metadata={"reason": reason.strip()})
    clear_cache(tenant)


@transaction.atomic
def reactivate(tenant, *, paid: bool = False, actor=None) -> None:
    """Lift a suspension (back to trial or active). `paid=True` makes the licence active (paid)."""
    licence = tenant.licence
    if paid:
        new_status = "active"
    elif tenant.status in ("suspended", "cancelled"):
        new_status = licence.status_before_suspension or "trial"
    else:
        return
    tenant.status = new_status
    tenant.save(update_fields=["status", "updated_at"])
    Licence.objects.filter(tenant=tenant).update(suspension_reason="", status_before_suspension="")
    audit("tenant.reactivate", target=tenant, actor=actor, metadata={"status": new_status, "paid": paid})
    clear_cache(tenant)


@transaction.atomic
def extend_trial(tenant, days: int, *, actor=None) -> Licence:
    if days <= 0 or days > 90:
        raise ValidationError("Extend a trial by 1 to 90 days.")
    licence = tenant.licence
    base = max(licence.trial_ends_at or timezone.now(), timezone.now())
    licence.trial_ends_at = base + timedelta(days=days)
    licence.save(update_fields=["trial_ends_at", "updated_at"])
    audit("licence.trial_extended", target=tenant, actor=actor, metadata={"days": days, "trial_ends_at": licence.trial_ends_at})
    clear_cache(tenant)
    return licence


def invite_system_admin(tenant, email: str, *, actor=None, request=None) -> None:
    """
    Create the business's System Admin (in the business's own schema) with no
    password, and email them a link to set one on their own site.
    """
    from django.contrib.auth import get_user_model

    from apps.rbac.models import Role, UserRole

    email = email.strip().lower()
    domain = tenant.get_primary_domain().domain
    with schema_context(tenant.schema_name):
        User = get_user_model()
        user = User.objects.filter(email=email).first()
        if user is None:
            check_can_add_active_user(tenant)
            user = User(email=email, is_staff=True)
            user.set_unusable_password()
            user.save()
        elif not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        UserRole.objects.get_or_create(user=user, role=Role.objects.get(slug="system_admin"))
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
    protocol = "https" if (request is None or request.is_secure() or not settings.DEBUG) else "http"
    port = ""
    if request is not None and ":" in request.get_host():
        port = ":" + request.get_host().split(":", 1)[1]
    link = f"{protocol}://{domain}{port}/account/reset/{uid}/{token}/"
    context = {"business": tenant.name, "link": link, "email": email, "hours": settings.PASSWORD_RESET_TIMEOUT // 3600}
    send_mail(
        subject=f"You are the administrator of {tenant.name} on Anish1989 Business OS",
        message=render_to_string("licensing/invite_admin_email.txt", context),
        from_email=None,
        recipient_list=[email],
    )
    audit("tenant.admin_invited", target=tenant, actor=actor, metadata={"email": email})
