"""
The daily owner summary (task 2.7, D-155 and D-156).

One settings row per business (when and to whom), and one row per day that
was sent or skipped, so a summary is never sent twice for the same day.
"""
from datetime import time

from django.db import models


class DailySummarySettings(models.Model):
    enabled = models.BooleanField("Send the daily summary", default=True)
    send_at = models.TimeField("Send at", default=time(20, 0), help_text="New Zealand time. The summary covers the day until then.")
    by_whatsapp = models.BooleanField("By WhatsApp", default=True)
    whatsapp_numbers = models.CharField(
        "WhatsApp numbers", max_length=300, blank=True,
        help_text="The owner's mobile numbers, separated by commas, for example 021 123 4567. Empty = no WhatsApp summary.")
    template_name = models.CharField("Template", max_length=100, default="daily_summary",
                                     help_text="The name of the approved template in Meta (see below).")
    template_language = models.CharField("Template language", max_length=10, default="en")
    by_email = models.BooleanField("By email", default=True)
    email_to = models.CharField(
        "Email to", max_length=500, blank=True,
        help_text="Email addresses, separated by commas. Empty = every active staff member with Orders – Configure and Reports – View "
                  "(for example the Business Owner).")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "daily summary settings"
        verbose_name_plural = "daily summary settings"

    def __str__(self):
        return "Daily summary settings"

    def clean(self):
        import re

        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        from apps.customers.services import normalise_phone

        errors = {}
        numbers = []
        for raw in (self.whatsapp_numbers or "").split(","):
            if raw.strip():
                try:
                    numbers.append(normalise_phone(raw.strip()))
                except ValidationError:
                    errors["whatsapp_numbers"] = f"“{raw.strip()}” is not a valid phone number."
        self.whatsapp_numbers = ", ".join(dict.fromkeys(numbers))
        emails = [e.strip() for e in (self.email_to or "").split(",") if e.strip()]
        for email in emails:
            try:
                validate_email(email)
            except ValidationError:
                errors["email_to"] = f"“{email}” is not a valid email address."
        self.email_to = ", ".join(dict.fromkeys(emails))
        self.template_name = (self.template_name or "").strip()
        if self.template_name and not re.fullmatch(r"[a-z0-9_]{1,100}", self.template_name):
            errors["template_name"] = "Template names use lower-case letters, numbers and _ (as approved in Meta)."
        if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", self.template_language or ""):
            errors["template_language"] = "Use a language code such as en or en_US."
        if errors:
            raise ValidationError(errors)

    def phone_list(self) -> list[str]:
        return [p.strip() for p in (self.whatsapp_numbers or "").split(",") if p.strip()]

    def email_list(self) -> list[str]:
        return [e.strip() for e in (self.email_to or "").split(",") if e.strip()]


class DailySummary(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        PARTLY = "partly", "Partly sent"
        SKIPPED = "skipped", "Not sent"
        FAILED = "failed", "Not sent (error)"

    day = models.DateField(unique=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    text = models.TextField(blank=True, help_text="The summary as it was sent.")
    whatsapp_result = models.CharField("WhatsApp", max_length=300, blank=True)
    email_result = models.CharField("Email", max_length=300, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-day"]
        verbose_name = "daily summary"
        verbose_name_plural = "daily summaries"

    def __str__(self):
        return f"Daily summary {self.day:%d %b %Y}"
