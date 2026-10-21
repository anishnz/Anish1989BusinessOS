"""
Tickets (task 1.15). The same tables exist in every business schema (the
business's own tickets: staff report a problem, the business's admins handle
it) and in the platform schema (platform support tickets: a business admin
sends a ticket on, or a platform admin reports something).

A platform ticket that came from a business keeps the business's schema and
ticket number, so the business can follow it. People of a business are not
users of the platform, so their name and email are stored as text there.
"""
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

# How soon someone other than the reporter should answer.
RESPONSE_TARGETS = {"urgent": timedelta(hours=1), "high": timedelta(hours=4), "normal": timedelta(hours=24), "low": timedelta(hours=72)}


class Ticket(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING = "waiting", "Waiting for reply"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Category(models.TextChoices):
        PROBLEM = "problem", "Something is not working"
        QUESTION = "question", "Question"
        REQUEST = "request", "Request or idea"

    class Source(models.TextChoices):
        STAFF = "staff", "Reported by a person"
        CHECK = "check", "Check system"
        BACKUP = "backup", "Backups"
        BUSINESS = "business", "Sent on by a business"

    OPEN = (Status.NEW, Status.IN_PROGRESS, Status.WAITING)

    title = models.CharField(max_length=200)
    description = models.TextField(max_length=10000)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.PROBLEM)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.STAFF)
    source_key = models.CharField(max_length=100, blank=True, help_text="Automatic tickets: one open ticket per problem.")

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets_reported")
    reporter_name = models.CharField(max_length=200, blank=True)
    reporter_email = models.EmailField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets_assigned")

    # Details added automatically when reported (never secrets: the page path without its query string).
    page = models.CharField(max_length=300, blank=True)
    browser = models.CharField(max_length=300, blank=True)

    # Business ticket sent on to platform support:
    platform_ticket_id = models.PositiveIntegerField(null=True, blank=True)
    # Platform ticket that came from a business:
    from_schema = models.CharField(max_length=63, blank=True, db_index=True)
    from_business = models.CharField(max_length=200, blank=True)
    from_ticket_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "-created_at"]), models.Index(fields=["source_key"])]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    @property
    def response_due(self):
        return self.created_at + RESPONSE_TARGETS.get(self.priority, RESPONSE_TARGETS["normal"])

    @property
    def response_overdue(self) -> bool:
        return self.is_open and self.first_response_at is None and timezone.now() > self.response_due

    @property
    def reporter_label(self) -> str:
        if self.source in (self.Source.CHECK, self.Source.BACKUP):
            return "System"
        return self.reporter_name or self.reporter_email or "Unknown"


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    author_name = models.CharField(max_length=200, blank=True)
    author_email = models.EmailField(blank=True)
    body = models.TextField(max_length=10000)
    internal = models.BooleanField(default=False, help_text="Internal note: not shown to the reporter (or, on the platform, to the business).")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def author_label(self) -> str:
        return self.author_name or self.author_email or "System"
