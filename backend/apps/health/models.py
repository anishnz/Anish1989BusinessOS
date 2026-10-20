"""
History of "Check system" runs. The table exists in the platform schema
(platform checks) and in every business schema (that business's checks).
"""
from django.db import models


class CheckRun(models.Model):
    class Status(models.TextChoices):
        OK = "ok", "OK"
        WARNING = "warning", "Warning"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        BUTTON = "button", "Check system button"
        SCHEDULE = "schedule", "Schedule"
        COMMAND = "command", "Server command"

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    run_by_email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    counts = models.JSONField(default=dict)  # {"ok": 7, "warning": 1, ...}
    results = models.JSONField(default=list)  # [{"code", "area", "label", "status", "message"}]
    alert_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [models.Index(fields=["-started_at"])]

    def __str__(self) -> str:
        return f"{self.started_at:%Y-%m-%d %H:%M} {self.status}"

    @property
    def seconds(self) -> float:
        return round((self.finished_at - self.started_at).total_seconds(), 1)
