"""
Super Admin pages on the platform site: every business, its users, their
roles and two-step verification.

/platform/people/                         all businesses (and the platform's own admins)
/platform/people/<business id>/           users of one business
/platform/people/<business id>/<user>/    one user: roles, MFA reset / off / on, lock / unlock

Permissions (platform roles): tenants.view to look, tenants.administer to
change business users; platform_users.view / platform_users.edit (and
platform_roles.assign for roles) for the platform's own admins.

Every change is recorded in the business's own audit log as "platform
administrator <email>", and in the platform audit log.
"""
from __future__ import annotations

from contextlib import nullcontext

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django_tenants.utils import schema_context

from apps.audit.services import audit, platform_actor
from apps.rbac import policy
from apps.rbac.models import Role, UserRole
from apps.tenants.models import Tenant

from . import security
from .models import LoginEvent, User

PLATFORM = "public"


def _require(request, code: str) -> None:
    if not policy.require(request.user, code, request=request):
        raise PermissionDenied


def _codes(schema: str) -> tuple[str, str, str]:
    """(view, change, change roles) permission codes for a schema."""
    if schema == PLATFORM:
        return "platform_users.view", "platform_users.edit", "platform_roles.assign"
    return "tenants.view", "tenants.administer", "tenants.administer"


def _business(schema: str) -> Tenant:
    tenant = Tenant.objects.filter(schema_name=schema).first()
    if tenant is None:
        raise Http404("No such business.")
    return tenant


def _inside(schema: str, request):
    """Work inside the business's schema, recorded as the platform administrator."""
    if schema == PLATFORM:
        return nullcontext()
    return _Both(schema_context(schema), platform_actor(request.user.email))


class _Both:
    def __init__(self, *managers):
        self.managers = managers

    def __enter__(self):
        for m in self.managers:
            m.__enter__()

    def __exit__(self, *exc):
        for m in reversed(self.managers):
            m.__exit__(*exc)
        return False


def _ctx(request, **extra):
    return {**admin.site.each_context(request), **extra}


def _user_rows(users):
    roles = {}
    for ur in UserRole.objects.select_related("role").filter(user__in=users):
        roles.setdefault(ur.user_id, []).append(ur.role.name)
    return [
        {"user": u, "roles": sorted(roles.get(u.pk, [])), "mfa": security.mfa_status(u)}
        for u in users
    ]


@never_cache
def people_index(request):
    _require(request, "tenants.view")
    rows = []
    for tenant in Tenant.objects.exclude(schema_name=PLATFORM).order_by("name"):
        with schema_context(tenant.schema_name):
            users = list(User.objects.all())
            statuses = [security.mfa_status(u) for u in users if u.is_staff]
        rows.append({
            "tenant": tenant, "users": len(users), "active": sum(u.is_active for u in users),
            "mfa_on": statuses.count("on"), "mfa_not_set_up": statuses.count("not_set_up"), "mfa_off": statuses.count("off"),
        })
    platform_users = list(User.objects.all()) if policy.has_perm(request.user, "platform_users.view") else None
    return render(request, "accounts/platform/people_index.html", _ctx(
        request, title="Businesses and users", rows=rows,
        platform=_user_rows(platform_users) if platform_users is not None else None,
    ))


@never_cache
def people_list(request, schema: str):
    view_code, _, _ = _codes(schema)
    _require(request, view_code)
    tenant = _business(schema)
    with schema_context(schema):
        rows = _user_rows(list(User.objects.all()))
    from .login_as import is_super_admin

    return render(request, "accounts/platform/people_list.html", _ctx(
        request, title=f"Users of {tenant.name}" if schema != PLATFORM else "Platform administrators", tenant=tenant, rows=rows,
        can_login_as=schema != PLATFORM and is_super_admin(request.user),
    ))


def _active_super_admins() -> int:
    """Platform accounts that can still run the platform (only used in the public schema)."""
    ids = set(User.objects.filter(is_active=True, is_superuser=True).values_list("pk", flat=True))
    ids |= set(UserRole.objects.filter(role__full_access=True, user__is_active=True).values_list("user_id", flat=True))
    return len(ids)


@never_cache
def person_detail(request, schema: str, user_id: int):
    view_code, change_code, roles_code = _codes(schema)
    _require(request, view_code)
    tenant = _business(schema)
    here = reverse("platform_person", args=[schema, user_id])
    is_self = schema == PLATFORM and request.user.pk == int(user_id)

    if request.method == "POST":
        action = request.POST.get("action", "")
        _require(request, roles_code if action == "roles" else change_code)
        try:
            with _inside(schema, request), transaction.atomic():
                person = User.objects.filter(pk=user_id).first()
                if person is None:
                    raise Http404("No such user.")
                done = _apply(request, schema, person, action, is_self)
            audit(
                "platform.user_changed", request=request, target_type="accounts.user", target_id=str(user_id), target_repr=person.email,
                metadata={"business": schema, "action": action},
            )
            messages.success(request, done)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(here)

    with schema_context(schema):
        person = User.objects.filter(pk=user_id).first()
        if person is None:
            raise Http404("No such user.")
        current = set(UserRole.objects.filter(user=person).values_list("role_id", flat=True))
        roles = [{"role": r, "checked": r.pk in current} for r in Role.objects.order_by("-full_access", "name")]
        events = list(LoginEvent.objects.filter(user=person).order_by("-created_at")[:15])
        status = security.mfa_status(person)
        backup = security.backup_codes_remaining(person) if status == "on" else 0
    return render(request, "accounts/platform/person_detail.html", _ctx(
        request, title=person.email, tenant=tenant, person=person, roles=roles, events=events, status=status, backup=backup,
        is_self=is_self, can_change=policy.has_perm(request.user, change_code), can_roles=policy.has_perm(request.user, roles_code),
        back=reverse("platform_people_list", args=[schema]),
    ))


def _apply(request, schema: str, person: User, action: str, is_self: bool) -> str:
    by = request.user.email
    if action == "reset_mfa":
        security.reset_mfa(person, by_email=by, request=request)
        return f"Two-step verification reset. {person.email} sets it up again at the next login."
    if action == "mfa_off":
        security.set_mfa_switched_off(person, True, reason=request.POST.get("reason", ""), by_email=by, request=request)
        return f"Two-step verification is switched OFF for {person.email}. They sign in with a password only."
    if action == "mfa_on":
        security.set_mfa_switched_off(person, False, by_email=by, request=request)
        return f"Two-step verification is required again for {person.email}. They set it up at the next login."
    if action in ("lock", "unlock"):
        if is_self:
            raise ValidationError("You cannot lock your own account.")
        if action == "lock" and schema == PLATFORM and person.is_active and _active_super_admins() <= 1 and _is_super_admin(person):
            raise ValidationError("This is the last active Super Admin. Add another one first.")
        person.is_active = action == "unlock"
        person.save()  # unlocking checks the business's user limit
        return f"{person.email} is {'unlocked' if person.is_active else 'locked and can no longer sign in'}."
    if action == "roles":
        if is_self:
            raise ValidationError("You cannot change your own roles.")
        wanted = {int(pk) for pk in request.POST.getlist("roles") if pk.isdigit()}
        valid = set(Role.objects.filter(pk__in=wanted).values_list("pk", flat=True))
        if schema == PLATFORM and _is_super_admin(person) and not Role.objects.filter(pk__in=valid, full_access=True).exists() \
                and not person.is_superuser and _active_super_admins() <= 1:
            raise ValidationError("This is the last active Super Admin. Add another one first.")
        current = set(UserRole.objects.filter(user=person).values_list("role_id", flat=True))
        UserRole.objects.filter(user=person, role_id__in=current - valid).delete()
        for role_id in valid - current:
            UserRole.objects.create(user=person, role_id=role_id)
        policy.clear_cache(person)
        names = sorted(Role.objects.filter(pk__in=valid).values_list("name", flat=True))
        return f"Roles of {person.email}: {', '.join(names) if names else 'none'}."
    raise ValidationError("Unknown action.")


def _is_super_admin(person: User) -> bool:
    return person.is_superuser or UserRole.objects.filter(user=person, role__full_access=True).exists()
