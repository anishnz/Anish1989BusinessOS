"""
Permission checks. Deny unless every step allows (master spec 4.4):

  1. user is signed in and active
  2. the business (tenant) is active or in trial
  3. the module is enabled for the business       (licences arrive in task 1.4)
  4. one of the user's roles grants the permission
  5. record / department scope                     (added with departments)
  6. explicit restrictions and approvals           (added per module)

Superusers have every permission inside their own schema. Users only exist
in one schema, so this never crosses into another business.
"""
from __future__ import annotations

from django.db import connection

from apps.audit.models import AuditEvent
from apps.audit.services import audit

from .catalogue import module_of, permissions_for

ACTIVE_TENANT_STATUSES = {"trial", "active"}
_CACHE_ATTR = "_rbac_permission_cache"


class Decision:
    def __init__(self, allowed: bool, reason: str):
        self.allowed = allowed
        self.reason = reason

    def __bool__(self):
        return self.allowed

    def __repr__(self):
        return f"Decision({self.allowed}, {self.reason!r})"


def tenant_is_active() -> bool:
    tenant = getattr(connection, "tenant", None)
    if tenant is None or getattr(tenant, "schema_name", "public") == "public":
        return True
    return getattr(tenant, "status", "active") in ACTIVE_TENANT_STATUSES


def module_enabled(module: str) -> bool:
    """Placeholder until licences and module entitlements (task 1.4)."""
    return True


def effective_permissions(user) -> set[str]:
    """All permission codes the user has in the current schema (cached on the user object)."""
    if user is None or not user.is_authenticated or not user.is_active:
        return set()
    cache_key = (connection.schema_name, _CACHE_ATTR)
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    if user.is_superuser:
        codes = set(permissions_for(connection.schema_name))
    else:
        from .models import Role

        codes = set()
        for role in Role.objects.filter(assignments__user=user).prefetch_related("permissions"):
            codes |= role.permission_codes() if role.full_access else {p.code for p in role.permissions.all()}
    setattr(user, _CACHE_ATTR, (cache_key, codes))
    return codes


def clear_cache(user) -> None:
    if hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def check(user, code: str) -> Decision:
    if user is None or not user.is_authenticated:
        return Decision(False, "not_authenticated")
    if not user.is_active:
        return Decision(False, "inactive_user")
    if code not in permissions_for(connection.schema_name):
        return Decision(False, "unknown_permission")
    if not tenant_is_active():
        return Decision(False, "tenant_inactive")
    if not module_enabled(module_of(code)):
        return Decision(False, "module_disabled")
    if code not in effective_permissions(user):
        return Decision(False, "role_missing_permission")
    return Decision(True, "allowed")


def has_perm(user, code: str) -> bool:
    return check(user, code).allowed


def require(user, code: str, *, request=None, target=None) -> Decision:
    """Check and write an audit entry when access is denied."""
    decision = check(user, code)
    if not decision.allowed:
        audit(
            "permission.denied",
            request=request,
            target=target,
            outcome=AuditEvent.Outcome.DENIED,
            metadata={"permission": code, "reason": decision.reason},
        )
    return decision
