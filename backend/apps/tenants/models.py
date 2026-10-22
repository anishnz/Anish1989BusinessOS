"""
Tenants (businesses) and their domains.

These tables live in the `public` schema. Each Tenant row owns one
PostgreSQL schema that holds that business's own data.
"""
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(TenantMixin):
    class Status(models.TextChoices):
        TRIAL = "trial", "Trial"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CANCELLED = "cancelled", "Cancelled"

    class Industry(models.TextChoices):
        PLATFORM = "platform", "Platform (public schema)"
        BUTCHERY = "butchery", "Butchery / meat shop"
        RESTAURANT = "restaurant", "Restaurant"
        FAST_FOOD = "fast_food", "Small fast-food restaurant"
        CATERING = "catering", "Catering"
        EVENTS = "events", "Events"
        RETAIL = "retail", "Retail shop"
        SERVICES = "services", "Service business"
        EDUCATION_CONSULTANCY = "education_consultancy", "Education consultancy"
        E_LEARNING = "e_learning", "Education / e-learning platform"
        JOBS = "jobs", "Job platform"
        OTHER = "other", "Other"

    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    industry = models.CharField(max_length=40, choices=Industry.choices, default=Industry.OTHER)
    is_test = models.BooleanField(
        "Test business", default=False, editable=False,
        help_text="Made by “Install test data” (made-up data). Only test businesses can be removed with “Remove test data”.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Create the PostgreSQL schema automatically when a tenant is saved.
    auto_create_schema = True
    # Never drop a schema automatically when a tenant row is deleted.
    # Tenant deletion must go through an explicit, audited offboarding process.
    auto_drop_schema = False

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.schema_name})"

    @property
    def is_public(self) -> bool:
        from django.conf import settings

        return self.schema_name == settings.PUBLIC_SCHEMA_NAME


class Domain(DomainMixin):
    """A host name (subdomain or custom domain) that points to one tenant."""

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.domain


class CustomDomain(models.Model):
    """
    A business's own domain, for example gorkhabutchery.co.nz (task 2.8,
    D-159 to D-163). It only opens the business (a Domain row) once the DNS
    check found the TXT code and the domain points to the platform.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for DNS"
        LIVE = "live", "Live"
        FAILING = "failing", "DNS problem"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="custom_domains")
    name = models.CharField(max_length=253, unique=True, help_text="Without www. Both the name and www.name work.")
    token = models.CharField(max_length=40, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    domain = models.OneToOneField(Domain, null=True, blank=True, on_delete=models.SET_NULL, related_name="custom",
                                  help_text="The address row that routes visitors, once the domain is live.")
    added_by = models.CharField(max_length=254, blank=True)
    last_result = models.CharField(max_length=500, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    failing_since = models.DateTimeField(null=True, blank=True)
    fell_back_at = models.DateTimeField(null=True, blank=True, help_text="When the platform address became the main address again.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def txt_name(self) -> str:
        return f"_anish1989-verify.{self.name}"

    @property
    def txt_value(self) -> str:
        return f"anish1989-verify={self.token}"
