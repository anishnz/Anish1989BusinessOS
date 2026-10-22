"""
A business's own domain (task 2.8, D-159 to D-163).

1. A business admin (Settings – Configure) adds a name, for example
   gorkhabutchery.co.nz. It gets a secret code.
2. The business adds two DNS records at its domain company:
   - TXT  _anish1989-verify.<name>  =  anish1989-verify=<code>   (proves it is theirs)
   - A record to the server's IP address (for example gorkhabutchery.co.nz),
     or a CNAME to the business's platform address (for example
     shop.gorkhabutchery.co.nz -> gorkhabutchery.<platform>).
3. The DNS check (every hour while waiting, then daily, and the "Check now"
   button) finds both: the domain is live. A Domain row is made, so it opens
   the business, and Caddy may get an HTTPS certificate for it (and for
   www.<name>). The admin can then make it the main address.
4. Once live, a failed check (the domain no longer points to the server)
   emails the business admins at once. After 3 days of failures, the
   platform address becomes the main address again (the custom domain stays,
   and works again when the DNS is fixed).

Names are stored without www. The routing (apps.tenants.middleware) treats
www.<name> as <name>.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from . import domains
from .models import CustomDomain, Domain

log = logging.getLogger(__name__)
C = CustomDomain.Status
MAX_PER_BUSINESS = 3
FALL_BACK_AFTER = timedelta(days=3)
CHECK_PENDING_EVERY = timedelta(hours=1)
PENDING_HOURLY_FOR = timedelta(days=7)  # after a week of waiting, check once a day
CHECK_LIVE_EVERY = timedelta(days=1)
CHECK_FAILING_EVERY = timedelta(hours=1)
LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
BLOCKED_ENDINGS = (".localhost", ".local", ".internal", ".invalid", ".test", ".arpa")


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
def normalise(name: str) -> str:
    """'https://WWW.Gorkha.co.nz/menu' -> 'gorkha.co.nz' (international names in their xn-- form)."""
    name = (name or "").strip().lower()
    name = re.sub(r"^[a-z]+://", "", name).split("/")[0].split("?")[0].split("#")[0]
    name = name.split("@")[-1].split(":")[0].rstrip(".")
    if name.startswith("www."):
        name = name[4:]
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValidationError("This is not a valid domain name.") from None
    return name


def validate(name: str) -> str:
    name = normalise(name)
    try:
        ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        raise ValidationError("Type a domain name, not an IP address.")
    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or not all(LABEL.match(part) for part in labels) or not TLD.match(labels[-1]):
        raise ValidationError("Type a domain name such as gorkhabutchery.co.nz.")
    platform = domains.platform_domain()
    if name == platform or name.endswith("." + platform):
        raise ValidationError(f"Addresses ending in {platform} are platform addresses. Ask the Super Admin for those.")
    if name == "localhost" or name.endswith(BLOCKED_ENDINGS):
        raise ValidationError("This name cannot be used on the internet.")
    if CustomDomain.objects.filter(name=name).exists() or Domain.objects.filter(domain=name).exists():
        raise ValidationError(f"{name} is already used by a business.")
    return name


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------
def lookup(name: str, kind: str) -> list[str]:
    """DNS answers for one name and record type ([] when there are none). Tests replace this."""
    import dns.exception
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5
    try:
        answer = resolver.resolve(name, kind)
    except dns.exception.DNSException:  # no such name, no answer, timeout, no DNS server reachable
        return []
    if kind == "TXT":
        return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]
    return [r.to_text().rstrip(".").lower() for r in answer]


def server_ips() -> set[str]:
    configured = {ip.strip() for ip in getattr(settings, "PLATFORM_SERVER_IPS", []) if ip.strip()}
    return configured or set(lookup(domains.platform_domain(), "A")) | set(lookup(domains.platform_domain(), "AAAA"))


def check_dns(cd: CustomDomain) -> dict:
    """What the DNS says: {"txt": bool, "points": bool, "found": [...], "expected": [...], "message": str}."""
    txt = any(value.strip() == cd.txt_value for value in lookup(cd.txt_name, "TXT"))
    found = set(lookup(cd.name, "A")) | set(lookup(cd.name, "AAAA"))
    expected = server_ips()
    points = bool(found) and bool(expected) and found <= expected
    if not expected:
        message = "The platform's own address could not be found in DNS. Tell the Super Admin."
    elif not found:
        message = f"{cd.name} does not point anywhere yet."
    elif not points:
        message = f"{cd.name} points to {', '.join(sorted(found))}, not to {', '.join(sorted(expected))}."
    else:
        message = f"{cd.name} points to the platform."
    if cd.status == C.PENDING:
        message += " The TXT code was found." if txt else " The TXT code was not found yet."
    return {"txt": txt, "points": points, "found": sorted(found), "expected": sorted(expected), "message": message}


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def _record(action: str, cd: CustomDomain | None, *, tenant=None, name: str = "", actor=None, request=None, by_business: bool = False,
            **metadata) -> None:
    """
    Write to the platform audit log and the business's audit log. `by_business`: a business admin did it
    (their user lives in the business, so the platform log keeps only their email); otherwise the Super
    Admin (or the scheduled check when there is no actor).
    """
    from apps.audit.models import AuditEvent
    from apps.audit.services import audit, platform_actor

    tenant = tenant or cd.tenant
    name = name or cd.name
    meta = {"business": tenant.schema_name, "address": name, **metadata}
    email = getattr(actor, "email", "") or ""
    with schema_context(get_public_schema_name()):
        if by_business:
            audit(action, target=tenant, metadata=meta, actor_type=AuditEvent.ActorType.USER, actor_email=email, actor_elsewhere=True)
        else:
            audit(action, target=tenant, actor=actor, request=request, metadata=meta)
    with schema_context(tenant.schema_name):
        if by_business or actor is None:
            audit(action, target_type="tenants.customdomain", target_repr=name, actor=actor, request=request if by_business else None, metadata=meta)
        else:
            with platform_actor(email):
                audit(action, target_type="tenants.customdomain", target_repr=name, request=request, metadata=meta)


@transaction.atomic
def add(tenant, name: str, *, actor=None, request=None, by_business: bool = False) -> CustomDomain:
    from .models import Tenant

    domains._check_business(tenant)
    Tenant.objects.select_for_update().filter(pk=tenant.pk).first()  # one change at a time per business
    name = validate(name)
    if CustomDomain.objects.filter(tenant=tenant).count() >= MAX_PER_BUSINESS:
        raise ValidationError(f"A business can have up to {MAX_PER_BUSINESS} own domains. Remove one first.")
    cd = CustomDomain.objects.create(tenant=tenant, name=name, token=secrets.token_hex(16), added_by=getattr(actor, "email", "") or "")
    _record("tenant.custom_domain_added", cd, actor=actor, request=request, by_business=by_business)
    return cd


def check(cd: CustomDomain, *, now=None, actor=None, by_business: bool = False) -> CustomDomain:
    """Look at the DNS now and move the domain on (live, problem, back to the platform address)."""
    now = now or timezone.now()
    result = check_dns(cd)
    with transaction.atomic():
        cd = CustomDomain.objects.select_for_update(of=("self",)).select_related("tenant", "domain").get(pk=cd.pk)
        cd.last_checked_at, cd.last_result = now, result["message"][:500]
        if cd.status == C.PENDING:
            if result["txt"] and result["points"]:
                _go_live(cd, now, actor, by_business)
        elif result["points"]:
            if cd.status == C.FAILING:
                cd.status, cd.failing_since = C.LIVE, None
                _record("tenant.custom_domain_working", cd, actor=actor, by_business=by_business)
                _tell(cd, "works again", f"{cd.name} points to the platform again and opens your business."
                      + (" You can make it the main address again on the Web addresses page." if cd.fell_back_at else ""))
        else:
            if cd.status == C.LIVE:
                cd.status, cd.failing_since = C.FAILING, now
                _record("tenant.custom_domain_failing", cd, actor=actor, by_business=by_business, result=cd.last_result)
                _tell(cd, "does not point to us", f"{cd.last_result}\n\nFix the DNS records at your domain company. "
                      f"If it is not fixed within 3 days and {cd.name} is your main address, the platform address becomes the main address again.")
            elif cd.failing_since and now - cd.failing_since >= FALL_BACK_AFTER and not cd.fell_back_at:
                _fall_back(cd, now)
        cd.save()
    return cd


def _go_live(cd: CustomDomain, now, actor, by_business: bool) -> None:
    domain = Domain(tenant=cd.tenant, domain=cd.name, is_primary=False)
    domain.save()
    cd.domain, cd.status, cd.verified_at = domain, C.LIVE, now
    _record("tenant.custom_domain_live", cd, actor=actor, by_business=by_business)
    _tell(cd, "is live", f"{cd.name} now opens your business (the HTTPS certificate is made on the first visit). "
          "To use it in emails and links, make it the main address on the Web addresses page.")


def _fall_back(cd: CustomDomain, now) -> None:
    """After 3 days of DNS problems: the platform address becomes the main address again."""
    cd.fell_back_at = now
    if cd.domain is not None and cd.domain.is_primary:
        platform = Domain.objects.filter(tenant=cd.tenant, custom__isnull=True).order_by("created_at").first()
        if platform is not None:
            domains.make_main(platform)
            _tell(cd, "is no longer the main address", f"{cd.name} has not pointed to the platform for 3 days, so {platform.domain} "
                  "is the main address again. When the DNS is fixed, you can make it the main address again.")
    _record("tenant.custom_domain_fell_back", cd)


@transaction.atomic
def make_main_by_business(domain: Domain, *, actor=None, request=None) -> Domain:
    """A business admin picks the main address (one of their own addresses)."""
    domains._check_business(domain.tenant)
    if domain.is_primary:
        return domain
    previous = domains.main_address(domain.tenant)
    domain.is_primary = True
    domain.save()  # the library clears is_primary on the business's other addresses
    _record("tenant.main_address_changed", None, tenant=domain.tenant, name=domain.domain, actor=actor, request=request,
            by_business=True, previous=previous)
    return domain


@transaction.atomic
def remove(cd: CustomDomain, *, actor=None, request=None, by_business: bool = False) -> None:
    cd = CustomDomain.objects.select_for_update(of=("self",)).select_related("tenant", "domain").get(pk=cd.pk)
    if cd.domain is not None and cd.domain.is_primary:
        raise ValidationError("This is the main address. Make another address the main one first.")
    if cd.domain is not None:
        cd.domain.delete()
    name = cd.name
    cd.delete()
    _record("tenant.custom_domain_removed", None, tenant=cd.tenant, name=name, actor=actor, request=request, by_business=by_business)


# ---------------------------------------------------------------------------
# The scheduled job and HTTPS
# ---------------------------------------------------------------------------
def due(now=None):
    """Domains whose next DNS check is due."""
    now = now or timezone.now()
    due_ids = []
    for cd in CustomDomain.objects.all():
        last = cd.last_checked_at
        if cd.status == C.PENDING:
            every = CHECK_PENDING_EVERY if now - cd.created_at < PENDING_HOURLY_FOR else CHECK_LIVE_EVERY
        elif cd.status == C.FAILING:
            every = CHECK_FAILING_EVERY
        else:
            every = CHECK_LIVE_EVERY
        if last is None or now - last >= every - timedelta(minutes=5):  # a little early, so the 15-minute job does not drift
            due_ids.append(cd.pk)
    return CustomDomain.objects.filter(pk__in=due_ids).select_related("tenant")


def check_due(now=None) -> dict:
    from apps.licensing.services import is_access_allowed

    counts = {}
    for cd in due(now):
        if not is_access_allowed(cd.tenant):
            continue
        try:
            status = check(cd, now=now).status
        except Exception:  # noqa: BLE001 - one domain must not stop the others
            log.exception("Custom domain check failed for %s", cd.name)
            status = "error"
        counts[status] = counts.get(status, 0) + 1
    return counts


def tls_allowed(host: str) -> bool:
    """May Caddy get a certificate for this host name? Only addresses that open a business (or the platform)."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or len(host) > 253:
        return False
    bare = host[4:] if host.startswith("www.") else host
    # An own domain has a Domain row only while it is live (or live with a DNS problem).
    return Domain.objects.filter(domain=bare).exists()


def is_live(host: str) -> bool:
    """Is this host a business's own domain that may open the business (live, or live with a DNS problem)?"""
    host = (host or "").strip().lower().rstrip(".")
    bare = host[4:] if host.startswith("www.") else host
    return Domain.objects.filter(domain=bare, custom__isnull=False).exists()  # the routing row exists only once it went live


def _tell(cd: CustomDomain, what: str, body: str) -> None:
    """Email the business's admins (Settings – Configure) about their domain."""
    from django.core.mail import send_mail

    from apps.accounts.models import User
    from apps.rbac import policy

    try:
        with schema_context(cd.tenant.schema_name):
            recipients = sorted({u.email for u in User.objects.filter(is_active=True, is_staff=True).exclude(email="")
                                 if policy.has_perm(u, "settings.configure")})
        if recipients:
            send_mail(f"Your domain {cd.name} {what}", body, None, recipients)
    except Exception:  # noqa: BLE001 - an email must not stop the check
        log.exception("Could not email about %s", cd.name)
