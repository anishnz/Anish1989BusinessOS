"""The admin entry for integrations just opens the Integrations settings page."""
from django.contrib import admin
from django.shortcuts import redirect

from .models import Connection


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    def changelist_view(self, request, extra_context=None):
        return redirect("vault:list")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
