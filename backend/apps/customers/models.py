"""
Customers of a business (people who order, enquire or book).

Phone numbers are stored in international format (+6421...), so WhatsApp
messages and duplicate checks work. Marketing consent is recorded with
when and how it was given, because NZ law (Unsolicited Electronic Messages
Act 2007) needs consent before marketing messages are sent.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.business import SET_NULL_IN_BUSINESS


class Customer(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Added by staff"
        IMPORT = "import", "CSV import"
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBSITE = "website", "Website"
        WALK_IN = "walk_in", "Walk-in / phone"

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True, help_text="Any format; saved as +64... (other countries: start with +).")
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Visible to staff only. Do not store card or bank numbers here.")
    tags = models.CharField(max_length=200, blank=True, help_text="Words separated by commas, e.g. regular, wholesale, halal.")
    preferred_language = models.CharField(max_length=30, blank=True, help_text="For example English, Nepali, Hindi.")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    marketing_consent = models.BooleanField("Agreed to marketing messages", default=False)
    marketing_consent_at = models.DateTimeField(null=True, blank=True, editable=False)
    is_archived = models.BooleanField("Archived", default=False)
    is_anonymised = models.BooleanField("Personal data removed", default=False, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["phone"], condition=~Q(phone=""), name="customers_phone_unique"),
            models.UniqueConstraint(Lower("email"), condition=~Q(email=""), name="customers_email_unique"),
        ]
        indexes = [models.Index(fields=["is_archived"])]

    def __str__(self):
        return self.name

    @property
    def audit_label(self) -> str:
        """Shown in the audit log instead of the name, which is personal data."""
        return f"Customer #{self.pk}"

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class ConsentRecord(models.Model):
    """Append-only history of marketing consent (yes or no), with how it was given."""

    class Source(models.TextChoices):
        STAFF = "staff", "Recorded by staff"
        IMPORT = "import", "CSV import"
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBSITE = "website", "Website form"
        STOP = "stop", "Customer replied STOP"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="consent_records")
    channel = models.CharField(max_length=20, default="all", help_text="all, whatsapp, email or sms")
    given = models.BooleanField()
    source = models.CharField(max_length=20, choices=Source.choices)
    note = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
