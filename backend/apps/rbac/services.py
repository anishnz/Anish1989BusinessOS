"""
Role management with protection against privilege escalation:

- You can only put permissions into a role that you have yourself.
- You can only give someone a role whose permissions you have yourself.
- You cannot change your own roles.
- Full-access roles (System Admin, Super Admin) can only be given by a superuser
  or someone who already has a full-access role.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from apps.audit.services import audit

from . import policy
from .catalogue import permissions_for
from .defaults import FULL_ACCESS_ROLES, default_roles_for
from .models import Role, UserRole


def sync_default_roles(schema_name: str | None = None) -> int:
    """Create any missing default roles. Existing roles (and admins' edits) are left alone."""
    schema_name = schema_name or connection.schema_name
    created = 0
    for slug, (name, description, codes) in default_roles_for(schema_name).items():
        role, was_created = Role.objects.get_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "is_system": True,
                "full_access": slug in FULL_ACCESS_ROLES,
            },
        )
        if was_created:
            created += 1
            if not role.full_access:
                role.set_permissions(codes & permissions_for(schema_name))
    return created


def _has_full_access(user) -> bool:
    return user.is_superuser or Role.objects.filter(assignments__user=user, full_access=True).exists()


def ensure_can_grant(actor, codes) -> None:
    missing = set(codes) - policy.effective_permissions(actor)
    if missing:
        raise PermissionDenied(f"You cannot grant permissions you do not have: {', '.join(sorted(missing))}")


@transaction.atomic
def create_role(actor, *, slug: str, name: str, description: str = "", codes=()) -> Role:
    if not policy.has_perm(actor, "roles.create"):
        raise PermissionDenied("You do not have permission to create roles.")
    ensure_can_grant(actor, codes)
    if Role.objects.filter(slug=slug).exists():
        raise ValidationError(f"A role with the id '{slug}' already exists.")
    role = Role.objects.create(slug=slug, name=name, description=description)
    role.set_permissions(codes)
    audit("role.permissions_set", target=role, changes={"permissions": sorted(codes)})
    return role


@transaction.atomic
def update_role_permissions(actor, role: Role, codes) -> Role:
    if not policy.has_perm(actor, "roles.manage_permissions"):
        raise PermissionDenied("You do not have permission to change role permissions.")
    if role.full_access:
        raise ValidationError("This role always has every permission and cannot be changed.")
    codes = set(codes)
    before = set(role.permissions.values_list("code", flat=True))
    # Adding or removing a permission both count as granting control over it.
    ensure_can_grant(actor, codes ^ before)
    role.set_permissions(codes)
    audit("role.permissions_set", target=role, changes={"added": sorted(codes - before), "removed": sorted(before - codes)})
    _clear_caches_for_role(role)
    return role


@transaction.atomic
def delete_role(actor, role: Role) -> None:
    if not policy.has_perm(actor, "roles.delete"):
        raise PermissionDenied("You do not have permission to delete roles.")
    if role.is_system:
        raise ValidationError("Default roles cannot be deleted.")
    ensure_can_grant(actor, role.permission_codes())
    role.delete()


@transaction.atomic
def assign_role(actor, user, role: Role) -> UserRole:
    if not policy.has_perm(actor, "roles.assign"):
        raise PermissionDenied("You do not have permission to assign roles.")
    if actor.pk == user.pk:
        raise PermissionDenied("You cannot change your own roles.")
    if role.full_access and not _has_full_access(actor):
        raise PermissionDenied("Only a full administrator can give full access.")
    ensure_can_grant(actor, role.permission_codes())
    assignment, _ = UserRole.objects.get_or_create(user=user, role=role, defaults={"assigned_by": actor})
    policy.clear_cache(user)
    return assignment


@transaction.atomic
def remove_role(actor, user, role: Role) -> None:
    if not policy.has_perm(actor, "roles.assign"):
        raise PermissionDenied("You do not have permission to remove roles.")
    if actor.pk == user.pk:
        raise PermissionDenied("You cannot change your own roles.")
    if role.full_access and not _has_full_access(actor):
        raise PermissionDenied("Only a full administrator can remove full access.")
    ensure_can_grant(actor, role.permission_codes())
    for assignment in UserRole.objects.filter(user=user, role=role):
        assignment.delete()
    policy.clear_cache(user)


def _clear_caches_for_role(role):
    # Permission caches live on user objects for one request only, so nothing to clear globally.
    return None
