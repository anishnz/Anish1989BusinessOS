"""
Admin pages for roles. Only superusers can change roles here; other staff
can look. Role changes by non-superusers go through the API, which applies
the privilege-escalation checks in services.py.
"""
from django import forms
from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import connection

from apps.audit.services import audit

from .catalogue import grouped_choices
from .models import Role, UserRole


class RoleForm(forms.ModelForm):
    permission_codes = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple, label="Permissions",
        help_text="Tick what people with this role may do.",
    )

    class Meta:
        model = Role
        fields = ["slug", "name", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Fields can be missing when the page is view-only (staff who may only look).
        codes = self.fields.get("permission_codes")
        if codes is not None:
            codes.choices = grouped_choices(connection.schema_name)
        if self.instance.pk:
            if codes is not None:
                codes.initial = sorted(self.instance.permission_codes())
            if "slug" in self.fields:
                self.fields["slug"].disabled = self.instance.is_system
            if self.instance.full_access and codes is not None:
                codes.disabled = True
                codes.help_text = "This role always has every permission."


# Django's own groups are not used: permissions come only from roles.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)


class SuperuserEditsOnly:
    def has_add_permission(self, request, *args):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "is_system", False):
            return False
        return request.user.is_superuser


@admin.register(Role)
class RoleAdmin(SuperuserEditsOnly, admin.ModelAdmin):
    form = RoleForm

    class Media:
        css = {"all": ["rbac/role_admin.css"]}

    list_display = ("name", "slug", "is_system", "full_access", "permission_count", "user_count")
    list_filter = ("is_system", "full_access")
    search_fields = ("name", "slug", "description")

    @admin.display(description="Permissions")
    def permission_count(self, obj):
        return "All" if obj.full_access else obj.permissions.count()

    @admin.display(description="Users")
    def user_count(self, obj):
        return obj.assignments.count()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.full_access and "permission_codes" in form.cleaned_data:
            before = set(obj.permissions.values_list("code", flat=True))
            after = set(form.cleaned_data["permission_codes"])
            if before != after:
                obj.set_permissions(after)
                audit("role.permissions_set", target=obj, changes={"added": sorted(after - before), "removed": sorted(before - after)})


@admin.register(UserRole)
class UserRoleAdmin(SuperuserEditsOnly, admin.ModelAdmin):
    list_display = ("user", "role", "assigned_by", "assigned_at")
    list_filter = ("role",)
    search_fields = ("user__email", "role__name")
    autocomplete_fields = ("user",)
    readonly_fields = ("assigned_by", "assigned_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.assigned_by = request.user
        super().save_model(request, obj, form, change)
