from django.apps import AppConfig


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rbac"
    verbose_name = "Roles and permissions"

    def ready(self):
        from django_tenants.signals import schema_migrated

        from apps.audit.tracking import track

        from .models import Role, RolePermission, UserRole

        track(Role)
        track(RolePermission)
        track(UserRole)

        schema_migrated.connect(_sync_roles_after_migrate, dispatch_uid="rbac-sync-default-roles")


def _sync_roles_after_migrate(sender, schema_name, **kwargs):
    """Every new or migrated schema gets its default roles."""
    from django_tenants.utils import schema_context

    from .services import sync_default_roles

    with schema_context(schema_name):
        sync_default_roles(schema_name)
