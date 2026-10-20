"""Business logic for creating tenants. Used by management commands and tests."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Domain, Tenant

# Lowercase letter first, then letters, digits or underscores. 3 to 40 characters.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
RESERVED_SLUGS = {"public", "www", "admin", "api", "app", "static", "media", "mail", "support", "help"}


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_PATTERN.match(slug):
        raise ValidationError(
            "Slug must be 3 to 40 characters, start with a letter, and use only "
            "lowercase letters, numbers and underscores."
        )
    if slug in RESERVED_SLUGS or slug.startswith("pg_"):
        raise ValidationError(f"'{slug}' is reserved. Choose another slug.")
    return slug


def subdomain_for(slug: str) -> str:
    """Subdomains use hyphens, schema names use underscores."""
    return f"{slug.replace('_', '-')}.{settings.PLATFORM_DOMAIN}"


@transaction.atomic
def create_public_tenant(domain: str | None = None) -> Tenant:
    """Create (or return) the platform tenant that owns the public schema."""
    domain = domain or settings.PLATFORM_DOMAIN
    tenant, _ = Tenant.objects.get_or_create(
        schema_name=settings.PUBLIC_SCHEMA_NAME,
        defaults={
            "name": "Anish1989 Business OS (platform)",
            "status": Tenant.Status.ACTIVE,
            "industry": Tenant.Industry.PLATFORM,
        },
    )
    Domain.objects.get_or_create(domain=domain, defaults={"tenant": tenant, "is_primary": True})
    return tenant


def create_tenant(name: str, slug: str, industry: str = Tenant.Industry.OTHER) -> Tenant:
    """Create a business tenant, its schema, and its platform subdomain."""
    slug = validate_slug(slug)
    if industry not in Tenant.Industry.values or industry == Tenant.Industry.PLATFORM:
        raise ValidationError(f"Unknown industry '{industry}'.")
    if Tenant.objects.filter(schema_name=slug).exists():
        raise ValidationError(f"A tenant with slug '{slug}' already exists.")

    # Saving the tenant creates the schema and runs tenant migrations.
    tenant = Tenant(schema_name=slug, name=name.strip(), industry=industry)
    tenant.save()
    Domain.objects.create(domain=subdomain_for(slug), tenant=tenant, is_primary=True)
    return tenant
