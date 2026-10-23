"""
Enquiries for catering and events (task 3.1, D-168 and D-172 to D-176).

An enquiry comes from the website form, a WhatsApp chat (the AI or a staff
member) or staff. It holds the event details the business needs for a quote.
The contact details are kept as the person gave them; the enquiry is also
linked to a customer record. All of it is personal data: it is removed when
the customer's personal data is removed, and never copied into the audit log.
"""
from django.conf import settings
from django.db import models

from apps.core.business import SET_NULL_IN_BUSINESS


class EnquirySettings(models.Model):
    """One row per business (pk=1)."""

    form_enabled = models.BooleanField("Website enquiry form", default=True,
                                       help_text="Shows the form at /enquiry/ and an “Ask for a quote” button on the website.")
    form_heading = models.CharField("Form heading", max_length=80, default="Ask for a quote")
    form_intro = models.TextField("Text above the form", max_length=600, blank=True,
                                  default="Tell us about your event. We will reply with a quote, usually within one working day.")
    thanks_text = models.TextField("Thank-you text", max_length=600, blank=True,
                                   default="Thank you. We have your enquiry and will be in touch soon.")
    email_staff = models.BooleanField("Email staff about new enquiries", default=True,
                                      help_text="Goes to every active staff member with Catering and events – Edit.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "enquiry settings"
        verbose_name_plural = "enquiry settings"

    def __str__(self):
        return "Enquiry settings"


class Enquiry(models.Model):
    class Source(models.TextChoices):
        WEBSITE = "website", "Website form"
        WHATSAPP = "whatsapp", "WhatsApp"
        STAFF = "staff", "Added by staff"

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUOTED = "quoted", "Quoted"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    class EventType(models.TextChoices):
        WEDDING = "wedding", "Wedding"
        BIRTHDAY = "birthday", "Birthday"
        CORPORATE = "corporate", "Work or corporate"
        CULTURAL = "cultural", "Cultural or festival"
        RELIGIOUS = "religious", "Religious (puja, bratabandha)"
        MEMORIAL = "memorial", "Funeral or memorial"
        PARTY = "party", "Party or gathering"
        OTHER = "other", "Other"

    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    lost_reason = models.CharField(max_length=200, blank=True)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="enquiries")
    conversation = models.ForeignKey("inbox.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="enquiries")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+")

    # The contact details as given (the customer record may say something else)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)

    # The event
    event_type = models.CharField(max_length=20, choices=EventType.choices, blank=True)
    event_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=300, blank=True, help_text="Name and address, or “not booked yet”.")
    guests = models.PositiveIntegerField(null=True, blank=True)
    menu = models.TextField(blank=True, max_length=2000, help_text="Food and drinks they would like.")
    dietary_needs = models.TextField(blank=True, max_length=1000, help_text="For example vegetarian, halal, no beef, nut allergy (how many guests).")
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="NZ$ including GST, as given.")
    message = models.TextField(blank=True, max_length=3000, help_text="Anything else, in the customer's own words.")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL_IN_BUSINESS, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status_changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "enquiries"
        indexes = [models.Index(fields=["status", "created_at"]), models.Index(fields=["event_date"])]

    def __str__(self):
        return f"Enquiry #{self.pk}"

    @property
    def audit_label(self) -> str:
        return f"Enquiry #{self.pk}"

    @property
    def name(self) -> str:
        if self.contact_name:
            return self.contact_name
        if self.customer and not self.customer.is_anonymised:
            return self.customer.name
        return ""


class EnquiryActivity(models.Model):
    """What happened to an enquiry: created, status changes, details changed, staff notes."""

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        STATUS = "status", "Status changed"
        CHANGED = "changed", "Details changed"
        NOTE = "note", "Note"

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    text = models.TextField(blank=True, max_length=2000)
    by_email = models.CharField(max_length=254, blank=True, help_text="Empty: the system, the AI or the customer.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "enquiry activities"
