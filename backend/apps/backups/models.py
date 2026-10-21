"""
Backups. Both tables exist in the platform schema (the platform's full
backups) and in every business schema (that business's own backups to its
Google Drive).
"""
from django.db import models


class BackupSettings(models.Model):
    """One row per site (platform or business)."""

    EVERY_HOURS_CHOICES = [(6, "Every 6 hours"), (12, "Every 12 hours"), (24, "Once a day")]

    every_hours = models.PositiveSmallIntegerField(default=6, choices=EVERY_HOURS_CHOICES)
    drive_folder_name = models.CharField(max_length=120, blank=True)
    drive_folder_id = models.CharField(max_length=200, blank=True)
    drive_paused_reason = models.CharField(max_length=300, blank=True, help_text="Why copies to Google Drive stopped (for example access was removed).")

    # Business sites only: the backup passphrase, encrypted with the vault master key.
    # It is shown once when set and never again.
    passphrase_kid = models.CharField(max_length=40, blank=True)
    passphrase_wrapped_key = models.BinaryField(null=True, blank=True)
    passphrase_key_nonce = models.BinaryField(null=True, blank=True)
    passphrase_nonce = models.BinaryField(null=True, blank=True)
    passphrase_ciphertext = models.BinaryField(null=True, blank=True)
    passphrase_set_at = models.DateTimeField(null=True, blank=True)
    passphrase_set_by_email = models.EmailField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "backup settings"

    @property
    def has_passphrase(self) -> bool:
        return bool(self.passphrase_ciphertext)


class BackupRun(models.Model):
    class Kind(models.TextChoices):
        BACKUP = "backup", "Backup"
        RESTORE_TEST = "restore_test", "Restore test"

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting"
        RUNNING = "running", "Running"
        OK = "ok", "OK"
        WARNING = "warning", "Needs attention"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        BUTTON = "button", "Button"
        COMMAND = "command", "Server command"

    class Drive(models.TextChoices):
        NOT_SET_UP = "not_set_up", "Not set up"
        UPLOADED = "uploaded", "Copied"
        FAILED = "failed", "Failed"
        PAUSED = "paused", "Paused"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    run_by_email = models.EmailField(blank=True)
    queued_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Backups: the encrypted file.
    file_name = models.CharField(max_length=200, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    kept_locally = models.BooleanField(default=False)
    drive_status = models.CharField(max_length=20, choices=Drive.choices, default=Drive.NOT_SET_UP)
    drive_file_id = models.CharField(max_length=200, blank=True)

    # Restore tests: which backup was tested.
    tested_backup = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="restore_tests")

    message = models.CharField(max_length=500, blank=True)  # plain words, never secrets or technical errors
    details = models.JSONField(default=dict, blank=True)  # tables, rows, differences, deleted old copies
    alert_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-queued_at", "-id"]
        indexes = [models.Index(fields=["kind", "-queued_at"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.queued_at:%Y-%m-%d %H:%M} {self.status}"

    @property
    def seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 1)
        return None

    @property
    def finished(self) -> bool:
        return self.status in (self.Status.OK, self.Status.WARNING, self.Status.FAILED)
