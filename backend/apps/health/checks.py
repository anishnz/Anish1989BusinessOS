"""
The checks behind the "Check system" button (task 1.13).

Every check is safe: it reads, or tests a connection with a read-only call.
It never sends messages, charges money or changes business data. (Testing a
saved connection updates that connection's "Connected / Failed" status, the
same as the Test button on the Integrations page.)

A check returns a Result with one of four states:
  ok          green, works
  warning     amber, works but needs attention
  failed      red, broken
  not_set_up  grey, not set up yet (does not change the overall result)

Messages are written for business owners. They never contain secrets,
host names or error details: those go to the server log only.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

log = logging.getLogger(__name__)

OK, WARNING, FAILED, NOT_SET_UP = "ok", "warning", "failed", "not_set_up"
STATUS_LABELS = {OK: "OK", WARNING: "Needs attention", FAILED: "Failed", NOT_SET_UP: "Not set up"}

HEARTBEAT_KEY = "health:heartbeat"  # written by the scheduled heartbeat task (no tenant prefix: see tasks.py)
HEARTBEAT_LATE = timedelta(minutes=15)
TRIAL_WARNING = timedelta(days=7)
DISK_WARNING, DISK_FAILED = 0.15, 0.05  # share of free space
WORKER_PING_SECONDS = 1.5


@dataclass
class Result:
    code: str
    area: str
    label: str
    status: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def overall(results: list[Result]) -> str:
    states = {r.status for r in results}
    if FAILED in states:
        return FAILED
    if WARNING in states:
        return WARNING
    return OK


def _safe(code: str, area: str, label: str, func) -> list[Result]:
    """Run one check; an unexpected error becomes a red result with a plain message."""
    try:
        found = func()
        return found if isinstance(found, list) else [found]
    except Exception:  # noqa: BLE001 - details go to the log only
        log.exception("System check %s failed with an error", code)
        return [Result(code, area, label, FAILED, "The check itself stopped with an error. Details are in the server log.")]


def _ago(moment) -> str:
    seconds = int((timezone.now() - moment).total_seconds())
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        n, unit = round(seconds / 60), "minute"
    elif seconds < 36 * 3600:
        n, unit = round(seconds / 3600), "hour"
    else:
        n, unit = seconds // 86400, "day"
    return f"{n} {unit}{'' if n == 1 else 's'} ago"


# ---------------------------------------------------------------------------
# System (both sites)
# ---------------------------------------------------------------------------
def unapplied_migrations() -> int:
    executor = MigrationExecutor(connection)
    return len(executor.migration_plan(executor.loader.graph.leaf_nodes()))


def check_database() -> Result:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    missing = unapplied_migrations()
    if missing:
        return Result("database", "System", "Database", FAILED,
                      f"The database works, but {missing} update(s) were not applied. Restart the platform, or ask support to run the updates.")
    return Result("database", "System", "Database", OK, "Works and is up to date.")


def check_cache() -> Result:
    key = f"health:check:{uuid.uuid4().hex}"
    cache.set(key, "ok", timeout=10)
    ok = cache.get(key) == "ok"
    cache.delete(key)
    if not ok:
        return Result("cache", "System", "Cache (Redis)", FAILED, "Cannot save and read back a test value. Sign-in limits and background jobs need it.")
    return Result("cache", "System", "Cache (Redis)", OK, "Works.")


def ping_workers() -> int:
    """Number of background workers that answer (0 if none)."""
    from config.celery import app

    replies = app.control.ping(timeout=WORKER_PING_SECONDS) or []
    return len(replies)


def check_workers() -> Result:
    label = "Background jobs (worker)"
    try:
        workers = ping_workers()
    except Exception:  # noqa: BLE001 - broker down etc.
        log.exception("System check: worker ping failed")
        workers = 0
    if not workers:
        return Result("workers", "System", label, WARNING,
                      "No background worker answered. Scheduled checks, reminders and backups will not run. Start the worker service.")
    return Result("workers", "System", label, OK, f"{workers} worker(s) answered.")


def _local_date(moment) -> str:
    moment = timezone.localtime(moment)
    return f"{moment.day} {moment:%B %Y}"


def last_heartbeat():
    # Cache keys get the current schema as a prefix; the heartbeat is always kept under the platform's.
    with schema_context(get_public_schema_name()):
        value = cache.get(HEARTBEAT_KEY)
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check_scheduler() -> Result:
    label = "Scheduled jobs"
    beat = last_heartbeat()
    if beat is None:
        return Result("scheduler", "System", label, WARNING,
                      "No scheduled job has run yet. Check that the scheduler and worker services are running.")
    if timezone.now() - beat > HEARTBEAT_LATE:
        return Result("scheduler", "System", label, WARNING, f"The last scheduled job ran {_ago(beat)}. Check the scheduler and worker services.")
    return Result("scheduler", "System", label, OK, f"Last scheduled job ran {_ago(beat)}.")


def check_audit_chain() -> Result:
    from apps.audit.services import verify_chain

    ok, problems = verify_chain()
    if not ok:
        return Result("audit", "Security", "Audit log", FAILED,
                      f"The audit log was changed or has gaps ({len(problems)} problem(s)). Contact support now.")
    return Result("audit", "Security", "Audit log", OK, "Complete and unchanged.")


def check_staff_mfa(label: str = "Two-step verification") -> Result:
    from apps.accounts import security
    from apps.accounts.models import User

    staff = list(User.objects.filter(is_active=True, is_staff=True))
    states = [security.mfa_status(u) for u in staff]
    off, not_set = states.count("off"), states.count("not_set_up")
    if off:
        return Result("mfa", "Security", label, WARNING,
                      f"{off} active staff account(s) have two-step verification switched off. A stolen password is enough to sign in to them.")
    if not_set:
        return Result("mfa", "Security", label, WARNING, f"{not_set} active staff account(s) have not set up two-step verification yet.")
    if not staff:
        return Result("mfa", "Security", label, OK, "No active staff accounts yet.")
    return Result("mfa", "Security", label, OK, f"On for all {len(staff)} active staff account(s).")


def check_backups() -> list[Result]:
    from apps.backups.checks import results

    return results()


# ---------------------------------------------------------------------------
# Saved connections (API keys)
# ---------------------------------------------------------------------------
def _test_one(provider_test, secrets, config):
    try:
        return provider_test(secrets, config)
    except Exception:  # noqa: BLE001
        log.exception("System check: connection test crashed")
        from apps.vault.providers import TestResult

        return TestResult(False, "The test stopped with an error.")


def test_connections(live: bool = True) -> list[Result]:
    """
    Test every saved connection of the current schema at the same time (each
    test has a 10-second limit). Updates each connection's status like the
    Test button, but writes an audit entry only when the status changes.
    """
    from apps.audit.services import audit
    from apps.vault import crypto, providers, services
    from apps.vault.models import Connection

    results, jobs = [], []
    for conn in Connection.objects.all().order_by("category", "is_backup", "label"):
        label = f"{conn.label} ({providers.get(conn.provider).label})" if conn.provider in providers.PROVIDERS else conn.label
        if conn.status == Connection.Status.DISABLED:
            results.append((conn, Result(f"connection:{conn.pk}", "Connections", label, NOT_SET_UP, "Disabled.")))
            continue
        provider = providers.PROVIDERS.get(conn.provider)
        if provider is None or provider.test is None:
            results.append((conn, Result(f"connection:{conn.pk}", "Connections", label, NOT_SET_UP, "This provider cannot be tested yet.")))
            continue
        try:
            secrets = services.read_secrets(conn)
        except crypto.VaultError:
            results.append((conn, Result(f"connection:{conn.pk}", "Connections", label, FAILED,
                                         "The saved key cannot be opened (the vault master key changed?). Save the key again.")))
            continue
        jobs.append((conn, label, provider.test, secrets))

    if jobs and live:
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
            outcomes = list(pool.map(lambda job: _test_one(job[2], job[3], job[0].config), jobs))
        now = timezone.now()
        for (conn, label, _, _), outcome in zip(jobs, outcomes):
            new_status = Connection.Status.CONNECTED if outcome.ok else Connection.Status.FAILED
            changed = new_status != conn.status
            Connection.objects.filter(pk=conn.pk).update(status=new_status, last_tested_at=now, last_test_message=outcome.message)
            if changed:
                audit("integration.status_changed", target=conn, outcome="success" if outcome.ok else "failed",
                      metadata={"from": conn.status, "to": new_status, "by": "system check", "message": outcome.message})
            results.append((conn, Result(f"connection:{conn.pk}", "Connections", label, OK if outcome.ok else FAILED, outcome.message)))

    order = {c.pk: i for i, c in enumerate(Connection.objects.all().order_by("category", "is_backup", "label"))}
    return [r for _, r in sorted(results, key=lambda pair: order.get(pair[0].pk, 0))]


def _has_connection(category: str) -> bool:
    from apps.vault.models import Connection

    return Connection.objects.filter(category=category).exclude(status=Connection.Status.DISABLED).exists()


def platform_has_email() -> bool:
    with schema_context(get_public_schema_name()):
        return _has_connection("email")


def check_email() -> Result:
    label = "Email sending"
    if _has_connection("email"):
        return Result("email", "Connections", label, OK, "Uses this business's own email connection (tested above).")
    if platform_has_email():
        return Result("email", "Connections", label, OK, "Uses the platform's email connection.")
    if settings.DEBUG:
        return Result("email", "Connections", label, WARNING, "No email connection. In development, emails are only printed in the server log.")
    return Result("email", "Connections", label, WARNING,
                  "No email connection is saved. Password reset and invitation emails may not arrive. Add Gmail on the Integrations page.")


# ---------------------------------------------------------------------------
# Business checks
# ---------------------------------------------------------------------------
def check_licence(tenant) -> Result:
    from apps.licensing import services

    licence = getattr(tenant, "licence", None)
    if licence is None:
        return Result("licence", "Business", "Licence", FAILED, "No licence. Contact Anish1989 Business OS.")
    state = services.access_state(tenant)
    end = licence.period_end()
    if state == "grace":
        return Result("licence", "Business", "Licence", WARNING,
                      f"The licence period has ended. Access stops on {_local_date(licence.grace_ends_at())}. Contact Anish1989 Business OS.")
    if state in ("expired", "suspended", "cancelled", "unlicensed"):
        return Result("licence", "Business", "Licence", FAILED, f"The licence is {state}.")
    if end is not None and end - timezone.now() < TRIAL_WARNING:
        kind = "trial" if state == "trial" else "licence"
        return Result("licence", "Business", "Licence", WARNING, f"The {kind} ends on {_local_date(end)}.")
    if end is None:
        return Result("licence", "Business", "Licence", OK, f"{licence.plan_name}: active, no end date.")
    if state == "trial":
        return Result("licence", "Business", "Licence", OK, f"Free trial until {_local_date(end)}.")
    return Result("licence", "Business", "Licence", OK, f"{licence.plan_name}: active until {_local_date(end)}.")


def check_web_address(tenant) -> Result:
    from apps.tenants.domains import main_address

    host = main_address(tenant)
    if not host:
        return Result("web_address", "Business", "Web address", FAILED, "This business has no main web address.")
    return Result("web_address", "Business", "Web address", OK, f"Main address: {host}")


def check_whatsapp() -> Result:
    from apps.inbox.models import WebhookDelivery
    from apps.vault.models import Connection

    label = "WhatsApp messages"
    if not Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).exists():
        return Result("whatsapp", "Connections", label, NOT_SET_UP, "WhatsApp is not connected.")
    last = WebhookDelivery.objects.filter(channel="whatsapp").order_by("-received_at").first()
    if last is None:
        return Result("whatsapp", "Connections", label, WARNING,
                      "No message from Meta has arrived yet. Check the webhook address in Meta (user guide chapter 7).")
    if not last.ok:
        return Result("whatsapp", "Connections", label, WARNING,
                      f"The last call from Meta ({_ago(last.received_at)}) was refused. Check the app secret and phone number ID.")
    return Result("whatsapp", "Connections", label, OK, f"Last call from Meta arrived {_ago(last.received_at)}.")


def check_fulfilment() -> list[Result]:
    """Can customers choose a pickup or delivery time? (task 2.1). Only when the Orders module is on."""
    from apps.fulfilment import services as fulfilment
    from apps.fulfilment.models import DeliveryArea, Kind, OpeningHours
    from apps.rbac.policy import module_enabled

    if not module_enabled("orders"):
        return []
    label = "Pickup and delivery"
    s = fulfilment.current_settings()
    if not s.pickup_enabled and not s.delivery_enabled:
        return [Result("fulfilment", "Business", label, WARNING, "Pickup and delivery are both switched off, so customers cannot choose how to get their order.")]
    problems, counts = [], []
    for kind in (Kind.PICKUP, Kind.DELIVERY):
        if not s.enabled(kind):
            continue
        word = Kind(kind).label.lower()
        if not OpeningHours.objects.filter(settings=s, kind=kind).exists():
            problems.append(f"no {word} hours")
            continue
        free = len(fulfilment.bookable_slots(kind))
        counts.append(f"{free} {word} time{'s' if free != 1 else ''}")
        if not free:
            problems.append(f"no free {word} times in the next {s.days_ahead} day{'s' if s.days_ahead > 1 else ''}")
    if s.delivery_enabled and not DeliveryArea.objects.filter(is_active=True).exists():
        problems.append("no delivery areas")
    if problems:
        return [Result("fulfilment", "Business", label, WARNING,
                       f"Customers cannot order properly: {', '.join(problems)}. Open Pickup and delivery in the admin pages.")]
    return [Result("fulfilment", "Business", label, OK, f"Customers can choose from {' and '.join(counts)} in the next {s.days_ahead} day(s).")]


def check_order_messages() -> list[Result]:
    """WhatsApp messages to customers about orders (task 2.3): stuck in the queue, or not sent in the last day."""
    from datetime import timedelta

    from apps.orders.models import OrderMessage
    from apps.rbac.policy import module_enabled

    if not module_enabled("orders"):
        return []
    label = "WhatsApp messages about orders"
    now = timezone.now()
    stuck = OrderMessage.objects.filter(status=OrderMessage.Status.QUEUED, created_at__lt=now - timedelta(minutes=10)).count()
    if stuck:
        return [Result("order_messages", "Connections", label, FAILED,
                       f"{stuck} message(s) have waited more than 10 minutes to be sent. Check that the worker is running (see “Background jobs”).")]
    day = OrderMessage.objects.filter(created_at__gte=now - timedelta(days=1))
    failed = day.filter(status__in=[OrderMessage.Status.FAILED, OrderMessage.Status.SKIPPED]).count()
    sent = day.filter(status=OrderMessage.Status.SENT).count()
    if failed:
        return [Result("order_messages", "Connections", label, WARNING,
                       f"{failed} message(s) in the last 24 hours were not sent ({sent} sent). Open the orders to see why; "
                       "usually the 24-hour window had closed and no approved template is set.")]
    if not sent:
        return [Result("order_messages", "Connections", label, OK, "No messages in the last 24 hours.")]
    return [Result("order_messages", "Connections", label, OK, f"{sent} message(s) sent in the last 24 hours.")]


def business_checks(tenant, *, live: bool = True) -> list[Result]:
    """Checks for one business. Must run inside that business's schema."""
    found: list[Result] = []
    found += _safe("database", "System", "Database", check_database)
    found += _safe("cache", "System", "Cache (Redis)", check_cache)
    found += _safe("workers", "System", "Background jobs (worker)", check_workers)
    found += _safe("scheduler", "System", "Scheduled jobs", check_scheduler)
    found += _safe("licence", "Business", "Licence", lambda: check_licence(tenant))
    found += _safe("web_address", "Business", "Web address", lambda: check_web_address(tenant))
    found += _safe("fulfilment", "Business", "Pickup and delivery", check_fulfilment)
    found += _safe("connections", "Connections", "Saved connections", lambda: test_connections(live))
    found += _safe("email", "Connections", "Email sending", check_email)
    found += _safe("whatsapp", "Connections", "WhatsApp messages", check_whatsapp)
    found += _safe("order_messages", "Connections", "WhatsApp messages about orders", check_order_messages)
    found += _safe("mfa", "Security", "Two-step verification", check_staff_mfa)
    found += _safe("audit", "Security", "Audit log", check_audit_chain)
    found += _safe("backups", "Backups", "Backups", check_backups)
    return found


# ---------------------------------------------------------------------------
# Platform checks
# ---------------------------------------------------------------------------
def businesses():
    from apps.tenants.models import Tenant

    return Tenant.objects.exclude(schema_name=get_public_schema_name()).select_related("licence").order_by("name")


def check_all_schemas_migrated() -> Result:
    behind = []
    for tenant in businesses():
        with schema_context(tenant.schema_name):
            if unapplied_migrations():
                behind.append(tenant.name)
    if behind:
        return Result("business_databases", "System", "Business databases", FAILED,
                      f"Not up to date: {', '.join(behind)}. Run the database updates (migrate_schemas).")
    return Result("business_databases", "System", "Business databases", OK, f"All {businesses().count()} business database(s) are up to date.")


def check_disk() -> Result:
    usage = shutil.disk_usage(settings.BASE_DIR)
    free = usage.free / usage.total if usage.total else 0
    gb = usage.free / 1024 ** 3
    if free < DISK_FAILED:
        return Result("disk", "System", "Disk space", FAILED, f"Only {gb:.1f} GB ({free:.0%}) free. Free up space now.")
    if free < DISK_WARNING:
        return Result("disk", "System", "Disk space", WARNING, f"{gb:.1f} GB ({free:.0%}) free. Plan more space soon.")
    return Result("disk", "System", "Disk space", OK, f"{gb:.1f} GB ({free:.0%}) free.")


def check_vault_key() -> Result:
    from apps.vault import crypto

    label = "Secret vault master key"
    from django.core.exceptions import ImproperlyConfigured

    try:
        keys = crypto.master_keys()
    except (crypto.VaultError, ImproperlyConfigured):
        return Result("vault_key", "Security", label, FAILED,
                      "The master key is missing or not valid (VAULT_MASTER_KEYS in .env). Saved API keys cannot be opened.")
    sealed = crypto.seal(b"check", b"health-check")
    if crypto.open_sealed(sealed, b"health-check") != b"check":
        return Result("vault_key", "Security", label, FAILED, "The master key does not work.")
    if keys[0][0] == "dev":
        return Result("vault_key", "Security", label, WARNING,
                      "Uses the development key made from DJANGO_SECRET_KEY. Set VAULT_MASTER_KEYS before saving real API keys.")
    return Result("vault_key", "Security", label, OK, f"Works ({len(keys)} key(s)). Keep a copy of it outside the server.")


def check_production_settings() -> Result:
    label = "Security settings"
    if settings.DEBUG:
        return Result("settings", "Security", label, WARNING,
                      "Development mode is on (DJANGO_DEBUG=True). This is fine on a laptop, but never on a real server.")
    from django.core import checks

    problems = [m for m in checks.run_checks(include_deployment_checks=True) if m.level >= checks.WARNING and not m.is_silenced()]
    if problems:
        return Result("settings", "Security", label, WARNING, f"{len(problems)} security setting(s) need attention. Run: python manage.py check --deploy")
    return Result("settings", "Security", label, OK, "Production security settings are on (HTTPS, secure cookies, HSTS).")


def check_licences() -> Result:
    from apps.licensing import services

    ending, grace, blocked = [], [], []
    soon = timezone.now() + TRIAL_WARNING
    for tenant in businesses():
        licence = getattr(tenant, "licence", None)
        state = licence.state() if licence else "unlicensed"
        services.clear_cache(tenant)
        if state == "grace":
            grace.append(tenant.name)
        elif state in ("expired", "unlicensed"):
            blocked.append(tenant.name)
        elif state in ("trial", "active") and licence.period_end() and licence.period_end() < soon:
            ending.append(tenant.name)
    if blocked:
        return Result("licences", "Businesses", "Licences", WARNING, f"Expired or missing licence: {', '.join(blocked)}.")
    if grace or ending:
        parts = []
        if grace:
            parts.append(f"in grace period: {', '.join(grace)}")
        if ending:
            parts.append(f"ending within 7 days: {', '.join(ending)}")
        return Result("licences", "Businesses", "Licences", WARNING, "Licences " + "; ".join(parts) + ".")
    return Result("licences", "Businesses", "Licences", OK, f"{businesses().count()} business(es); no licence needs attention.")


def check_business_connections() -> Result:
    """Saved test results of every business's connections (no live tests, that would be slow)."""
    from apps.vault.models import Connection

    failing = []
    for tenant in businesses():
        with schema_context(tenant.schema_name):
            n = Connection.objects.filter(status=Connection.Status.FAILED).count()
        if n:
            failing.append(f"{tenant.name} ({n})")
    if failing:
        return Result("business_connections", "Businesses", "Business connections", WARNING, f"Failed connections: {', '.join(failing)}.")
    return Result("business_connections", "Businesses", "Business connections", OK, "No business has a failed connection (last tests).")


def check_business_runs() -> Result:
    """The latest check result of each business."""
    from .models import CheckRun

    red = []
    for tenant in businesses():
        with schema_context(tenant.schema_name):
            last = CheckRun.objects.order_by("-started_at").first()
        if last and last.status == FAILED:
            red.append(tenant.name)
    if red:
        return Result("business_checks", "Businesses", "Business checks", WARNING, f"Last check failed for: {', '.join(red)}.")
    return Result("business_checks", "Businesses", "Business checks", OK, "No business's last check failed.")


def platform_checks(*, live: bool = True) -> list[Result]:
    found: list[Result] = []
    found += _safe("database", "System", "Database", check_database)
    found += _safe("business_databases", "System", "Business databases", check_all_schemas_migrated)
    found += _safe("cache", "System", "Cache (Redis)", check_cache)
    found += _safe("workers", "System", "Background jobs (worker)", check_workers)
    found += _safe("scheduler", "System", "Scheduled jobs", check_scheduler)
    found += _safe("disk", "System", "Disk space", check_disk)
    found += _safe("licences", "Businesses", "Licences", check_licences)
    found += _safe("business_connections", "Businesses", "Business connections", check_business_connections)
    found += _safe("business_checks", "Businesses", "Business checks", check_business_runs)
    found += _safe("connections", "Connections", "Saved connections", lambda: test_connections(live))
    found += _safe("vault_key", "Security", "Secret vault master key", check_vault_key)
    found += _safe("settings", "Security", "Security settings", check_production_settings)
    found += _safe("mfa", "Security", "Two-step verification (platform admins)", lambda: check_staff_mfa("Two-step verification (platform admins)"))
    found += _safe("audit", "Security", "Audit log", check_audit_chain)
    found += _safe("backups", "Backups", "Backups", check_backups)
    return found
