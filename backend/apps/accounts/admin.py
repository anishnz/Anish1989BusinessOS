from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import LoginEvent, User

# Hide django-otp's own admin pages: they would let one admin see another
# person's authenticator secret. MFA is managed through the user's own setup
# pages and the "Reset two-step verification" action below.
for model in (TOTPDevice, StaticDevice):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


@admin.action(description="Reset two-step verification (user sets it up again at next login)")
def reset_mfa(modeladmin, request, queryset):
    targets = queryset.exclude(pk=request.user.pk)
    skipped_self = queryset.filter(pk=request.user.pk).exists()
    count = 0
    for user in targets:
        TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()
        count += 1
    if count:
        modeladmin.message_user(request, f"Two-step verification reset for {count} user(s).", messages.SUCCESS)
    if skipped_self:
        modeladmin.message_user(request, "You cannot reset your own two-step verification here.", messages.WARNING)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "mfa_enabled", "last_login")
    search_fields = ("email", "first_name", "last_name")
    actions = [reset_mfa]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    @admin.display(boolean=True, description="Two-step verification")
    def mfa_enabled(self, obj):
        return TOTPDevice.objects.filter(user=obj, confirmed=True).exists()


@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    """Login history is read-only: it can be viewed and searched, never edited or deleted."""

    list_display = ("created_at", "event", "email", "ip_address")
    list_filter = ("event",)
    search_fields = ("email", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "event", "email", "user", "ip_address", "user_agent")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
