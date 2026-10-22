"""
Admin pages for the daily owner summary (task 2.7): the settings (seeing them
needs Orders – View, changing needs Orders – Configure) and the summaries that
were sent (Reports – View, read-only).
"""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from apps.core.business import BusinessOnlyAdminMixin
from apps.fulfilment.admin import ConfigureOnlyMixin
from apps.rbac import policy

from . import summary
from .models import DailySummary, DailySummarySettings


@admin.register(DailySummarySettings)
class DailySummarySettingsAdmin(ConfigureOnlyMixin, admin.ModelAdmin):
    readonly_fields = ["whatsapp", "recipients", "today", "template_to_create"]
    fieldsets = [
        ("When", {"fields": ["enabled", "send_at"],
                  "description": "The summary covers today until the time it is sent. It is not sent on a closed day without orders."}),
        ("WhatsApp", {"fields": ["whatsapp", "by_whatsapp", "whatsapp_numbers", "template_name", "template_language"],
                      "description": "Sent as an approved template (Meta charges per message)."}),
        ("Email", {"fields": ["by_email", "email_to", "recipients"]}),
        ("Today so far", {"fields": ["today"]}),
        ("Template to create in Meta (category: Utility, language: English)", {"fields": ["template_to_create"]}),
    ]

    def has_module_permission(self, request):
        return super().has_module_permission(request) and policy.module_enabled("reports")

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and policy.module_enabled("reports")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and policy.module_enabled("reports")

    def has_add_permission(self, request, *args):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        return redirect(reverse("admin:reports_dailysummarysettings_change", args=[summary.current_settings().pk]))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_send_test"] = self._can_configure(request)
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        return [path("send-test/", self.admin_site.admin_view(self.send_test_view), name="reports_dailysummarysettings_send_test")] + super().get_urls()

    def send_test_view(self, request):
        if not self.has_module_permission(request) or not self._can_configure(request) or not self.has_change_permission(request):
            raise PermissionDenied
        settings = summary.current_settings()
        if request.method == "POST":
            self.message_user(request, f"Test sent. {summary.send_test(actor=request.user)}", messages.SUCCESS)
            return redirect(reverse("admin:reports_dailysummarysettings_change", args=[settings.pk]))
        context = {**self.admin_site.each_context(request), "title": "Send a test of the daily summary", "settings": settings,
                   "preview": summary.preview(), "opts": self.model._meta}
        return render(request, "admin/reports/dailysummarysettings/send_test.html", context)

    @admin.display(description="Connection")
    def whatsapp(self, obj):
        from apps.orders.notify import whatsapp_connected

        return "WhatsApp is connected." if whatsapp_connected() else "WhatsApp is not connected, so the summary is only emailed."

    @admin.display(description="Who gets the email now")
    def recipients(self, obj):
        people = ", ".join(summary.email_recipients(obj)) or "Nobody yet."
        return people if obj.by_email else f"Email is switched off. When it is on: {people}"

    @admin.display(description="Summary")
    def today(self, obj):
        return format_html('<pre style="white-space: pre-wrap; margin: 0;">{}</pre>', summary.preview())

    @admin.display(description="Template")
    def template_to_create(self, obj):
        return format_html("<p>Name: <code>{}</code> (no buttons)</p><p>{}</p>", obj.template_name or "daily_summary", summary.TEMPLATE)


@admin.register(DailySummary)
class DailySummaryAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["day", "status", "whatsapp_result", "email_result", "note"]
    list_filter = ["status"]
    readonly_fields = ["day", "status", "summary_text", "whatsapp_result", "email_result", "note", "created_at"]
    fields = readonly_fields

    @admin.display(description="Summary")
    def summary_text(self, obj):
        return format_html('<pre style="white-space: pre-wrap; margin: 0;">{}</pre>', obj.text)

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
