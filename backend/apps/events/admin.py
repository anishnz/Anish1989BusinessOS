"""
Admin pages for enquiries (task 3.1): the form settings and a read-only list
(staff work on enquiries in the staff app, /app/enquiries).
"""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from apps.core.business import BusinessOnlyAdminMixin

from . import services, spam
from .models import Enquiry, EnquirySettings


@admin.register(EnquirySettings)
class EnquirySettingsAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    readonly_fields = ["form_link", "spam_check", "recipients"]
    fieldsets = [
        ("Website form", {"fields": ["form_enabled", "form_link", "form_heading", "form_intro", "thanks_text", "spam_check"]}),
        ("Telling staff", {"fields": ["email_staff", "recipients"]}),
    ]

    def has_add_permission(self, request, *args):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        return redirect(reverse("admin:events_enquirysettings_change", args=[services.current_settings().pk]))

    @admin.display(description="Address of the form")
    def form_link(self, obj):
        from apps.health.services import current_tenant
        from apps.tenants.domains import main_address, site_url

        tenant = current_tenant()
        url = site_url(main_address(tenant), None, "/enquiry/") if tenant else "/enquiry/"
        if not services.form_available():
            return "The form is switched off."
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a> – share it on Facebook, Instagram or in emails.', url, url)

    @admin.display(description="Spam check")
    def spam_check(self, obj):
        if spam.turnstile():
            return "Cloudflare Turnstile is connected, plus a hidden field and limits."
        return ("A hidden field and limits (5 enquiries an hour from one internet address, 100 a day in total). For a stronger check, "
                "add Cloudflare Turnstile under Integrations (user guide 23.4).")

    @admin.display(description="Who gets the email now")
    def recipients(self, obj):
        return ", ".join(services.staff_recipients()) or "Nobody yet (nobody has Catering and events – Edit)."


@admin.register(Enquiry)
class EnquiryAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["number", "name", "status", "source", "event_type", "event_date", "guests", "created_at"]
    list_filter = ["status", "source", "event_type"]
    search_fields = ["contact_name", "contact_email", "id"]
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Enquiry", ordering="id")
    def number(self, obj):
        return f"#{obj.pk}"
