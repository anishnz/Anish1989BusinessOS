from django.conf import settings
from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from django_tenants.utils import get_public_schema_name

from .models import Domain, Tenant


class PublicSchemaOnlyAdmin(admin.ModelAdmin):
    """Tenant records exist only in the public schema; hide them on tenant sites."""

    def _on_public_site(self, request) -> bool:
        tenant = getattr(request, "tenant", None)
        return tenant is not None and tenant.schema_name == get_public_schema_name()

    def has_module_permission(self, request):
        return self._on_public_site(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._on_public_site(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._on_public_site(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._on_public_site(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Deleting tenants must go through the audited offboarding process.
        return False


class ReadOnlyDomainMixin:
    """Addresses are changed on the "Web addresses" page, which checks and audits every change."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DomainInline(ReadOnlyDomainMixin, admin.TabularInline):
    model = Domain
    extra = 0
    fields = ("domain", "is_primary", "created_at")
    readonly_fields = fields
    verbose_name_plural = "Web addresses (change them with the Web addresses button above)"


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, PublicSchemaOnlyAdmin):
    list_display = ("name", "schema_name", "industry", "status", "created_at")
    list_filter = ("status", "industry")
    search_fields = ("name", "schema_name")
    readonly_fields = ("schema_name", "created_at", "updated_at")
    inlines = [DomainInline]

    def get_readonly_fields(self, request, obj=None):
        # schema_name can be set when creating, never changed afterwards.
        return self.readonly_fields if obj else ("created_at", "updated_at")


@admin.register(Domain)
class DomainAdmin(ReadOnlyDomainMixin, PublicSchemaOnlyAdmin):
    list_display = ("domain", "tenant", "is_primary", "created_at")
    list_filter = ("is_primary",)
    search_fields = ("domain", "tenant__name")
    readonly_fields = ("domain", "tenant", "is_primary", "created_at")


admin.site.site_header = "Anish1989 Business OS"
admin.site.site_title = getattr(settings, "PLATFORM_DOMAIN", "Business OS")
