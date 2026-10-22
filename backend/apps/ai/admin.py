"""
AI assistant pages in the business admin (task 2.4).
Settings: look with AI – View, change with AI – Configure. The AI log is read only (AI – View).
"""
import json

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.core.business import BusinessOnlyAdminMixin
from apps.rbac import policy

from . import agent, providers
from .models import AIRun, AISettings


@admin.register(AISettings)
class AISettingsAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    readonly_fields = ["status", "this_month"]
    fieldsets = [
        ("Now", {"fields": ["status", "this_month"]}),
        ("Answering", {"fields": ["enabled", "connection", "instructions", "email_on_handover"],
                       "description": "The AI answers customers who write on WhatsApp, in English or Nepali. It never confirms an order: "
                                      "the customer presses Yes on the summary. It stays quiet in chats that staff are handling."}),
        ("Limits", {"fields": ["monthly_limit", "max_answers_per_chat_per_day"]}),
        ("Cost estimate", {"fields": ["usd_to_nzd", "price_input", "price_output"],
                           "description": "The estimate uses the provider's list price for the model. Check your real bill with the provider."}),
    ]

    @staticmethod
    def _can_configure(request) -> bool:
        return policy.has_perm(request.user, "ai.configure")

    def has_add_permission(self, request, *args):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._can_configure(request)

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        return redirect(reverse("admin:ai_aisettings_change", args=[agent.current_settings().pk]))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "connection":
            from apps.vault.models import Connection

            kwargs["queryset"] = Connection.objects.filter(category="ai", provider__in=providers.SUPPORTED)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Status")
    def status(self, obj):
        from apps.orders.notify import whatsapp_connected
        from apps.rbac.policy import module_enabled

        if not obj.enabled:
            return "Switched off."
        if not module_enabled("ai"):
            return "The AI module is switched off for this business."
        if not whatsapp_connected():
            return "Waiting: WhatsApp is not connected (Integrations page)."
        conn = agent.ai_connection(obj)
        if conn is None:
            return "Waiting: save an OpenAI, Claude or Gemini key on the Integrations page."
        return f"Answering with {conn.label} ({providers.model_for(conn.provider, conn.config)})."

    @admin.display(description="This month")
    def this_month(self, obj):
        spent = agent.spent_this_month()
        runs = AIRun.objects.filter(created_at__gte=agent.month_start()).count()
        return f"{runs} answer(s), about NZ${spent:.2f} of NZ${obj.monthly_limit:.2f}"


@admin.register(AIRun)
class AIRunAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["when", "customer", "result", "tools", "tokens", "cost_label", "note"]
    list_filter = ["result", "provider"]
    search_fields = ["conversation__customer__name", "conversation__customer__phone", "note"]
    list_select_related = ["conversation__customer"]
    fields = ["when", "customer", "provider", "model", "result", "note", "tokens", "cost_label", "duration_ms", "order", "tools", "steps_text"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="When", ordering="created_at")
    def when(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d %b %H:%M")

    @admin.display(description="Customer")
    def customer(self, obj):
        c = obj.conversation.customer if obj.conversation else None
        return c.name if c else "–"

    @admin.display(description="Tokens")
    def tokens(self, obj):
        return f"{obj.input_tokens:,} in / {obj.output_tokens:,} out"

    @admin.display(description="Cost (NZ$)", ordering="cost")
    def cost_label(self, obj):
        return f"{obj.cost:.4f}"

    @admin.display(description="What the AI did")
    def steps_text(self, obj):
        if not obj.steps:
            return "–"
        return format_html("<pre style='white-space:pre-wrap;max-width:900px'>{}</pre>", json.dumps(obj.steps, ensure_ascii=False, indent=1))
