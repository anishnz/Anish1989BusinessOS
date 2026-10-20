"""
Roles and role assignments. One set of tables per schema: platform roles in
`public`, each business's roles in its own schema.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models

from .catalogue import permissions_for


class Role(models.Model):
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    is_system = models.BooleanField(default=False, help_text="Default role created by the platform. Cannot be deleted.")
    full_access = models.BooleanField(default=False, help_text="Always has every permission (System Admin / Super Admin).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def permission_codes(self) -> set[str]:
        if self.full_access:
            return set(permissions_for(connection.schema_name))
        return set(self.permissions.values_list("code", flat=True))

    def set_permissions(self, codes) -> None:
        if self.full_access:
            raise ValidationError("This role always has every permission and cannot be changed.")
        codes = set(codes)
        unknown = codes - permissions_for(connection.schema_name)
        if unknown:
            raise ValidationError(f"Unknown permission(s): {', '.join(sorted(unknown))}")
        current = set(self.permissions.values_list("code", flat=True))
        for code in current - codes:
            self.permissions.filter(code=code).delete()
        for code in sorted(codes - current):
            RolePermission.objects.create(role=self, code=code)

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError("Default roles cannot be deleted.")
        return super().delete(*args, **kwargs)


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    code = models.CharField(max_length=80)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["role", "code"], name="unique_role_permission")]
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.role.slug}: {self.code}"

    def clean(self):
        if self.code not in permissions_for(connection.schema_name):
            raise ValidationError(f"Unknown permission: {self.code}")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class UserRole(models.Model):
    """
    A role given to a user. Scope is the whole business for now; department
    and branch scopes are added with the departments module.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")]
        ordering = ["role__name"]

    def __str__(self) -> str:
        return f"{self.user} → {self.role}"
