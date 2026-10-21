"""Products in the business admin, with CSV import/export and archive instead of delete."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse

from apps.core import csvtools
from apps.core.business import ArchivedFilter, BusinessOnlyAdminMixin
from apps.rbac import policy

from . import services, stock
from .models import Category, Product, StockMovement


@admin.register(Category)
class CategoryAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    list_display = ["name", "sort_order", "is_active", "products"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("products", filter=Q(products__is_archived=False)))

    @admin.display(description="Products", ordering="n")
    def products(self, obj):
        return obj.n


class ImportForm(forms.Form):
    file = forms.FileField(label="CSV file")


class StockForm(forms.Form):
    reason = forms.ChoiceField(label="Why", choices=[(r, StockMovement.Reason(r).label) for r in stock.MANUAL_REASONS])
    quantity = forms.CharField(label="Amount", max_length=20,
                               help_text="Received or waste: the amount. Counted: the amount now in stock. Correction: the change (use - to take off).")
    note = forms.CharField(label="Note", max_length=200, required=False, help_text="Needed for waste and corrections.")


class StockFilter(admin.SimpleListFilter):
    title = "stock"
    parameter_name = "stock"

    def lookups(self, request, model_admin):
        return [("low", "Low, out or below zero"), ("counted", "Counted"), ("not_counted", "Not counted")]

    def queryset(self, request, queryset):
        from django.db.models import F, Q

        if self.value() == "low":
            return queryset.filter(track_stock=True).filter(
                Q(stock_quantity__lt=F("min_quantity")) | Q(low_stock_level__isnull=False, stock_quantity__lte=F("low_stock_level")))
        if self.value() == "counted":
            return queryset.filter(track_stock=True)
        if self.value() == "not_counted":
            return queryset.filter(track_stock=False)
        return queryset


@admin.register(Product)
class ProductAdmin(BusinessOnlyAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/catalog/product/change_list.html"
    change_form_template = "admin/catalog/product/change_form.html"
    list_display = ["name", "sku", "category", "sold_per", "price", "available", "in_stock"]
    list_filter = [ArchivedFilter, StockFilter, "is_available", "category", "unit"]
    search_fields = ["name", "sku", "search_terms"]
    list_select_related = ["category"]
    actions = ["make_available", "make_unavailable", "archive", "restore"]
    readonly_fields = ["stock_quantity", "created_by", "created_at", "updated_at"]

    def get_fieldsets(self, request, obj=None):
        price = ["unit", "price", "gst_applies"]
        if self.has_change_permission(request, obj):
            price.append("cost_price")
        return [
            (None, {"fields": ["name", "sku", "category", "description", "is_available"]}),
            ("Price and amounts", {"fields": price + ["min_quantity", "quantity_step"]}),
            ("Stock", {"fields": ["track_stock", "stock_quantity", "low_stock_level"],
                       "description": "Orders take stock off when they are confirmed. Change it with “Adjust stock” (top right)."}),
            ("Search", {"fields": ["search_terms"], "description": "Other names customers use. Helps search and the WhatsApp AI find the product."}),
            ("History", {"fields": ["is_archived", "created_by", "created_at", "updated_at"], "classes": ["collapse"]}),
        ]

    @admin.display(description="Available", boolean=True, ordering="is_available")
    def available(self, obj):
        return obj.is_available

    @admin.display(description="Sold per", ordering="unit")
    def sold_per(self, obj):
        return obj.unit

    @admin.display(description="In stock", ordering="stock_quantity")
    def in_stock(self, obj):
        if not obj.track_stock:
            return "–"
        s = stock.state(obj)
        text = stock.amount_text(obj.stock_quantity, obj)
        return text if s == "ok" else f"{text} ({stock.STATE_TEXT[s]})"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False  # archive instead, so old orders and reports keep their products

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not policy.has_perm(request.user, "products.edit"):
            for name in ("make_available", "make_unavailable", "restore"):
                actions.pop(name, None)
        if not policy.has_perm(request.user, "products.delete"):
            actions.pop("archive", None)
        return actions

    @admin.action(description="Mark selected products as available")
    def make_available(self, request, queryset):
        for product in queryset:
            product.is_available = True
            product.save()
        self.message_user(request, f"{queryset.count()} product(s) are available.", messages.SUCCESS)

    @admin.action(description="Mark selected products as not available")
    def make_unavailable(self, request, queryset):
        for product in queryset:
            product.is_available = False
            product.save()
        self.message_user(request, f"{queryset.count()} product(s) are not available.", messages.SUCCESS)

    @admin.action(description="Archive selected products")
    def archive(self, request, queryset):
        for product in queryset:
            services.archive(product, actor=request.user)
        self.message_user(request, "Archived. Choose Status: Archived on the right to see or restore them.", messages.SUCCESS)

    @admin.action(description="Restore selected archived products")
    def restore(self, request, queryset):
        for product in queryset:
            services.restore(product, actor=request.user)
        self.message_user(request, "Restored.", messages.SUCCESS)

    # ---- CSV import and export pages ----
    def get_urls(self):
        return [
            path("import/", self.admin_site.admin_view(self.import_view), name="catalog_product_import"),
            path("export/", self.admin_site.admin_view(self.export_view), name="catalog_product_export"),
            path("<int:pk>/stock/", self.admin_site.admin_view(self.stock_view), name="catalog_product_stock"),
        ] + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_adjust_stock"] = policy.has_perm(request.user, "products.edit")
        return super().change_view(request, object_id, form_url, extra_context)

    def stock_view(self, request, pk):
        """Adjust stock and see the stock history (task 2.2). Looking needs Products - View; changing needs Products - Edit."""
        if not self.has_module_permission(request) or not policy.require(request.user, "products.view", request=request):
            raise PermissionDenied
        product = get_object_or_404(Product, pk=pk)
        can_change = policy.has_perm(request.user, "products.edit")
        form = StockForm(request.POST or None)
        if request.method == "POST":
            if not can_change:
                raise PermissionDenied
            if form.is_valid():
                try:
                    stock.adjust(product, reason=form.cleaned_data["reason"], quantity=form.cleaned_data["quantity"],
                                 note=form.cleaned_data["note"], actor=request.user)
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    product.refresh_from_db()
                    self.message_user(request, f"Saved. {product.name}: {stock.amount_text(product.stock_quantity, product)} in stock.", messages.SUCCESS)
                    return redirect(reverse("admin:catalog_product_stock", args=[product.pk]))
        context = {
            **self.admin_site.each_context(request), "title": f"Stock of {product.name}", "product": product, "form": form,
            "can_change": can_change and product.track_stock, "opts": self.model._meta,
            "state": stock.STATE_TEXT[stock.state(product)], "amount": stock.amount_text(product.stock_quantity, product),
            "warn_at": stock.number_text(product.low_stock_level) if product.low_stock_level is not None else "",
            "movements": [{"m": m, "change": ("+" if m.change > 0 else "") + stock.number_text(m.change), "after": stock.number_text(m.quantity_after)}
                          for m in product.stock_movements.all()[:100]],
            "back": reverse("admin:catalog_product_change", args=[product.pk]),
        }
        return render(request, "admin/catalog/product/stock.html", context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["can_import"] = policy.has_perm(request.user, "products.import")
        extra_context["can_export"] = policy.has_perm(request.user, "products.export")
        return super().changelist_view(request, extra_context)

    def import_view(self, request):
        if not self.has_module_permission(request) or not policy.require(request.user, "products.import", request=request):
            raise PermissionDenied
        form = ImportForm(request.POST or None, request.FILES or None)
        result = None
        if request.method == "POST" and form.is_valid():
            dry_run = "check" in request.POST
            try:
                result = services.import_products(form.cleaned_data["file"], actor=request.user, dry_run=dry_run)
            except ValidationError as exc:
                form.add_error("file", exc)
            else:
                if result.ok and not dry_run:
                    self.message_user(request, f"Import finished: {result.created} added, {result.updated} updated.", messages.SUCCESS)
        context = {
            **self.admin_site.each_context(request), "title": "Import products from CSV", "form": form, "result": result,
            "opts": self.model._meta, "columns": services.CSV_COLUMNS, "back": reverse("admin:catalog_product_changelist"),
        }
        return render(request, "admin/catalog/product/import.html", context)

    def export_view(self, request):
        if not self.has_module_permission(request) or not policy.require(request.user, "products.export", request=request):
            raise PermissionDenied
        include_cost = policy.has_perm(request.user, "products.edit")
        qs = Product.objects.filter(is_archived=False)
        from apps.audit.services import audit

        audit("products.export", actor=request.user, metadata={"rows": qs.count(), "cost_included": include_cost})
        return csvtools.csv_response("products.csv", services.CSV_COLUMNS, services.export_rows(qs, include_cost=include_cost))
