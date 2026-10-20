"""Inbox in the business admin: list of conversations and a chat page for each one."""
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.business import BusinessOnlyAdminMixin
from apps.rbac import policy

from . import services
from .models import Conversation


class ReplyForm(forms.Form):
    text = forms.CharField(label="Reply", widget=forms.Textarea(attrs={"rows": 3, "cols": 70}), max_length=services.MAX_TEXT)


class TemplateForm(forms.Form):
    name = forms.CharField(label="Template name", max_length=100, help_text="Exactly as approved in Meta, e.g. order_ready")
    language = forms.CharField(max_length=10, initial="en")
    params = forms.CharField(label="Values", required=False, help_text="Values for {{1}}, {{2}}… separated by |  e.g. Sita | #1001")
    category = forms.ChoiceField(choices=[("utility", "Utility (order updates)"), ("marketing", "Marketing (needs consent)")])


@admin.register(Conversation)
class ConversationAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["who", "last_message_preview", "unread", "status", "assigned_to", "last_message"]
    list_filter = ["status", "assigned_to"]
    search_fields = ["customer__name", "external_id"]
    list_select_related = ["customer", "assigned_to"]

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(external_id="", messages__isnull=True)

    @admin.display(description="Customer")
    def who(self, obj):
        return obj.customer.name if obj.customer else f"+{obj.external_id}"

    @admin.display(description="Unread", ordering="unread_count")
    def unread(self, obj):
        return obj.unread_count or ""

    @admin.display(description="Last message", ordering="last_message_at")
    def last_message(self, obj):
        return timezone.localtime(obj.last_message_at).strftime("%d %b %H:%M") if obj.last_message_at else "–"

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {**(extra_context or {}), "title": "Inbox"})

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        conversation = get_object_or_404(Conversation.objects.select_related("customer", "assigned_to"), pk=object_id)
        can_edit = policy.has_perm(request.user, "crm.edit")
        can_assign = policy.has_perm(request.user, "crm.assign")
        reply_form = ReplyForm(request.POST if "reply" in request.POST else None)
        template_form = TemplateForm(request.POST if "template" in request.POST else None)
        if request.method == "POST":
            action = next((a for a in ("reply", "template", "assign", "close", "reopen") if a in request.POST), None)
            needed = "crm.assign" if action == "assign" else "crm.edit"
            if not policy.require(request.user, needed, request=request):
                raise PermissionDenied
            try:
                if action == "reply" and reply_form.is_valid():
                    message = services.send_text(conversation, reply_form.cleaned_data["text"], actor=request.user)
                    self._report(request, message)
                    return redirect(request.path)
                if action == "template" and template_form.is_valid():
                    data = template_form.cleaned_data
                    params = [p.strip() for p in data["params"].split("|")] if data["params"].strip() else []
                    message = services.send_template(conversation, name=data["name"].strip(), language=data["language"].strip(), params=params, category=data["category"], actor=request.user)
                    self._report(request, message)
                    return redirect(request.path)
                if action == "assign":
                    user_id = request.POST.get("user")
                    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
                    services.assign(conversation, user, actor=request.user)
                    return redirect(request.path)
                if action in ("close", "reopen"):
                    services.set_closed(conversation, action == "close", actor=request.user)
                    return redirect(reverse("admin:inbox_conversation_changelist") if action == "close" else request.path)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
        else:
            services.mark_read(conversation)
        thread = list(conversation.messages.select_related("sent_by").order_by("-created_at", "-id")[:200])[::-1]
        context = {
            **self.admin_site.each_context(request), "title": self.who(conversation), "conversation": conversation,
            "thread": thread, "reply_form": reply_form, "template_form": template_form, "can_edit": can_edit, "can_assign": can_assign,
            "can_reply_freely": services.can_reply_freely(conversation), "opts": self.model._meta,
            "staff": get_user_model().objects.filter(is_active=True, is_staff=True).order_by("email") if can_assign else [],
            "back": reverse("admin:inbox_conversation_changelist"),
            "customer_url": reverse("admin:customers_customer_change", args=[conversation.customer_id]) if conversation.customer_id else "",
        }
        return render(request, "admin/inbox/conversation/thread.html", context)

    def _report(self, request, message):
        if message.status == message.Status.FAILED:
            messages.error(request, f"Not sent: {message.error}")
        else:
            messages.success(request, "Sent.")
