"""
Unified inbox: one conversation per customer per channel, with its messages.

Only WhatsApp is connected now; the same tables will hold Viber, Telegram,
SMS and website chat later. Message text is personal data: it is never
copied into the audit log, and it is deleted when a customer's personal data
is removed.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.customers.models import Customer


class Conversation(models.Model):
    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WHATSAPP)
    external_id = models.CharField(max_length=64, blank=True, help_text="The customer's id on the channel (WhatsApp: phone digits).")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    unread_count = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True, help_text="Last message from the customer (starts the 24-hour reply window).")
    last_message_preview = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_message_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["channel", "external_id"], condition=~Q(external_id=""), name="inbox_conversation_unique_contact"),
        ]
        indexes = [models.Index(fields=["status", "last_message_at"])]

    def __str__(self):
        return f"{self.get_channel_display()} conversation #{self.pk}"

    @property
    def audit_label(self) -> str:
        return f"Conversation #{self.pk}"


class Message(models.Model):
    class Direction(models.TextChoices):
        IN = "in", "From customer"
        OUT = "out", "From business"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        QUEUED = "queued", "Sending"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        READ = "read", "Read"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    kind = models.CharField(max_length=20, default="text")
    text = models.TextField(blank=True)
    media_id = models.CharField(max_length=128, blank=True)
    template_name = models.CharField(max_length=100, blank=True)
    provider_message_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.CharField(max_length=300, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    provider_timestamp = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class WebhookDelivery(models.Model):
    """Short log of incoming webhook calls (no message content), for the 'Check system' button and support."""

    received_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=20, default="whatsapp")
    ok = models.BooleanField()
    note = models.CharField(max_length=200, blank=True)
    messages = models.PositiveIntegerField(default=0)
    statuses = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-received_at"]
        verbose_name_plural = "webhook deliveries"
