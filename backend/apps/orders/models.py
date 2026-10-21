"""
Orders: what a customer asked for, at the prices of the moment.

- Each line keeps a copy of the product name, unit and price, so later price
  changes never change an old order.
- Products sold by weight: the customer orders an amount (for example 1 kg);
  staff enter the real weight when packing (for example 1.08 kg) and the
  final price is worked out from it. The customer accepts the final price.
- All money is NZ$ including GST, rounded to the cent.
- Pickup or delivery (task 2.1): the due time is the pickup time or the start
  of the delivery window. A delivery order also has an address, an area and
  the delivery fee of that area, which is part of the total.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import Product
from apps.core.business import SET_NULL_IN_BUSINESS
from apps.customers.models import Customer
from apps.fulfilment.models import DeliveryArea, Kind


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting_confirmation", "Awaiting customer confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        PREPARING = "preparing", "Being prepared"
        FINAL_SENT = "final_price_sent", "Final price sent"
        FINAL_ACCEPTED = "final_price_accepted", "Final price accepted"
        READY = "ready", "Ready"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        COMPLETED = "completed", "Completed"
        CANCELLED_CUSTOMER = "cancelled_by_customer", "Cancelled by customer"
        CANCELLED_SHOP = "cancelled_by_shop", "Cancelled by shop"
        EXPIRED = "expired", "Expired"

    class Channel(models.TextChoices):
        COUNTER = "counter", "Counter"
        PHONE = "phone", "Phone"
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBSITE = "website", "Website"

    class PaymentMethod(models.TextChoices):
        NONE = "", "Not paid"
        CASH = "cash", "Cash"
        CARD = "card", "Card (EFTPOS)"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        OTHER = "other", "Other"

    number = models.PositiveIntegerField(unique=True, editable=False)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="orders",
                                 help_text="Leave empty for a walk-in customer.")
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.COUNTER)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT, editable=False)
    fulfilment = models.CharField("Pickup or delivery", max_length=10, choices=Kind.choices, default=Kind.PICKUP)
    due_at = models.DateTimeField("Pickup or delivery time", null=True, blank=True,
                                  help_text="The pickup time, or the start of the delivery window.")
    due_until = models.DateTimeField("Until", null=True, blank=True, editable=False,
                                     help_text="The end of the chosen slot. Empty when staff typed an exact time.")
    delivery_address = models.CharField(max_length=200, blank=True, help_text="Street and number, flat or unit, and delivery notes.")
    delivery_suburb = models.CharField("Suburb", max_length=100, blank=True)
    delivery_postcode = models.CharField("Postcode", max_length=4, blank=True)
    delivery_area = models.ForeignKey(DeliveryArea, null=True, blank=True, on_delete=models.PROTECT, related_name="orders",
                                      help_text="Found from the postcode or suburb when left empty.")
    delivery_fee = models.DecimalField("Delivery fee (NZ$)", max_digits=8, decimal_places=2, default=Decimal("0"), editable=False)
    delivery_fee_gst = models.BooleanField("GST in the delivery fee", default=True, editable=False)
    stock_taken = models.BooleanField(default=False, editable=False,
                                      help_text="This order took its products off the stock when it was confirmed (task 2.2).")
    notes = models.TextField(blank=True, help_text="Customer requests, for example 'cut into small pieces'.")
    estimated_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    total = models.DecimalField("Total (NZ$, incl. GST)", max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    gst_total = models.DecimalField("GST included", max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    is_paid = models.BooleanField("Paid", default=False, editable=False)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True, default="", editable=False)
    paid_at = models.DateTimeField(null=True, blank=True, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["created_at"]), models.Index(fields=["due_at"], name="orders_order_due_at_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0) & Q(estimated_total__gte=0) & Q(gst_total__gte=0), name="orders_totals_not_negative"),
            models.CheckConstraint(condition=Q(delivery_fee__gte=0), name="orders_delivery_fee_not_negative"),
        ]

    def __str__(self):
        return f"Order #{self.number}"

    @property
    def audit_label(self) -> str:
        return f"Order #{self.number}"

    @property
    def is_open(self) -> bool:
        return self.status not in CLOSED_STATUSES

    @property
    def is_delivery(self) -> bool:
        return self.fulfilment == Kind.DELIVERY

    @property
    def status_text(self) -> str:
        """The status in words; "Ready" says what the order is ready for."""
        if self.status == self.Status.READY:
            return "Ready for delivery" if self.is_delivery else "Ready for pickup"
        return self.get_status_display()

    @property
    def products_estimate(self) -> Decimal:
        """The estimated price of the products, without the delivery fee."""
        return self.estimated_total - self.delivery_fee

    @property
    def needs_weighing(self) -> bool:
        return any(line.unit == Product.Unit.KG and line.final_quantity is None for line in self.lines.all())


CLOSED_STATUSES = {
    Order.Status.COMPLETED, Order.Status.CANCELLED_CUSTOMER, Order.Status.CANCELLED_SHOP, Order.Status.EXPIRED,
}
EDITABLE_STATUSES = {Order.Status.DRAFT, Order.Status.AWAITING}


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    product_name = models.CharField(max_length=150, editable=False)
    unit = models.CharField(max_length=10, choices=Product.Unit.choices, editable=False)
    unit_price = models.DecimalField("Unit price (NZ$, incl. GST)", max_digits=10, decimal_places=2, editable=False)
    gst_applies = models.BooleanField(default=True, editable=False)
    quantity = models.DecimalField("Ordered amount", max_digits=10, decimal_places=3)
    final_quantity = models.DecimalField("Real weight", max_digits=10, decimal_places=3, null=True, blank=True,
                                         help_text="For products sold by weight: the weight after packing.")
    note = models.CharField(max_length=200, blank=True)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="orders_line_quantity_positive"),
            models.CheckConstraint(condition=Q(final_quantity__isnull=True) | Q(final_quantity__gt=0), name="orders_line_final_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="orders_line_price_not_negative"),
        ]

    def __str__(self):
        return f"{self.product_name} × {self.effective_quantity.normalize():f}"

    @property
    def effective_quantity(self) -> Decimal:
        return self.final_quantity if self.final_quantity is not None else self.quantity


class OrderEvent(models.Model):
    """Status history: who moved the order, when, and why."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    note = models.CharField(max_length=300, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]


class OrderCounter(models.Model):
    """One row per business: the last order number used (orders start at #1001)."""

    last_number = models.PositiveIntegerField(default=1000)
