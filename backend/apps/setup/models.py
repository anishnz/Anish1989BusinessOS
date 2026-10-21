"""
Business details and the first-login setup wizard (task 1.16).
Both tables exist only inside each business's schema (one row each).
"""
from django.db import models


class BusinessProfile(models.Model):
    """Details shown to customers later (invoices, website, WhatsApp messages)."""

    trading_name = models.CharField(max_length=200, blank=True, help_text="The name customers know. Empty = the registered name.")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True, help_text="Where customers can write to the business.")
    address = models.CharField(max_length=200, blank=True, help_text="Street and number")
    suburb = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=10, blank=True)
    gst_number = models.CharField(max_length=20, blank=True, verbose_name="GST number")
    website = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_email = models.EmailField(blank=True)


class SetupProgress(models.Model):
    """Where the business's admins are in the setup wizard."""

    business_done_at = models.DateTimeField(null=True, blank=True)
    backups_skipped_at = models.DateTimeField(null=True, blank=True)
    keys_seen_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_email = models.EmailField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
