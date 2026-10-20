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
