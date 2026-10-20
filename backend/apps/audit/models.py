"""
Audit log.

Every important action is stored as an AuditEvent. Events are append-only:
- the model refuses updates and deletes,
- a database trigger refuses UPDATE, DELETE and TRUNCATE on the table,
- each event stores a SHA-256 hash of its content plus the previous event's
  hash, so any change to an old row breaks the chain and is detected by
  `python manage.py verify_audit_chain`.

There is one audit table per schema: the platform's in `public`, and each
business's in its own schema.
"""
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit events cannot be changed.")

    def delete(self):
        raise PermissionError("Audit events cannot be deleted.")


class AuditEvent(models.Model):
    class ActorType(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"
        AI = "ai", "AI agent"
        PLATFORM = "platform", "Platform administrator"
        ANONYMOUS = "anonymous", "Anonymous"

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        DENIED = "denied", "Denied"
        FAILED = "failed", "Failed"

    created_at = models.DateTimeField(db_index=True)
    actor_type = models.CharField(max_length=20, choices=ActorType.choices)
    actor_id = models.BigIntegerField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=100, db_index=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_repr = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, default=Outcome.SUCCESS)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    metadata = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    prev_hash = models.CharField(max_length=64, blank=True)
    hash = models.CharField(max_length=64, unique=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor_email", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action} {self.outcome} by {self.actor_email or self.actor_type}"

    # Fields covered by the hash, in a fixed order.
    HASHED_FIELDS = (
        "created_at", "actor_type", "actor_id", "actor_email", "action", "target_type", "target_id",
        "target_repr", "outcome", "ip_address", "user_agent", "changes", "metadata", "prev_hash",
    )

    def compute_hash(self) -> str:
        payload = {name: getattr(self, name) for name in self.HASHED_FIELDS}
        canonical = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Audit events cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events cannot be deleted.")
