"""
The business's one-page public website (task 2.9, D-164 to D-167).

The texts live in a draft (one row per business). Publish copies the draft
into a new version; the newest version is what visitors see. The last 20
versions are kept, so an older one can be restored into the draft.
Products, prices, opening hours and delivery areas are not stored here: the
page reads them from the system when it is shown.
"""
from django.db import models


class WebsiteDraft(models.Model):
    content = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_email = models.EmailField(blank=True)

    class Meta:
        verbose_name = "website draft"

    def __str__(self):
        return "Website draft"


class WebsiteVersion(models.Model):
    number = models.PositiveIntegerField(unique=True)
    content = models.JSONField(default=dict)
    published_at = models.DateTimeField(auto_now_add=True)
    published_by_email = models.EmailField(blank=True)
    note = models.CharField(max_length=120, blank=True, help_text="For example: Restored from version 3.")

    class Meta:
        ordering = ["-number"]
        verbose_name = "published website version"

    def __str__(self):
        return f"Website version {self.number}"
