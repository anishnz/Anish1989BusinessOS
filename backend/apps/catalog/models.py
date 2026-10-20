"""
Products a business sells, grouped in categories.

Prices are in New Zealand dollars and include GST (as shown to customers).
Products sold by weight use the price per kg; the final price is worked out
from the real weight when the order is packed (task 1.7 / step 2).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

ZERO = Decimal("0")
CENT = Decimal("0.01")


class Category(models.Model):
    name = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower numbers are shown first.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        constraints = [models.UniqueConstraint(Lower("name"), name="catalog_category_name_unique")]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        KG = "kg", "Per kg (sold by weight)"
        EACH = "each", "Each"
        PACK = "pack", "Per pack"

    sku = models.CharField("SKU / code", max_length=40, blank=True, help_text="Your own product code. Optional, but must be unique.")
    name = models.CharField(max_length=150)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.EACH)
    price = models.DecimalField(
        "Price (NZ$, incl. GST)", max_digits=10, decimal_places=2, validators=[MinValueValidator(ZERO)],
        help_text="For products sold by weight, the price per kg.",
    )
    cost_price = models.DecimalField(
        "Cost price (NZ$)", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(ZERO)],
        help_text="Only people who can edit products see this.",
    )
    gst_applies = models.BooleanField("GST applies", default=True, help_text="15% GST is included in the price.")
    min_quantity = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1"), validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Smallest amount a customer can order, e.g. 0.5 for half a kg.",
    )
    quantity_step = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1"), validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Amounts go up in these steps, e.g. 0.5 kg.",
    )
    search_terms = models.TextField(
        blank=True, help_text="Other names customers use, separated by commas (e.g. goat curry cut, khasi ko masu). Helps search and the AI.",
    )
    is_available = models.BooleanField("Available to order", default=True)
    is_archived = models.BooleanField("Archived", default=False, help_text="Archived products are hidden but kept for old orders and reports.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("sku"), condition=~Q(sku=""), name="catalog_product_sku_unique"),
            models.CheckConstraint(condition=Q(price__gte=0), name="catalog_product_price_not_negative"),
            models.CheckConstraint(condition=Q(cost_price__isnull=True) | Q(cost_price__gte=0), name="catalog_product_cost_not_negative"),
            models.CheckConstraint(condition=Q(min_quantity__gt=0) & Q(quantity_step__gt=0), name="catalog_product_quantities_positive"),
        ]
        indexes = [models.Index(fields=["is_archived", "is_available"])]

    def __str__(self):
        return f"{self.name} ({self.sku})" if self.sku else self.name

    @property
    def sold_by_weight(self) -> bool:
        return self.unit == self.Unit.KG

    @property
    def gst_amount(self) -> Decimal:
        """The GST included in the price (3/23 of a GST-inclusive price at 15%)."""
        if not self.gst_applies:
            return ZERO
        return gst_in(self.price)


def gst_in(amount: Decimal, rate: Decimal | None = None) -> Decimal:
    rate = Decimal(str(rate if rate is not None else getattr(settings, "GST_RATE", "0.15")))
    return (Decimal(amount) * rate / (1 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
