"""
Web addresses of businesses (task 1.12).

Every business gets a free subdomain of the platform domain, for example
`gorkhabutchery.<PLATFORM_DOMAIN>`. A business can have a few subdomains;
one is the main address. The others send visitors to the main address
(see apps.tenants.middleware), so links in old emails, posters and the
WhatsApp webhook keep working after a change.

Custom domains (for example `gorkhabutchery.co.nz`) come in Step 2. They need
a DNS ownership check and HTTPS certificates first.

Only the Super Admin changes addresses in Step 1. Every change is written to
the platform audit log and to the business's own audit log.
"""
from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit, platform_actor

from .models import Domain, Tenant

# One DNS label: letters, digits and hyphens, no hyphen at either end.
LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
MAX_SUBDOMAINS = 5

# Names kept for the platform itself, or that look official or confusing.
RESERVED_LABELS = frozenset({
    "public", "www", "admin", "administrator", "api", "app", "apps", "static", "media", "assets", "cdn",
    "mail", "email", "smtp", "imap", "pop", "ftp", "ns", "ns1", "ns2", "dns", "mx",
    "support", "help", "helpdesk", "docs", "status", "blog", "news", "shop", "store",
    "platform", "login", "logout", "signin", "signup", "auth", "account", "accounts", "sso", "oauth",
    "billing", "pay", "payment", "payments", "invoice", "secure", "security",
    "dev", "test", "staging", "demo", "sandbox", "beta", "preview", "localhost",
    "webhook", "webhooks", "whatsapp", "health", "system", "root", "superadmin", "anish1989",
})


def platform_domain() -> str:
    return settings.PLATFORM_DOMAIN.strip().lower().rstrip(".")


def subdomain_host(label: str) -> str:
    return f"{label}.{platform_domain()}"


def label_from_slug(slug: str) -> str:
    """Schema names use underscores; web addresses use hyphens."""
    return slug.replace("_", "-")


def is_platform_subdomain(host: str) -> bool:
    return host.endswith("." + platform_domain())


def normalise_label(label: str) -> str:
    label = (label or "").strip().lower()
    suffix = "." + platform_domain()
    if label.endswith(suffix):  # someone pasted the whole address
        label = label[: -len(suffix)]
    return label


def validate_label(label: str) -> str:
    """Check one subdomain label and return it in its normal form."""
    label = normalise_label(label)
    if "." in label:
        raise ValidationError("Use one name without dots, for example gorkha-butchery.")
    if not LABEL_PATTERN.match(label):
        raise ValidationError(
            "A web address name must be 3 to 63 characters: lowercase letters, numbers and hyphens, "
            "starting and ending with a letter or number. Example: gorkha-butchery."
        )
    if label[2:4] == "--":
        raise ValidationError("Names with two hyphens in the 3rd and 4th place are not allowed (they are used for special characters).")
    if label.isdigit():
        raise ValidationError("A web address name cannot be only numbers.")
    if label in RESERVED_LABELS:
        raise ValidationError(f"'{label}' is kept for the platform. Choose another name.")
    if Domain.objects.filter(domain__iexact=subdomain_host(label)).exists():
        raise ValidationError(f"{subdomain_host(label)} is already used by a business.")
    return label


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
def site_url(host: str, request=None, path: str = "/") -> str:
    """
    Full link to `host`. HTTPS in production; on a laptop (DEBUG and plain
    HTTP) it keeps http and the port the request came in on, e.g. :8000.
    """
    secure = request is None or request.is_secure() or not settings.DEBUG
    port = ""
    if request is not None:
        request_host = request.get_host()
        if ":" in request_host:
            port = ":" + request_host.rsplit(":", 1)[1]
    return f"{'https' if secure else 'http'}://{host}{port}{path}"


def main_address(tenant) -> str:
    domain = tenant.get_primary_domain()
    return domain.domain if domain else ""


def addresses(tenant) -> list[Domain]:
    return list(Domain.objects.filter(tenant=tenant).order_by("-is_primary", "domain"))


# ---------------------------------------------------------------------------
# Changes (Super Admin)
# ---------------------------------------------------------------------------
def _check_business(tenant) -> None:
    if tenant.schema_name == get_public_schema_name():
        raise ValidationError(
            "The platform's own address cannot be changed here. Use the change_platform_domain command."
        )


def _record(action: str, tenant, *, actor=None, request=None, **metadata) -> None:
    """Write to the platform audit log, and to the business's own audit log."""
    audit(action, target=tenant, actor=actor, request=request, metadata={"business": tenant.schema_name, **metadata})
    email = getattr(actor, "email", "") or "system"
    with schema_context(tenant.schema_name), platform_actor(email):
        audit(action, target_type="tenants.domain", target_repr=metadata.get("address", ""), request=request, metadata=metadata)


@transaction.atomic
def add_subdomain(tenant, label: str, *, make_main: bool = False, actor=None, request=None) -> Domain:
    _check_business(tenant)
    Tenant.objects.select_for_update().filter(pk=tenant.pk).first()  # one change at a time per business
    label = validate_label(label)
    if Domain.objects.filter(tenant=tenant).count() >= MAX_SUBDOMAINS:
        raise ValidationError(f"A business can have up to {MAX_SUBDOMAINS} web addresses. Remove one first.")
    # is_primary must be set on purpose: the library makes a new domain the main one by default.
    domain = Domain(tenant=tenant, domain=subdomain_host(label), is_primary=make_main)
    domain.save()
    _record("tenant.address_added", tenant, actor=actor, request=request, address=domain.domain, main=domain.is_primary)
    return domain


@transaction.atomic
def make_main(domain: Domain, *, actor=None, request=None) -> Domain:
    tenant = domain.tenant
    _check_business(tenant)
    if domain.is_primary:
        return domain
    previous = main_address(tenant)
    domain.is_primary = True
    domain.save()  # the library clears is_primary on the business's other addresses
    _record("tenant.main_address_changed", tenant, actor=actor, request=request, address=domain.domain, previous=previous)
    return domain


@transaction.atomic
def remove(domain: Domain, *, actor=None, request=None) -> None:
    tenant = domain.tenant
    _check_business(tenant)
    if domain.is_primary:
        raise ValidationError("The main address cannot be removed. Make another address the main one first.")
    address = domain.domain
    domain.delete()
    _record("tenant.address_removed", tenant, actor=actor, request=request, address=address)


# ---------------------------------------------------------------------------
# Moving the whole platform (laptop -> real domain)
# ---------------------------------------------------------------------------
def platform_domain_changes(old: str, new: str) -> list[tuple[Domain, str]]:
    """Every address that changes when the platform moves from `old` to `new`."""
    old, new = old.strip().lower().rstrip("."), new.strip().lower().rstrip(".")
    changes = []
    for domain in Domain.objects.select_related("tenant").order_by("domain"):
        if domain.domain == old:
            changes.append((domain, new))
        elif domain.domain.endswith("." + old):
            changes.append((domain, domain.domain[: -len(old)] + new))
    return changes


@transaction.atomic
def change_platform_domain(old: str, new: str) -> list[tuple[str, str]]:
    changes = platform_domain_changes(old, new)
    targets = [target for _, target in changes]
    clash = Domain.objects.filter(domain__in=targets).exclude(pk__in=[d.pk for d, _ in changes]).values_list("domain", flat=True)
    if clash:
        raise ValidationError(f"These addresses already exist: {', '.join(sorted(clash))}")
    done = []
    for domain, target in changes:
        done.append((domain.domain, target))
        Domain.objects.filter(pk=domain.pk).update(domain=target)
    audit("platform.domain_changed", target_type="tenants.domain", target_repr=f"{old} -> {new}", metadata={"old": old, "new": new, "addresses": len(done)})
    return done
