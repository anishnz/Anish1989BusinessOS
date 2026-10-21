"""
Pickup and delivery settings in the business admin (task 2.1).

Everyone with Orders – View can look; changing needs Orders – Configure (D-124).
"""
from django import forms
from django.contrib import admin
from django.contrib.admin import widgets
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.core.business import BusinessOnlyAdminMixin
from apps.rbac import policy

from . import services
from .models import ClosedDay, DeliveryArea, FulfilmentSettings, Kind, OpeningHours


class ConfigureOnlyMixin(BusinessOnlyAdminMixin):
    """See with Orders – View; add, change and delete with Orders – Configure."""

    @staticmethod
    def _can_configure(request) -> bool:
        return policy.has_perm(request.user, "orders.configure")

    def has_add_permission(self, request, *args):
        return super().has_add_permission(request, *args) and self._can_configure(request)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._can_configure(request)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._can_configure(request)


class HoursFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        rows = []
        for form in self.forms:
            data = getattr(form, "cleaned_data", None) or {}
            if not data or data.get("DELETE") or not all(data.get(k) is not None for k in ("kind", "weekday", "opens", "closes")):
                continue
            rows.append((data["kind"], int(data["weekday"]), data["opens"], data["closes"]))
        try:
            services.check_hours(rows)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from None


class HoursForm(forms.ModelForm):
    class Meta:
        model = OpeningHours
        fields = ["kind", "weekday", "opens", "closes"]
        widgets = {"opens": widgets.AdminTimeWidget(format="%H:%M"), "closes": widgets.AdminTimeWidget(format="%H:%M")}


class HoursInline(ConfigureOnlyMixin, admin.TabularInline):
    model = OpeningHours
    form = HoursForm
    formset = HoursFormSet
    fields = ["kind", "weekday", "opens", "closes"]

    def get_extra(self, request, obj=None, **kwargs):
        return 7 if obj is not None and not obj.hours.exists() else 1


@admin.register(FulfilmentSettings)
class FulfilmentSettingsAdmin(ConfigureOnlyMixin, admin.ModelAdmin):
    inlines = [HoursInline]
    readonly_fields = ["next_days"]
    fieldsets = [
        ("Pickup", {"fields": ["pickup_enabled", "pickup_slot_minutes", "pickup_capacity"]}),
        ("Delivery", {"fields": ["delivery_enabled", "delivery_slot_minutes", "delivery_capacity", "delivery_fee_gst"],
                      "description": "Delivery areas and fees are on the “Delivery areas” page."}),
        ("For customers", {"fields": ["lead_minutes", "days_ahead"]}),
        ("Times customers can choose now", {"fields": ["next_days"]}),
    ]

    def has_add_permission(self, request, *args):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        return redirect(reverse("admin:fulfilment_fulfilmentsettings_change", args=[services.current_settings().pk]))

    @admin.display(description="Next days")
    def next_days(self, obj):
        rows = []
        for kind in (Kind.PICKUP, Kind.DELIVERY):
            label = Kind(kind).label
            if not obj.enabled(kind):
                rows.append((label, "switched off"))
                continue
            found = services.bookable_slots(kind, include_full=True)
            if not found:
                rows.append((label, "no times customers can choose. Add opening hours below (and check the closed days)."))
                continue
            per_day: dict[str, list] = {}
            for slot in found:
                per_day.setdefault(services.day_text(timezone.localtime(slot.start).date()), []).append(slot)
            text = "; ".join(f"{day}: {sum(1 for s in items if not s.full)} free of {len(items)}" for day, items in per_day.items())
            rows.append((label, text))
        return format_html("<ul style='margin:0;padding-left:1.2em'>{}</ul>", format_html_join("", "<li><strong>{}</strong>: {}</li>", rows))


@admin.register(ClosedDay)
class ClosedDayAdmin(ConfigureOnlyMixin, admin.ModelAdmin):
    list_display = ["date", "weekday", "reason"]
    search_fields = ["reason"]

    @admin.display(description="Day")
    def weekday(self, obj):
        return f"{obj.date:%A}"


class AreaForm(forms.ModelForm):
    class Meta:
        model = DeliveryArea
        fields = ["name", "postcodes", "suburbs", "fee", "minimum_order", "free_over", "is_active", "sort_order"]
        widgets = {"suburbs": forms.Textarea(attrs={"rows": 2, "cols": 60})}

    def clean_postcodes(self):
        return ", ".join(p.strip() for p in self.cleaned_data["postcodes"].split(",") if p.strip())

    def clean_suburbs(self):
        return ", ".join(" ".join(s.split()) for s in self.cleaned_data["suburbs"].split(",") if s.strip())


@admin.register(DeliveryArea)
class DeliveryAreaAdmin(ConfigureOnlyMixin, admin.ModelAdmin):
    form = AreaForm
    list_display = ["name", "postcodes", "suburb_names", "fee", "minimum_order", "free_over", "is_active", "sort_order"]
    list_filter = ["is_active"]
    search_fields = ["name", "postcodes", "suburbs"]

    @admin.display(description="Suburbs")
    def suburb_names(self, obj):
        names = obj.suburb_list()
        return ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")

    def has_delete_permission(self, request, obj=None):
        # Areas used by orders are kept (switch "Delivering here now" off instead).
        if obj is not None and obj.orders.exists():
            return False
        return super().has_delete_permission(request, obj)
