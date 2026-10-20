"""
Licences and module entitlements. Stored in the public schema (platform data),
one licence per business.

Access state comes from the business status plus the licence dates:

    trial      in the trial period
    active     paid and not expired
    grace      trial or licence ended, but within the grace period (still works, with warnings)
    expired    ended and past the grace period (blocked)
    suspended  suspended by the platform (blocked)
    cancelled  cancelled (blocked)
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class Licence(models.Model):
    tenant = models.OneToOneField("tenants.Tenant", on_delete=models.CASCADE, related_name="licence")
    plan_name = models.CharField(max_length=100, default="Trial", help_text="Plans and prices are added in Phase 2.")
    starts_at = models.DateTimeField(default=timezone.now)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Leave empty for no end date (paid, renewing).")
    grace_days = models.PositiveIntegerField(default=7)

    # Limits (enforced on the server)
    max_users = models.PositiveIntegerField(default=10, help_text="Active users allowed.")
    max_websites = models.PositiveIntegerField(default=1)
    storage_mb = models.PositiveIntegerField(default=1024)
    ai_credits_monthly = models.PositiveIntegerField(default=0)
    api_calls_monthly = models.PositiveIntegerField(default=10000)

    suspension_reason = models.CharField(max_length=300, blank=True)
    status_before_suspension = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant__name"]

    def __str__(self) -> str:
        return f"{self.tenant.name}: {self.plan_name}"

    def period_end(self):
        """When the current trial or paid period ends (None = no end)."""
        if self.tenant.status == "trial":
            return self.trial_ends_at
        return self.ends_at

    def grace_ends_at(self):
        end = self.period_end()
        return end + timedelta(days=self.grace_days) if end else None

    def state(self, now=None) -> str:
        now = now or timezone.now()
        status = self.tenant.status
        if status == "suspended":
            return "suspended"
        if status == "cancelled":
            return "cancelled"
        end = self.period_end()
        if end is None or now < end:
            return "trial" if status == "trial" else "active"
        if now < self.grace_ends_at():
            return "grace"
        return "expired"


class TenantModule(models.Model):
    """
    entitled: the platform allows this business to use the module (licence).
    enabled:  the business's admin has switched it on (only possible if entitled).
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="modules")
    module = models.CharField(max_length=50)
    entitled = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "module"], name="unique_tenant_module")]
        ordering = ["module"]

    def __str__(self) -> str:
        return f"{self.tenant.schema_name}: {self.module} ({'on' if self.is_active else 'off'})"

    @property
    def is_active(self) -> bool:
        return self.entitled and self.enabled
