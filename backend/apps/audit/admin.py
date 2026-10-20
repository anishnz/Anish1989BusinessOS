from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Searchable, read-only audit log."""

    list_display = ("created_at", "action", "outcome", "actor_email", "target_repr", "ip_address")
    list_filter = ("outcome", "actor_type", "action")
    search_fields = ("action", "actor_email", "target_repr", "target_id", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
