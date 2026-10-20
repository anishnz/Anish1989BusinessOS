"""
A Connection is one provider account a business has connected (for example
its OpenAI key or its WhatsApp Business number). One table per schema, so
each business's connections are in its own database area.

Secret values are stored only in encrypted form (see crypto.py). Plain
settings that are not secret (for example a model name or phone number id)
are stored in `config`.
"""
import uuid

from django.conf import settings
from django.db import models


class Connection(models.Model):
    class Status(models.TextChoices):
        NOT_TESTED = "not_tested", "Saved, not tested"
        CONNECTED = "connected", "Connected"
        FAILED = "failed", "Failed"
        DISABLED = "disabled", "Disabled"

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider = models.CharField(max_length=50)
    category = models.CharField(max_length=30)
    label = models.CharField(max_length=100)
    is_backup = models.BooleanField(default=False, help_text="Use only if the main connection of this category fails.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_TESTED)
    config = models.JSONField(default=dict, blank=True)

    # Encrypted secrets (a JSON object of all secret fields, sealed as one value).
    secret_kid = models.CharField(max_length=40, blank=True)
    secret_wrapped_key = models.BinaryField(null=True, blank=True)
    secret_key_nonce = models.BinaryField(null=True, blank=True)
    secret_nonce = models.BinaryField(null=True, blank=True)
    secret_ciphertext = models.BinaryField(null=True, blank=True)
    secret_hints = models.JSONField(default=dict, blank=True, help_text="Last 4 characters of each secret, for display.")

    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_message = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "is_backup", "label"]

    def __str__(self) -> str:
        return f"{self.label} ({self.provider})"

    @property
    def has_secrets(self) -> bool:
        return bool(self.secret_ciphertext)
