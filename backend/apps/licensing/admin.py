"""
Super Admin pages (platform site only): licence and modules are edited on the
tenant page; lifecycle actions are in the tenant list.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import path, reverse

from apps.tenants.admin import TenantAdmin as BaseTenantAdmin
from apps.tenants.models import Tenant

from . import services
from .models import Licence, TenantModule
from .templates_catalogue import OPTIONAL_MODULES


class LicenceInline(admin.StackedInline):
    model = Licence
    can_delete = False
    extra = 0
    fields = (
        "plan_name", ("starts_at", "trial_ends_at", "ends_at", "grace_days"),
        ("max_users", "max_websites", "storage_mb"), ("ai_credits_monthly", "api_calls_monthly"),
        "suspension_reason", "notes",
    )
    readonly_fields = ("suspension_reason",)


class TenantModuleInline(admin.TabularInline):
    model = TenantModule
    extra = 0
    can_delete = False
    fields = ("module", "entitled", "enabled")
    readonly_fields = ("module",)
    verbose_name_plural = "Modules (entitled = included in the licence; enabled = switched on by the business)"

    def has_add_permission(self, request, obj=None):
        return False


class TenantCreateForm(forms.ModelForm):
    schema_name = forms.CharField(label="Business id (slug)", help_text="Lowercase letters, numbers and underscores, e.g. gorkhabutchery.")
    admin_email = forms.EmailField(required=False, label="System Admin email", help_text="Optional. They get an email to set their password.")

    class Meta:
        model = Tenant
        fields = ["name", "schema_name", "industry"]

    def clean_schema_name(self):
        from apps.tenants.services import validate_slug

        slug = validate_slug(self.cleaned_data["schema_name"])
        if Tenant.objects.filter(schema_name=slug).exists():
            raise ValidationError(f"A business with the id '{slug}' already exists.")
        return slug

    def clean_industry(self):
        industry = self.cleaned_data["industry"]
        if industry == Tenant.Industry.PLATFORM:
            raise ValidationError("Choose the type of business.")
        return industry


class InviteAdminForm(forms.Form):
    email = forms.EmailField(label="System Admin email")


class SuspendForm(forms.Form):
    reason = forms.CharField(max_length=300, widget=forms.Textarea(attrs={"rows": 3}), label="Reason (recorded in the audit log)")


admin.site.unregister(Tenant)


@admin.register(Tenant)
class TenantAdmin(BaseTenantAdmin):
    change_form_template = "admin/tenants/tenant/change_form.html"  # adds Invite / Suspend buttons
    list_display = ("name", "schema_name", "industry", "status", "access", "trial_ends", "created_at")
    actions = ["action_reactivate", "action_mark_paid", "action_extend_trial_14"]

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = TenantCreateForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["name", "schema_name", "industry", "admin_email"]
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        return ("schema_name", "status", "created_at", "updated_at") if obj else ()

    def get_inlines(self, request, obj):
        return [LicenceInline, TenantModuleInline, *super().get_inlines(request, obj)] if obj else []

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        from apps.tenants.services import create_tenant

        tenant = create_tenant(form.cleaned_data["name"], form.cleaned_data["schema_name"], form.cleaned_data["industry"])
        obj.pk, obj.id = tenant.pk, tenant.pk
        obj.schema_name = tenant.schema_name
        email = form.cleaned_data.get("admin_email")
        if email:
            try:
                services.invite_system_admin(tenant, email, actor=request.user, request=request)
            except ValidationError as exc:
                self.message_user(request, " ".join(exc.messages), messages.WARNING)
            else:
                self.message_user(request, f"Invitation sent to {email}.", messages.SUCCESS)

    def save_formset(self, request, form, formset, change):
        # Modules: an un-entitled module cannot stay enabled.
        instances = formset.save(commit=False)
        for item in instances:
            if isinstance(item, TenantModule) and not item.entitled:
                item.enabled = False
            item.save()
        formset.save_m2m()
        services.clear_cache(form.instance)

    @admin.display(description="Access")
    def access(self, obj):
        return services.access_state(obj)

    @admin.display(description="Trial ends")
    def trial_ends(self, obj):
        licence = getattr(obj, "licence", None)
        return licence.trial_ends_at if licence and obj.status == "trial" else "–"

    # ---- extra pages: suspend and invite (need a form) ----
    def get_urls(self):
        extra = [
            path("<int:pk>/suspend/", self.admin_site.admin_view(self.suspend_view), name="tenants_tenant_suspend"),
            path("<int:pk>/invite-admin/", self.admin_site.admin_view(self.invite_view), name="tenants_tenant_invite"),
        ]
        return extra + super().get_urls()

    def _form_page(self, request, pk, form_class, title, handle):
        tenant = Tenant.objects.get(pk=pk)
        if not self.has_change_permission(request, tenant):
            return redirect("admin:index")
        form = form_class(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                handle(tenant, form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                return redirect(reverse("admin:tenants_tenant_change", args=[pk]))
        context = {**self.admin_site.each_context(request), "title": f"{title}: {tenant.name}", "form": form, "opts": self.model._meta, "original": tenant}
        return render(request, "admin/licensing/form_page.html", context)

    def suspend_view(self, request, pk):
        def handle(tenant, data):
            services.suspend(tenant, data["reason"], actor=request.user)
            self.message_user(request, f"{tenant.name} is suspended.", messages.WARNING)

        return self._form_page(request, pk, SuspendForm, "Suspend business", handle)

    def invite_view(self, request, pk):
        def handle(tenant, data):
            services.invite_system_admin(tenant, data["email"], actor=request.user, request=request)
            self.message_user(request, f"Invitation sent to {data['email']}.", messages.SUCCESS)

        return self._form_page(request, pk, InviteAdminForm, "Invite System Admin", handle)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["tenant_links"] = [
            (reverse("admin:tenants_tenant_invite", args=[object_id]), "Invite System Admin"),
            (reverse("admin:tenants_tenant_suspend", args=[object_id]), "Suspend business"),
        ]
        return super().change_view(request, object_id, form_url, extra_context)

    # ---- list actions ----
    @admin.action(description="Reactivate selected businesses")
    def action_reactivate(self, request, queryset):
        for tenant in queryset.exclude(schema_name="public"):
            services.reactivate(tenant, actor=request.user)
        self.message_user(request, "Reactivated.", messages.SUCCESS)

    @admin.action(description="Mark selected as paid (active licence)")
    def action_mark_paid(self, request, queryset):
        for tenant in queryset.exclude(schema_name="public"):
            services.reactivate(tenant, paid=True, actor=request.user)
        self.message_user(request, "Marked as paid.", messages.SUCCESS)

    @admin.action(description="Extend trial by 14 days")
    def action_extend_trial_14(self, request, queryset):
        for tenant in queryset.exclude(schema_name="public"):
            services.extend_trial(tenant, 14, actor=request.user)
        self.message_user(request, "Trial extended by 14 days.", messages.SUCCESS)


def optional_module_codes():
    return OPTIONAL_MODULES
