"""
Running the checks, saving the history, and alerting admins when a scheduled
run turns red.
"""
from __future__ import annotations

import logging
from collections import Counter

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_public_schema_name

from apps.audit.services import audit

from . import checks
from .models import CheckRun

log = logging.getLogger(__name__)
BUTTON_COOLDOWN_SECONDS = 60
HISTORY_KEEP = 500


def on_platform() -> bool:
    return connection.schema_name == get_public_schema_name()


def current_tenant():
    from apps.tenants.models import Tenant

    tenant = getattr(connection, "tenant", None)
    if isinstance(tenant, Tenant):
        return tenant
    return Tenant.objects.filter(schema_name=connection.schema_name).first()


def run(trigger: str, *, user=None, live: bool = True) -> CheckRun:
    """Run the checks for the current schema (platform or one business) and save the run."""
    if trigger == CheckRun.Trigger.BUTTON:
        # One run a minute per site: each run tests every saved connection with the providers.
        if not cache.add("health:button", "1", timeout=BUTTON_COOLDOWN_SECONDS):
            raise ValidationError("The checks ran less than a minute ago. Wait a moment and try again.")
    started = timezone.now()
    results = checks.platform_checks(live=live) if on_platform() else checks.business_checks(current_tenant(), live=live)
    status = checks.overall(results)
    counts = dict(Counter(r.status for r in results))
    previous = CheckRun.objects.order_by("-started_at", "-id").first()
    record = CheckRun.objects.create(
        started_at=started, finished_at=timezone.now(), trigger=trigger,
        run_by_email=getattr(user, "email", "") or "", status=status, counts=counts,
        results=[r.as_dict() for r in results],
    )
    audit("system_check.run", target_type="health.checkrun", target_id=str(record.pk), target_repr=f"Check system: {status}",
          actor=user, outcome="success" if status != checks.FAILED else "failed",
          metadata={"trigger": trigger, "counts": counts})
    if trigger == CheckRun.Trigger.SCHEDULE and status == checks.FAILED and (previous is None or previous.status != checks.FAILED):
        record.alert_sent = send_alert(record)
        record.save(update_fields=["alert_sent"])
    if trigger == CheckRun.Trigger.SCHEDULE and status == checks.FAILED:
        _ticket(record)
    _trim_history()
    return record


def _ticket(record: CheckRun) -> None:
    """One open ticket while the scheduled checks stay red (task 1.15)."""
    from apps.tickets.services import system_ticket

    red = [r for r in record.results if r["status"] == checks.FAILED]
    lines = "\n".join(f"- {r['area']} / {r['label']}: {r['message']}" for r in red)
    try:
        system_ticket(source="check", key="check:scheduled", title=f"Check system: {len(red)} failed check(s)",
                      description=f"The automatic check at {timezone.localtime(record.started_at):%H:%M on %d %b %Y} found:\n\n{lines}")
    except Exception:  # noqa: BLE001 - a ticket problem must not break the checks
        log.exception("Could not create a ticket for a failed check")


def _trim_history() -> None:
    old = CheckRun.objects.order_by("-started_at", "-id").values_list("pk", flat=True)[HISTORY_KEEP:]
    ids = list(old)
    if ids:
        CheckRun.objects.filter(pk__in=ids).delete()


def alert_recipients() -> list[str]:
    """Platform: active Super Admins. Business: active System Admins and IT Admins."""
    from apps.accounts.models import User
    from apps.rbac.models import UserRole

    slugs = ["super_admin"] if on_platform() else ["system_admin", "it_admin"]
    ids = set(UserRole.objects.filter(role__slug__in=slugs).values_list("user_id", flat=True))
    users = User.objects.filter(is_active=True).filter(pk__in=ids)
    if on_platform():
        users = users | User.objects.filter(is_active=True, is_superuser=True)
    return sorted({u.email for u in users if u.email})


def send_alert(record: CheckRun) -> bool:
    recipients = alert_recipients()
    if not recipients:
        return False
    tenant = current_tenant()
    where = "the platform" if on_platform() else tenant.name
    red = [r for r in record.results if r["status"] == checks.FAILED]
    lines = [f"- {r['label']}: {r['message']}" for r in red]
    from apps.tenants.domains import main_address, site_url

    link = site_url(main_address(tenant), None, "/system-check/") if tenant else ""
    body = (
        f"The automatic system check of {where} found {len(red)} problem(s) "
        f"at {timezone.localtime(record.started_at):%H:%M on %d %b %Y}:\n\n" + "\n".join(lines)
        + f"\n\nOpen the results: {link}\n\nYou get this email when the check turns red. It is not sent again until the problem is fixed."
    )
    try:
        send_mail(f"System check failed: {where}", body, None, recipients)
    except Exception:  # noqa: BLE001 - the alert must not break the run
        log.exception("System check alert email could not be sent")
        audit("system_check.alert_failed", target_type="health.checkrun", target_id=str(record.pk), outcome="failed")
        return False
    audit("system_check.alert_sent", target_type="health.checkrun", target_id=str(record.pk), metadata={"recipients": len(recipients)})
    return True


def grouped(results: list[dict]) -> list[tuple[str, list[dict]]]:
    """Results grouped by area, keeping the order of the checks."""
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(r["area"], []).append({**r, "status_label": checks.STATUS_LABELS.get(r["status"], r["status"])})
    return list(groups.items())


def run_everywhere(trigger: str = CheckRun.Trigger.SCHEDULE) -> dict:
    """
    Every business that may use the system (not suspended or expired), then
    the platform (whose checks include each business's latest result).
    """
    from django_tenants.utils import schema_context

    from apps.licensing.services import access_state, is_access_allowed

    summary = {}
    with schema_context(get_public_schema_name()):
        tenants = list(checks.businesses())
    for tenant in tenants:
        if not is_access_allowed(tenant):
            summary[tenant.schema_name] = f"skipped ({access_state(tenant)})"
            continue
        with schema_context(tenant.schema_name):
            try:
                summary[tenant.schema_name] = run(trigger).status
            except Exception:  # noqa: BLE001 - one business must not stop the others
                log.exception("Scheduled system check failed for %s", tenant.schema_name)
                summary[tenant.schema_name] = "error"
    with schema_context(get_public_schema_name()):
        summary["public"] = run(trigger).status
    return summary
