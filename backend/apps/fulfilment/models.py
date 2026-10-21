"""
Pickup and delivery settings (task 2.1). Every table lives inside each
business's schema.

- FulfilmentSettings: one row. Pickup and delivery on or off, slot length,
  orders per slot, preparation time and how many days ahead customers can order.
- OpeningHours: when pickup or delivery happens on each weekday. A day can
  have several periods (for example 9:00-12:00 and 13:00-17:00).
- ClosedDay: dates with no pickup and no delivery (public holidays).
- DeliveryArea: where the business delivers, found by postcode or suburb,
  with a fee, a minimum order and an optional free-delivery amount.

The rules that use these tables are in services.py (D-120 to D-122).
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

ZERO = Decimal("0")


class Kind(models.TextChoices):
    PICKUP = "pickup", "Pickup"
    DELIVERY = "delivery", "Delivery"


WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday")]


class FulfilmentSettings(models.Model):
    PICKUP_SLOT_CHOICES = [(15, "15 minutes"), (30, "30 minutes"), (60, "1 hour")]
    DELIVERY_SLOT_CHOICES = [(30, "30 minutes"), (60, "1 hour"), (120, "2 hours"), (180, "3 hours")]

    pickup_enabled = models.BooleanField("Customers can pick up orders", default=True)
    pickup_slot_minutes = models.PositiveSmallIntegerField("Pickup slot length", choices=PICKUP_SLOT_CHOICES, default=30)
    pickup_capacity = models.PositiveSmallIntegerField(
        "Pickup orders per slot", default=5, validators=[MaxValueValidator(500)],
        help_text="The most orders you can have ready in one pickup slot. 0 = no limit.",
    )
    delivery_enabled = models.BooleanField("You deliver orders", default=False)
    delivery_slot_minutes = models.PositiveSmallIntegerField("Delivery window length", choices=DELIVERY_SLOT_CHOICES, default=60)
    delivery_capacity = models.PositiveSmallIntegerField(
        "Deliveries per window", default=3, validators=[MaxValueValidator(500)],
        help_text="The most deliveries you can make in one window. 0 = no limit.",
    )
    lead_minutes = models.PositiveIntegerField(
        "Preparation time (minutes)", default=60, validators=[MaxValueValidator(7 * 24 * 60)],
        help_text="Customers can only choose a slot that starts at least this long after they order.",
    )
    days_ahead = models.PositiveSmallIntegerField(
        "Days ahead", default=7, validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="How many days ahead customers can choose a time (1 = today only).",
    )
    delivery_fee_gst = models.BooleanField("Delivery fees include GST", default=True, help_text="15% GST is included in the delivery fee.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "Pickup and delivery settings"

    def __str__(self):
        return "Pickup and delivery settings"

    @property
    def audit_label(self) -> str:
        return "Pickup and delivery settings"

    def slot_minutes(self, kind: str) -> int:
        return self.delivery_slot_minutes if kind == Kind.DELIVERY else self.pickup_slot_minutes

    def capacity(self, kind: str) -> int:
        return self.delivery_capacity if kind == Kind.DELIVERY else self.pickup_capacity

    def enabled(self, kind: str) -> bool:
        return self.delivery_enabled if kind == Kind.DELIVERY else self.pickup_enabled


class OpeningHours(models.Model):
    settings = models.ForeignKey(FulfilmentSettings, on_delete=models.CASCADE, related_name="hours")
    kind = models.CharField("For", max_length=10, choices=Kind.choices, default=Kind.PICKUP)
    weekday = models.PositiveSmallIntegerField(choices=WEEKDAYS)
    opens = models.TimeField("From")
    closes = models.TimeField("Until")

    class Meta:
        ordering = ["-kind", "weekday", "opens"]  # pickup first
        verbose_name = "opening hours"
        verbose_name_plural = "opening hours"
        constraints = [
            models.CheckConstraint(condition=Q(closes__gt=F("opens")), name="fulfilment_hours_close_after_open"),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="fulfilment_hours_weekday_valid"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.get_weekday_display()} {self.opens:%H:%M}-{self.closes:%H:%M}"


class ClosedDay(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=100, blank=True, help_text="For example: Christmas Day. Customers may see this.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        day = self.date.strftime("%d %b %Y") if hasattr(self.date, "strftime") else str(self.date)
        return day + (f" ({self.reason})" if self.reason else "")


class DeliveryArea(models.Model):
    name = models.CharField(max_length=100, help_text="For example: Central Auckland. Customers may see this.")
    postcodes = models.CharField(
        max_length=500, blank=True, help_text="4-digit postcodes separated by commas, for example: 1010, 1011, 1021.",
    )
    suburbs = models.TextField(blank=True, help_text="Suburb names separated by commas, for example: Mount Roskill, Three Kings.")
    fee = models.DecimalField("Delivery fee (NZ$)", max_digits=8, decimal_places=2, validators=[MinValueValidator(ZERO)])
    minimum_order = models.DecimalField(
        "Minimum order (NZ$)", max_digits=10, decimal_places=2, default=ZERO, validators=[MinValueValidator(ZERO)],
        help_text="Products must cost at least this much (delivery fee not counted). 0 = no minimum.",
    )
    free_over = models.DecimalField(
        "Free delivery from (NZ$)", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(ZERO)],
        help_text="No delivery fee when the products cost at least this much. Empty = never free.",
    )
    is_active = models.BooleanField("Delivering here now", default=True)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower numbers are checked and shown first.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(fee__gte=0) & Q(minimum_order__gte=0), name="fulfilment_area_amounts_not_negative"),
            models.CheckConstraint(condition=Q(free_over__isnull=True) | Q(free_over__gte=0), name="fulfilment_area_free_not_negative"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        from .services import check_area

        check_area(self)

    def postcode_list(self) -> list[str]:
        return [p.strip() for p in self.postcodes.split(",") if p.strip()]

    def suburb_list(self) -> list[str]:
        return [s.strip() for s in self.suburbs.split(",") if s.strip()]
