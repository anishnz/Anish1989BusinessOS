"""
Orders in the business admin (until the React staff screens arrive).

- Add an order with its products; prices come from the products.
- Products can be changed while the order is a draft or awaiting confirmation.
- While "Being prepared", enter the real weights of products sold by weight.
- The "Status and payment" page moves the order on, cancels it, or marks it paid.
- Pickup or delivery, the address and the time are saved through the order
  rules too (delivery fee from the area, warnings for broken slot rules).
  When a rule says no, nothing is saved and the reason is shown.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone

from apps.audit.services import audit
from apps.catalog.models import Product
from apps.core.business import BusinessOnlyAdminMixin
from apps.fulfilment.models import Kind
from apps.rbac import policy

from apps.fulfilment.admin import ConfigureOnlyMixin

from . import notify, services
from .api import EXPORT_COLUMNS, export_rows
from .models import EDITABLE_STATUSES, CustomerMessageSettings, Order, OrderLine

S = Order.Status


class LineForm(forms.ModelForm):
    class Meta:
        model = OrderLine
        fields = ["product", "quantity", "final_quantity", "note"]
        widgets = {"note": forms.TextInput(attrs={"size": 18})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only products sold by weight get a real-weight box.
        if self.instance.pk and self.instance.unit != Product.Unit.KG and "final_quantity" in self.fields:
            field = self.fields["final_quantity"]
            field.disabled = True
            field.widget.attrs["placeholder"] = "not sold by weight"

    def clean(self):
        data = super().clean()
        order = self.instance.order if self.instance.order_id else None
        editable = order is None or order.status in EDITABLE_STATUSES
        product = data.get("product")
        if editable and product is not None and not data.get("DELETE"):
            if product.is_archived or not product.is_available:
                raise forms.ValidationError(f"{product.name} is not available to order right now.")
            if data.get("quantity") is not None:
                try:
                    services.check_quantity(product, data["quantity"])
                except ValidationError as exc:
                    raise forms.ValidationError(exc.messages) from None
        final = data.get("final_quantity")
        if final is not None and self.instance.pk and self.instance.unit != Product.Unit.KG:
            raise forms.ValidationError(f"{self.instance.product_name} is not sold by weight.")
        return data


class LineInline(admin.TabularInline):
    model = OrderLine
    form = LineForm
    extra = 0
    autocomplete_fields = ["product"]
    fields = ["product", "quantity", "unit", "unit_price", "final_quantity", "line_total", "note"]

    def get_extra(self, request, obj=None, **kwargs):
        return 3 if obj is None else 0

    def get_readonly_fields(self, request, obj=None):
        base = ["unit", "unit_price", "line_total"]
        if obj is None or obj.status in EDITABLE_STATUSES:
            return base + ["final_quantity"]
        if obj.status == S.PREPARING:
            return base + ["product", "quantity", "note"]
        return base + ["product", "quantity", "note", "final_quantity"]

    def has_add_permission(self, request, obj=None):
        return (obj is None or obj.status in EDITABLE_STATUSES) and super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or obj.status in EDITABLE_STATUSES) and super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.status in EDITABLE_STATUSES | {S.PREPARING}) and super().has_change_permission(request, obj)


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["customer", "channel", "fulfilment", "due_at", "delivery_address", "delivery_suburb", "delivery_postcode", "delivery_area", "notes"]

    def clean_delivery_postcode(self):
        value = (self.cleaned_data.get("delivery_postcode") or "").strip()
        if value and not (len(value) == 4 and value.isdigit()):
            raise forms.ValidationError("The postcode must have 4 digits.")
        return value

    def clean_customer(self):
        customer = self.cleaned_data.get("customer")
        if customer is not None and (customer.is_anonymised or customer.is_archived):
            raise forms.ValidationError("Choose a current customer.")
        return customer


class StatusForm(forms.Form):
    to = forms.ChoiceField(label="Move to")
    note = forms.CharField(label="Note (needed when cancelling)", required=False, max_length=300)

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to"].choices = [(s, services.status_label(order, s)) for s in services.allowed_moves(order)]


class PaymentForm(forms.Form):
    method = forms.ChoiceField(label="Paid by", choices=[c for c in Order.PaymentMethod.choices if c[0]])


@admin.register(Order)
class OrderAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    change_form_template = "admin/orders/order/change_form.html"
    change_list_template = "admin/orders/order/change_list.html"
    form = OrderForm
    inlines = [LineInline]
    autocomplete_fields = ["customer"]
    list_display = ["number_label", "created", "customer", "status_label", "how", "due", "total_label", "paid"]
    list_filter = ["status", "fulfilment", "channel", "is_paid"]
    date_hierarchy = "created_at"
    search_fields = ["=number", "customer__name", "customer__phone"]
    list_select_related = ["customer", "delivery_area"]
    actions = ["confirm", "start_preparing", "mark_ready", "send_out", "complete"]
    fields = ["customer", "channel", "fulfilment", "due_at", "delivery_address", "delivery_suburb", "delivery_postcode", "delivery_area", "notes"]
    summary_fields = ["number_label", "status_label", "due", "delivery_fee", "estimated_total", "total", "gst_total", "paid", "payment_method",
                      "created_by", "created_at", "whatsapp_messages"]

    @admin.display(description="WhatsApp messages to the customer")
    def whatsapp_messages(self, obj):
        """What the customer was sent about this order, and their answers (task 2.3). A shown field, so forms post nothing extra."""
        from django.utils.html import format_html, format_html_join

        rows = [(timezone.localtime(m.sent_at or m.created_at).strftime("%d %b %H:%M"), notify.label(m), notify.status_text(m))
                for m in obj.messages.select_related("inbox_message")] if obj and obj.pk else []
        if not rows:
            return "None yet."
        return format_html("<table><tbody>{}</tbody></table>", format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td></tr>", rows))

    @admin.display(description="Order", ordering="number")
    def number_label(self, obj):
        return f"#{obj.number}" if obj and obj.number else "New"

    @admin.display(description="Created", ordering="created_at")
    def created(self, obj):
        return timezone.localtime(obj.created_at).strftime("%d %b %H:%M")

    @admin.display(description="Status", ordering="status")
    def status_label(self, obj):
        return obj.status_text

    @admin.display(description="Pickup or delivery", ordering="fulfilment")
    def how(self, obj):
        if obj.fulfilment == Kind.DELIVERY:
            return f"Delivery to {obj.delivery_area.name}" if obj.delivery_area_id else "Delivery (no area)"
        return "Pickup"

    @admin.display(description="Due", ordering="due_at")
    def due(self, obj):
        return services.due_text(obj) if obj.due_at else "–"

    @admin.display(description="Total $", ordering="total")
    def total_label(self, obj):
        return obj.total

    @admin.display(description="Paid", boolean=True, ordering="is_paid")
    def paid(self, obj):
        return obj.is_paid

    def get_fields(self, request, obj=None):
        return self.fields if obj is None else self.summary_fields + self.fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        readonly = list(self.summary_fields)
        if not obj.is_open:
            readonly += self.fields
        elif obj.status == S.OUT_FOR_DELIVERY:
            readonly += sorted(services.FULFILMENT_FIELDS, key=self.fields.index)
        return readonly

    # ---- saving goes through the order rules ----
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        # A rule that says no while saving: nothing is saved (the admin saves in one transaction).
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as exc:
            messages.error(request, "Not saved: " + " ".join(exc.messages))
            return redirect(request.get_full_path())

    def save_model(self, request, obj, form, change):
        if not change:
            obj.number = services._next_number()
            obj.created_by = request.user
            services._clean_fulfilment(obj)
            return super().save_model(request, obj, form, change)
        changed = {name: form.cleaned_data[name] for name in form.changed_data if name in self.fields}
        if changed:
            services.update_order(obj, actor=request.user, **changed)
        return None

    def save_formset(self, request, form, formset, change):
        order = form.instance
        if formset.model is not OrderLine:
            return super().save_formset(request, form, formset, change)
        # Lines are saved by the order rules below, not by Django's formset.
        formset.new_objects, formset.changed_objects, formset.deleted_objects = [], [], []
        if order.status == S.PREPARING:
            weights = {
                f.instance.pk: f.cleaned_data["final_quantity"]
                for f in formset.forms
                if f.instance.pk and "final_quantity" in f.changed_data and f.cleaned_data.get("final_quantity") is not None
            }
            if weights:
                services.set_weights(order, weights, actor=request.user)
            return None
        if order.status not in EDITABLE_STATUSES:
            return None
        lines = [
            services.LineInput(product_id=f.cleaned_data["product"].pk, quantity=f.cleaned_data["quantity"], note=f.cleaned_data.get("note", ""))
            for f in formset.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("product")
        ]
        if not change:
            services._replace_lines(order, lines) if lines else None
            services.recalculate(order, refresh_fee=True)
            services._event(order, "", S.DRAFT, request.user, f"Order created ({services.fulfilment_text(order)})")
            audit("orders.create", target=order, actor=request.user,
                  metadata={"lines": len(lines), "total": str(order.total), "channel": order.channel, "fulfilment": order.fulfilment})
        elif formset.has_changed():
            services.update_order(order, lines=lines, actor=request.user)
        return None

    def save_related(self, request, form, formsets, change):
        with transaction.atomic():
            super().save_related(request, form, formsets, change)

    # ---- delete only drafts, through the rules ----
    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != S.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        services.delete_draft(obj, actor=request.user)

    def delete_queryset(self, request, queryset):
        for order in queryset:
            services.delete_draft(order, actor=request.user)

    # ---- quick status actions for several orders ----
    def _bulk(self, request, queryset, to_status):
        done, problems = 0, []
        for order in queryset:
            try:
                services.change_status(order, to_status, actor=request.user)
                done += 1
            except ValidationError as exc:
                problems.append(f"#{order.number}: {' '.join(exc.messages)}")
        if done:
            self.message_user(request, f"{done} order(s) moved to '{S(to_status).label}'.", messages.SUCCESS)
        for problem in problems:
            self.message_user(request, problem, messages.WARNING)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not policy.has_perm(request.user, "orders.edit"):
            for name in ("confirm", "start_preparing", "mark_ready", "send_out", "complete"):
                actions.pop(name, None)
        return actions

    @admin.action(description="Confirm selected orders")
    def confirm(self, request, queryset):
        self._bulk(request, queryset, S.CONFIRMED)

    @admin.action(description="Start preparing selected orders")
    def start_preparing(self, request, queryset):
        self._bulk(request, queryset, S.PREPARING)

    @admin.action(description="Mark selected orders ready (for pickup or delivery)")
    def mark_ready(self, request, queryset):
        self._bulk(request, queryset, S.READY)

    @admin.action(description="Send selected delivery orders out for delivery")
    def send_out(self, request, queryset):
        self._bulk(request, queryset, S.OUT_FOR_DELIVERY)

    @admin.action(description="Complete selected orders (picked up or delivered)")
    def complete(self, request, queryset):
        self._bulk(request, queryset, S.COMPLETED)

    # ---- status and payment page, export ----
    def get_urls(self):
        return [
            path("<int:pk>/status/", self.admin_site.admin_view(self.status_view), name="orders_order_status"),
            path("export/", self.admin_site.admin_view(self.export_view), name="orders_order_export"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_export"] = policy.has_perm(request.user, "orders.export")
        return super().changelist_view(request, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_change_status"] = policy.has_perm(request.user, "orders.edit")
        order = Order.objects.filter(pk=object_id).select_related("delivery_area").first() if str(object_id).isdigit() else None
        extra_context["warnings"] = services.warnings(order) if order else []
        return super().change_view(request, object_id, form_url, extra_context)

    def status_view(self, request, pk):
        if not self.has_module_permission(request) or not policy.require(request.user, "orders.edit", request=request):
            raise PermissionDenied
        order = get_object_or_404(Order, pk=pk)
        status_form = StatusForm(request.POST if "move" in request.POST else None, order=order)
        payment_form = PaymentForm(request.POST if "pay" in request.POST else None)
        if request.method == "POST":
            try:
                if "move" in request.POST and status_form.is_valid():
                    services.change_status(order, status_form.cleaned_data["to"], actor=request.user, note=status_form.cleaned_data["note"])
                    order.refresh_from_db()
                    self.message_user(request, f"Order #{order.number} is now '{order.status_text}'.", messages.SUCCESS)
                    return redirect(reverse("admin:orders_order_change", args=[order.pk]))
                if "pay" in request.POST and payment_form.is_valid():
                    services.set_paid(order, True, method=payment_form.cleaned_data["method"], actor=request.user)
                    self.message_user(request, f"Order #{order.number} is marked as paid.", messages.SUCCESS)
                    return redirect(reverse("admin:orders_order_change", args=[order.pk]))
                if "unpay" in request.POST:
                    services.set_paid(order, False, actor=request.user)
                    self.message_user(request, f"Order #{order.number} is marked as not paid.", messages.WARNING)
                    return redirect(reverse("admin:orders_order_change", args=[order.pk]))
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
                order.refresh_from_db()
                status_form = StatusForm(order=order)
        context = {
            **self.admin_site.each_context(request), "title": f"Status and payment: order #{order.number}", "order": order,
            "status_form": status_form, "payment_form": payment_form, "opts": self.model._meta,
            "events": [
                {"at": e.at, "from": services.status_label(order, e.from_status) if e.from_status else "–", "to": services.status_label(order, e.to_status),
                 "by": e.actor.email if e.actor else "system", "note": e.note}
                for e in order.events.select_related("actor")
            ],
            "back": reverse("admin:orders_order_change", args=[order.pk]),
        }
        return render(request, "admin/orders/order/status.html", context)

    def export_view(self, request):
        if not self.has_module_permission(request) or not policy.require(request.user, "orders.export", request=request):
            raise PermissionDenied
        from apps.core import csvtools

        qs = Order.objects.order_by("number")
        audit("orders.export", actor=request.user, metadata={"orders": qs.count()})
        return csvtools.csv_response("orders.csv", EXPORT_COLUMNS, export_rows(qs))


@admin.register(CustomerMessageSettings)
class CustomerMessageSettingsAdmin(ConfigureOnlyMixin, admin.ModelAdmin):
    """Which WhatsApp messages customers get about their orders (task 2.3). Changing needs Orders – Configure."""

    readonly_fields = ["whatsapp", "templates_to_create"]
    fieldsets = [
        ("WhatsApp", {"fields": ["whatsapp"]}),
        ("Messages customers get", {"fields": ["ask_to_confirm", "on_confirmed", "on_final_price", "on_ready", "on_out_for_delivery", "on_cancelled"],
                                    "description": "Messages are in English. Within 24 hours of the customer's last message they are sent as normal "
                                                   "messages (with Yes and No buttons where needed). Later, the approved templates below are used."}),
        ("Approved templates (for messages after 24 hours)", {
            "fields": ["template_language", "template_confirm_request", "template_confirmed", "template_final_price", "template_ready",
                       "template_out_for_delivery", "template_cancelled"],
            "description": "The names must match the templates approved in Meta. Leave a name empty to send that message only within 24 hours."}),
        ("Templates to create in Meta (category: Utility, language: English)", {"fields": ["templates_to_create"]}),
    ]

    def has_add_permission(self, request, *args):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        return redirect(reverse("admin:orders_customermessagesettings_change", args=[notify.current_settings().pk]))

    @admin.display(description="Connection")
    def whatsapp(self, obj):
        if notify.whatsapp_connected():
            return "WhatsApp is connected."
        return "WhatsApp is not connected, so no messages are sent. Connect it on the Integrations page."

    @admin.display(description="Templates")
    def templates_to_create(self, obj):
        from django.utils.html import format_html, format_html_join

        rows = []
        for kind, text in notify.TEMPLATES.items():
            name = getattr(obj, notify.TEMPLATE_FIELD[kind]) or "(not used)"
            buttons = " and ".join(f"“{b}”" for b in notify.BUTTONS.get(kind, ())) or "none"
            rows.append((name, text, buttons))
        return format_html(
            "<table><thead><tr><th>Name</th><th>Text</th><th>Quick-reply buttons</th></tr></thead><tbody>{}</tbody></table>",
            format_html_join("", "<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>", rows))
