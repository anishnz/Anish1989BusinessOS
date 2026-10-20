"""Customers in the business admin: consent history, CSV import/export, archive and remove personal data."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import path, reverse

from apps.audit.services import audit
from apps.core import csvtools
from apps.core.business import ArchivedFilter, BusinessOnlyAdminMixin
from apps.rbac import policy

from . import services
from .models import ConsentRecord, Customer


class ConsentRecordInline(admin.TabularInline):
    model = ConsentRecord
    extra = 0
    can_delete = False
    fields = ["recorded_at", "given", "channel", "source", "note", "recorded_by"]
    readonly_fields = fields
    verbose_name_plural = "Marketing consent history"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "tags", "preferred_language", "notes", "marketing_consent"]

    def _run(self, func, value):
        try:
            return func(value)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages[0]) from None

    def clean_phone(self):
        return self._run(services.normalise_phone, self.cleaned_data.get("phone"))

    def clean_email(self):
        return self._run(services.clean_email, self.cleaned_data.get("email"))

    def clean(self):
        data = super().clean()
        if self.instance.pk and self.instance.is_anonymised:
            raise forms.ValidationError("This customer's personal data was removed and cannot be changed.")
        other = services.find_duplicate(phone=data.get("phone", ""), email=data.get("email", ""), exclude_pk=self.instance.pk)
        if other is not None:
            raise forms.ValidationError(f"This phone or email already belongs to {other.name} (customer #{other.pk}).")
        return data


class ImportForm(forms.Form):
    file = forms.FileField(label="CSV file")


@admin.register(Customer)
class CustomerAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    form = CustomerForm
    change_list_template = "admin/customers/customer/change_list.html"
    list_display = ["name", "phone", "email", "tags", "marketing_ok", "source"]
    list_filter = [ArchivedFilter, "marketing_consent", "source"]
    search_fields = ["name", "phone", "email", "tags"]
    inlines = [ConsentRecordInline]
    actions = ["archive", "restore", "anonymise"]
    fieldsets = [
        (None, {"fields": ["name", "phone", "email", "address", "tags", "preferred_language"]}),
        ("Marketing", {"fields": ["marketing_consent"], "description": "Only tick this when the customer has agreed to receive marketing messages. Each change is recorded."}),
        ("Staff notes", {"fields": ["notes"]}),
    ]

    @admin.display(description="Marketing OK", boolean=True, ordering="marketing_consent")
    def marketing_ok(self, obj):
        return obj.marketing_consent

    def get_search_results(self, request, queryset, search_term):
        return services.search(queryset, search_term), False

    def save_model(self, request, obj, form, change):
        consent_changed = "marketing_consent" in form.changed_data
        new_consent = obj.marketing_consent
        if not change:
            obj.created_by = request.user
            obj.marketing_consent = False  # recorded below, with history
        elif consent_changed:
            obj.marketing_consent = form.initial.get("marketing_consent", False)
        super().save_model(request, obj, form, change)
        if consent_changed or (not change and new_consent):
            services.set_marketing_consent(obj, new_consent, source=ConsentRecord.Source.STAFF, actor=request.user)

    def has_delete_permission(self, request, obj=None):
        return False  # archive, or remove personal data, instead

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not policy.has_perm(request.user, "crm.edit"):
            actions.pop("restore", None)
        if not policy.has_perm(request.user, "crm.delete"):
            actions.pop("archive", None)
            actions.pop("anonymise", None)
        return actions

    @admin.action(description="Archive selected customers")
    def archive(self, request, queryset):
        for customer in queryset:
            services.archive(customer, actor=request.user)
        self.message_user(request, "Archived. Choose Status: Archived on the right to see or restore them.", messages.SUCCESS)

    @admin.action(description="Restore selected archived customers")
    def restore(self, request, queryset):
        for customer in queryset.filter(is_anonymised=False):
            services.restore(customer, actor=request.user)
        self.message_user(request, "Restored.", messages.SUCCESS)

    @admin.action(description="Remove personal data of selected customers (privacy request)")
    def anonymise(self, request, queryset):
        if request.POST.get("confirm") == "yes":
            count = 0
            for customer in queryset.filter(is_anonymised=False):
                services.anonymise(customer, actor=request.user)
                count += 1
            self.message_user(request, f"Personal data removed for {count} customer(s).", messages.SUCCESS)
            return None
        context = {
            **self.admin_site.each_context(request), "title": "Remove personal data?", "customers": queryset,
            "opts": self.model._meta, "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/customers/customer/anonymise_confirm.html", context)

    # ---- CSV import and export pages ----
    def get_urls(self):
        return [
            path("import/", self.admin_site.admin_view(self.import_view), name="customers_customer_import"),
            path("export/", self.admin_site.admin_view(self.export_view), name="customers_customer_export"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_import"] = policy.has_perm(request.user, "crm.import")
        extra_context["can_export"] = policy.has_perm(request.user, "crm.export")
        return super().changelist_view(request, extra_context)

    def import_view(self, request):
        if not self.has_module_permission(request) or not policy.require(request.user, "crm.import", request=request):
            raise PermissionDenied
        form = ImportForm(request.POST or None, request.FILES or None)
        result = None
        if request.method == "POST" and form.is_valid():
            dry_run = "check" in request.POST
            try:
                result = services.import_customers(form.cleaned_data["file"], actor=request.user, dry_run=dry_run)
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                if result.ok and not dry_run:
                    self.message_user(request, f"Import finished: {result.created} added, {result.updated} updated.", messages.SUCCESS)
        context = {
            **self.admin_site.each_context(request), "title": "Import customers from CSV", "form": form, "result": result,
            "opts": self.model._meta, "columns": services.CSV_COLUMNS, "back": reverse("admin:customers_customer_changelist"),
        }
        return render(request, "admin/customers/customer/import.html", context)

    def export_view(self, request):
        if not self.has_module_permission(request) or not policy.require(request.user, "crm.export", request=request):
            raise PermissionDenied
        qs = Customer.objects.filter(is_archived=False, is_anonymised=False)
        audit("crm.export", actor=request.user, metadata={"rows": qs.count()})
        return csvtools.csv_response("customers.csv", services.CSV_COLUMNS, services.export_rows(qs))
