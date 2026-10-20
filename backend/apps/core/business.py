"""Helpers for apps whose data only exists inside a business (tenant) schema."""
from django.contrib import admin
from django.db import models
from django.db import connection


def on_platform_site() -> bool:
    return connection.schema_name == "public"


class BusinessOnlyAdminMixin:
    """Hide a business-only model in the platform site's admin (its tables do not exist there)."""

    def has_module_permission(self, request):
        return not on_platform_site() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return not on_platform_site() and super().has_view_permission(request, obj)

    def has_add_permission(self, request, *args):
        return not on_platform_site() and super().has_add_permission(request, *args)

    def has_change_permission(self, request, obj=None):
        return not on_platform_site() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not on_platform_site() and super().has_delete_permission(request, obj)


class ArchivedFilter(admin.SimpleListFilter):
    """Admin filter: current records by default, archived ones when chosen."""

    title = "status"
    parameter_name = "archived"

    def lookups(self, request, model_admin):
        return [("yes", "Archived")]

    def choices(self, changelist):
        yield {"selected": self.value() != "yes", "query_string": changelist.get_query_string(remove=[self.parameter_name]), "display": "Current"}
        yield {"selected": self.value() == "yes", "query_string": changelist.get_query_string({self.parameter_name: "yes"}), "display": "Archived"}

    def queryset(self, request, queryset):
        return queryset.filter(is_archived=self.value() == "yes")


def SET_NULL_IN_BUSINESS(collector, field, sub_objs, using):
    """
    on_delete for links from business-only tables to users.

    The users table exists in every schema, but business tables (products,
    orders...) only exist in business schemas. When a platform user is
    deleted, Django would try to update those tables in the platform schema,
    where they do not exist. There is nothing to update there, so skip it.
    """
    if not on_platform_site():
        models.SET_NULL(collector, field, sub_objs, using)


# Like Django's SET_NULL: do not load the linked rows before calling the rule
# (loading them is exactly what fails on the platform schema).
SET_NULL_IN_BUSINESS.lazy_sub_objs = True
