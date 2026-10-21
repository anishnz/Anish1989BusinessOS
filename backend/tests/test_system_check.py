"""
"Check system" (task 1.13): the checks, saved history, the button limit,
scheduled runs and alerts, the page and API, and who may use them.
"""
import dataclasses
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.health import checks, services, tasks
from apps.health.models import CheckRun
from apps.inbox.models import WebhookDelivery
from apps.licensing.models import Licence
from apps.vault import providers
from apps.vault import services as vault
from apps.vault.models import Connection
from tests.conftest import add_totp_device, make_user
from tests.test_inbox import connect_whatsapp
from tests.test_mfa_admin import platform_staff
from tests.test_rbac import give_role, verified_staff_client
from tests.test_vault import SECRET, create_openai, fake_http  # noqa: F401 - fixture

BUTTON = CheckRun.Trigger.BUTTON
SCHEDULE = CheckRun.Trigger.SCHEDULE


def by_code(results, code):
    return next(r for r in results if r.code == code)


def run_in(schema, trigger=BUTTON, **kw):
    with schema_context(schema):
        return services.run(trigger, **kw)


@pytest.fixture
def no_cooldown(monkeypatch):
    monkeypatch.setattr(services, "BUTTON_COOLDOWN_SECONDS", 0)
    from django.core.cache import cache

    real_add = cache.add
    monkeypatch.setattr(cache, "add", lambda key, *a, **k: True if key == "health:button" else real_add(key, *a, **k))


# ---------------------------------------------------------------------------
# Single checks
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChecks:
    def test_overall_result(self):
        r = lambda s: checks.Result("x", "a", "x", s, "")  # noqa: E731
        assert checks.overall([r("ok"), r("not_set_up")]) == "ok"
        assert checks.overall([r("ok"), r("warning"), r("not_set_up")]) == "warning"
        assert checks.overall([r("warning"), r("failed")]) == "failed"

    def test_database_and_missing_updates(self, tenant_a, monkeypatch):
        with schema_context("tenant_a"):
            assert checks.check_database().status == "ok"
            monkeypatch.setattr(checks, "unapplied_migrations", lambda: 2)
            result = checks.check_database()
        assert result.status == "failed" and "2 update(s)" in result.message

    def test_worker_and_scheduler(self, tenant_a, monkeypatch):
        with schema_context("tenant_a"):
            assert checks.check_workers().status == "warning"
            monkeypatch.setattr(checks, "ping_workers", lambda: 2)
            assert checks.check_workers().status == "ok"
            assert checks.check_scheduler().status == "warning"
        tasks.heartbeat()  # written once, read from any business
        with schema_context("tenant_a"):
            assert checks.check_scheduler().status == "ok"
        monkeypatch.setattr(checks, "HEARTBEAT_LATE", timedelta(seconds=-1))
        with schema_context("tenant_a"):
            assert "Check the scheduler" in checks.check_scheduler().message

    def test_broker_down_is_a_warning_not_a_crash(self, tenant_a, monkeypatch):
        def broken():
            raise ConnectionError("redis://secret-host:6379 refused")

        monkeypatch.setattr(checks, "ping_workers", broken)
        with schema_context("tenant_a"):
            result = checks.check_workers()
        assert result.status == "warning" and "secret-host" not in result.message

    def test_a_crashing_check_is_red_and_hides_details(self, tenant_a, monkeypatch):
        def broken():
            raise RuntimeError("password=hunter2 at db.internal")

        monkeypatch.setattr(checks, "check_cache", broken)
        with schema_context("tenant_a"):
            results = checks.business_checks(tenant_a, live=False)
        cache_result = by_code(results, "cache")
        assert cache_result.status == "failed"
        assert "hunter2" not in cache_result.message and "db.internal" not in cache_result.message

    def test_licence(self, tenant_a):
        licence = Licence.objects.get(tenant=tenant_a)
        assert checks.check_licence(tenant_a).status == "ok"
        licence.trial_ends_at = timezone.now() + timedelta(days=3)
        licence.save()
        tenant_a.refresh_from_db()
        result = checks.check_licence(tenant_a)
        assert result.status == "warning" and "trial ends" in result.message
        licence.trial_ends_at = timezone.now() - timedelta(days=1)
        licence.save()
        tenant_a.refresh_from_db()
        from apps.licensing.services import clear_cache

        clear_cache(tenant_a)
        assert "Access stops" in checks.check_licence(tenant_a).message

    def test_connections_are_tested_and_status_saved(self, tenant_a, fake_http):  # noqa: F811
        create_openai()
        fake_http(200, {"data": []})
        with schema_context("tenant_a"):
            [result] = checks.test_connections()
            assert result.status == "ok" and result.area == "Connections"
            assert Connection.objects.get().status == "connected"
            changes = AuditEvent.objects.filter(action="integration.status_changed").count()
        fake_http(401)
        with schema_context("tenant_a"):
            [result] = checks.test_connections()
            assert result.status == "failed" and "refused the key" in result.message
            assert Connection.objects.get().status == "failed"
            assert AuditEvent.objects.filter(action="integration.status_changed").count() == changes + 1
            checks.test_connections()  # same result again: no new audit entry
            assert AuditEvent.objects.filter(action="integration.status_changed").count() == changes + 1
            text = str(list(AuditEvent.objects.values_list("metadata", flat=True)))
        assert SECRET not in text and SECRET not in result.message

    def test_connection_tests_run_at_the_same_time(self, tenant_a, monkeypatch):
        import threading
        import time

        create_openai()
        with schema_context("tenant_a"):
            vault.create_connection(provider_code="anthropic", label="Second AI", config={}, secrets={"api_key": "sk-ant-other-123456"})
        seen = set()

        def slow(s, c):
            seen.add(threading.get_ident())
            time.sleep(0.5)
            return providers.TestResult(True, "Fine.")

        for code in ("openai", "anthropic"):
            monkeypatch.setitem(providers.PROVIDERS, code, dataclasses.replace(providers.PROVIDERS[code], test=slow))
        start = time.monotonic()
        with schema_context("tenant_a"):
            results = checks.test_connections()
        assert [r.status for r in results] == ["ok", "ok"]
        assert time.monotonic() - start < 0.95 and len(seen) == 2

    def test_disabled_and_unreadable_connections(self, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"):
            vault.set_disabled(conn, True)
            [result] = checks.test_connections()
            assert result.status == "not_set_up"
            vault.set_disabled(conn, False)
            Connection.objects.filter(pk=conn.pk).update(secret_ciphertext=b"broken")
            [result] = checks.test_connections()
        assert result.status == "failed" and "cannot be opened" in result.message

    def test_email(self, tenant_a, settings):
        settings.DEBUG = False
        with schema_context("tenant_a"):
            assert checks.check_email().status == "warning"
        with schema_context("public"):
            vault.create_connection(provider_code="gmail", label="Platform mail", config={"email": "platform@example.com"},
                                    secrets={"app_password": "abcd efgh ijkl mnop"})
        with schema_context("tenant_a"):
            result = checks.check_email()
        assert result.status == "ok" and "platform" in result.message

    def test_whatsapp(self, tenant_a):
        with schema_context("tenant_a"):
            assert checks.check_whatsapp().status == "not_set_up"
        connect_whatsapp()
        with schema_context("tenant_a"):
            assert "No message from Meta" in checks.check_whatsapp().message
            WebhookDelivery.objects.create(ok=False, note="bad signature")
            assert "refused" in checks.check_whatsapp().message
            WebhookDelivery.objects.create(ok=True, messages=1)
            assert checks.check_whatsapp().status == "ok"

    def test_staff_mfa(self, tenant_a):
        with schema_context("tenant_a"):
            assert checks.check_staff_mfa().message == "No active staff accounts yet."
        user = make_user("tenant_a", "staff@a.test", staff=True)
        with schema_context("tenant_a"):
            assert "not set up" in checks.check_staff_mfa().message
        add_totp_device("tenant_a", user)
        with schema_context("tenant_a"):
            assert checks.check_staff_mfa().status == "ok"
            from apps.accounts import security

            security.set_mfa_switched_off(user, True, reason="test", by_email="boss@platform.test")
            assert "switched off" in checks.check_staff_mfa().message

    def test_broken_audit_log_is_red(self, tenant_a, monkeypatch):
        import apps.audit.services as audit_services

        monkeypatch.setattr(audit_services, "verify_chain", lambda: (False, ["Event 3: changed"]))
        with schema_context("tenant_a"):
            assert checks.check_audit_chain().status == "failed"

    def test_business_backups_are_not_set_up_yet(self, tenant_a):
        with schema_context("tenant_a"):
            assert [r.status for r in checks.check_backups()] == ["not_set_up"]  # details: tests/test_backups.py

    def test_business_checks_cover_every_area(self, tenant_a):
        with schema_context("tenant_a"):
            results = checks.business_checks(tenant_a, live=False)
        assert {r.area for r in results} == {"System", "Business", "Connections", "Security", "Backups"}
        assert {"database", "cache", "workers", "scheduler", "licence", "web_address", "email", "whatsapp", "mfa", "audit", "backups"} <= {r.code for r in results}


@pytest.mark.django_db
class TestPlatformChecks:
    def test_platform_checks_cover_every_area(self, public_tenant):
        results = checks.platform_checks(live=False)
        assert {"database", "business_databases", "cache", "workers", "scheduler", "disk", "licences", "business_connections",
                "business_checks", "vault_key", "settings", "mfa", "audit", "backups"} <= {r.code for r in results}
        assert all(r.status != "failed" for r in results), [r for r in results if r.status == "failed"]

    def test_licences_ending_soon_are_named(self, tenant_a):
        Licence.objects.filter(tenant=tenant_a).update(trial_ends_at=timezone.now() + timedelta(days=2))
        result = checks.check_licences()
        assert result.status == "warning" and "Tenant A Butchery" in result.message

    def test_failed_business_connections_and_checks_are_named(self, tenant_a, tenant_b):
        conn = create_openai("tenant_b")
        with schema_context("tenant_b"):
            Connection.objects.filter(pk=conn.pk).update(status="failed")
        assert "Tenant B Catering (1)" in checks.check_business_connections().message
        now = timezone.now()
        with schema_context("tenant_a"):
            CheckRun.objects.create(started_at=now, finished_at=now, trigger=SCHEDULE, status="failed")
        assert "Tenant A Butchery" in checks.check_business_runs().message

    def test_disk_space(self, monkeypatch):
        import shutil
        from collections import namedtuple

        Usage = namedtuple("Usage", "total used free")
        monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(100 * 1024 ** 3, 90 * 1024 ** 3, 10 * 1024 ** 3))
        assert checks.check_disk().status == "warning"
        monkeypatch.setattr(shutil, "disk_usage", lambda path: Usage(100 * 1024 ** 3, 97 * 1024 ** 3, 3 * 1024 ** 3))
        assert checks.check_disk().status == "failed"

    def test_development_mode_is_a_warning(self, settings):
        settings.DEBUG = True
        assert checks.check_production_settings().status == "warning"

    def test_vault_key(self, settings):
        assert checks.check_vault_key().status == "ok"
        settings.VAULT_MASTER_KEYS = ""
        settings.DEBUG = False
        assert checks.check_vault_key().status == "failed"


# ---------------------------------------------------------------------------
# Runs, history, limits and alerts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRuns:
    def test_a_run_is_saved_and_audited(self, tenant_a):
        user = make_user("tenant_a", "it@a.test", staff=True)
        record = run_in("tenant_a", user=user, live=False)
        assert record.status == "warning"  # no worker, no scheduler in tests
        assert record.run_by_email == "it@a.test" and record.trigger == "button"
        assert sum(record.counts.values()) == len(record.results)
        with schema_context("tenant_a"):
            assert CheckRun.objects.count() == 1
            assert AuditEvent.objects.filter(action="system_check.run", actor_email="it@a.test").exists()
        with schema_context("tenant_b"):
            assert CheckRun.objects.count() == 0

    def test_button_only_once_a_minute_per_site(self, tenant_a, tenant_b):
        run_in("tenant_a", live=False)
        with pytest.raises(ValidationError, match="less than a minute"):
            run_in("tenant_a", live=False)
        run_in("tenant_b", live=False)  # another business is not affected
        run_in("tenant_a", SCHEDULE, live=False)  # the schedule is not limited

    def test_history_is_trimmed(self, tenant_a, monkeypatch):
        monkeypatch.setattr(services, "HISTORY_KEEP", 3)
        for _ in range(5):
            run_in("tenant_a", SCHEDULE, live=False)
        with schema_context("tenant_a"):
            assert CheckRun.objects.count() == 3

    def _fail(self, monkeypatch):
        monkeypatch.setattr(checks, "check_cache", lambda: checks.Result("cache", "System", "Cache (Redis)", "failed", "Broken."))

    def test_scheduled_failure_emails_admins_once(self, tenant_a, monkeypatch):
        admin = make_user("tenant_a", "sysadmin@a.test", staff=True)
        give_role("tenant_a", admin, "system_admin")
        it = make_user("tenant_a", "it@a.test", staff=True)
        give_role("tenant_a", it, "it_admin")
        clerk = make_user("tenant_a", "clerk@a.test", staff=True)
        give_role("tenant_a", clerk, "shop_staff")
        self._fail(monkeypatch)

        alerts = lambda: [m for m in mail.outbox if m.subject.startswith("System check failed")]  # noqa: E731 - tickets also email (test_tickets.py)
        first = run_in("tenant_a", SCHEDULE, live=False)
        assert first.status == "failed" and first.alert_sent
        assert len(alerts()) == 1
        mail.outbox[:] = alerts()
        assert sorted(mail.outbox[0].to) == ["it@a.test", "sysadmin@a.test"]
        assert "Cache (Redis): Broken." in mail.outbox[0].body and "Tenant A Butchery" in mail.outbox[0].subject
        assert "https://tenant-a.localhost/system-check/" in mail.outbox[0].body

        run_in("tenant_a", SCHEDULE, live=False)  # still red: no second email
        assert len(alerts()) == 1
        monkeypatch.undo()
        import apps.health.checks as health_checks

        monkeypatch.setattr(health_checks, "ping_workers", lambda: 0)
        run_in("tenant_a", SCHEDULE, live=False)  # back to amber
        self._fail(monkeypatch)
        run_in("tenant_a", SCHEDULE, live=False)  # red again: new email
        assert len(alerts()) == 2

    def test_button_failures_do_not_email(self, tenant_a, monkeypatch):
        admin = make_user("tenant_a", "sysadmin@a.test", staff=True)
        give_role("tenant_a", admin, "system_admin")
        self._fail(monkeypatch)
        assert run_in("tenant_a", BUTTON, live=False).status == "failed"
        assert mail.outbox == []

    def test_platform_alerts_go_to_super_admins(self, public_tenant, monkeypatch):
        make_user("public", "boss@platform.test", superuser=True)
        make_user("public", "helper@platform.test", staff=True)
        self._fail(monkeypatch)
        run_in("public", SCHEDULE, live=False)
        assert mail.outbox[0].to == ["boss@platform.test"]

    def test_scheduled_runs_cover_every_open_business(self, tenant_a, tenant_b, public_tenant):
        from apps.licensing.services import suspend

        suspend(tenant_b, "test")
        summary = services.run_everywhere()
        assert summary["tenant_a"] in ("ok", "warning") and summary["public"] in ("ok", "warning")
        assert summary["tenant_b"] == "skipped (suspended)"
        with schema_context("tenant_a"):
            assert CheckRun.objects.filter(trigger="schedule").count() == 1
        with schema_context("tenant_b"):
            assert CheckRun.objects.count() == 0
        assert CheckRun.objects.filter(trigger="schedule").count() == 1  # platform

    def test_command(self, tenant_a, capsys):
        from django.core.management import call_command

        call_command("check_system", "--schema", "tenant_a", "--no-live")
        out = capsys.readouterr().out
        assert "System / Database" in out and "Overall: warning" in out


# ---------------------------------------------------------------------------
# Page and API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPageAndApi:
    def test_system_admin_runs_the_checks_on_the_page(self, client_for, tenant_a):
        admin = verified_staff_client(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        page = admin.get("/system-check/").content.decode()
        assert 'value="Check system"' in page and "have not run yet" in page
        response = admin.post("/system-check/", follow=True)
        page = response.content.decode()
        assert "Checks finished" in page and "Database" in page and "Backups to your own Google Drive are not set up" in page
        assert 'class="pill warning big"' in page
        again = admin.post("/system-check/", follow=True).content.decode()
        assert "less than a minute ago" in again

    def test_earlier_run_page(self, client_for, tenant_a, tenant_b):
        admin = verified_staff_client(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        record = run_in("tenant_a", live=False)
        assert admin.get(f"/system-check/{record.pk}/").status_code == 200
        other = run_in("tenant_b", live=False)
        if other.pk != record.pk:
            assert admin.get(f"/system-check/{other.pk}/").status_code == 404

    def test_owner_may_check_but_shop_staff_may_not(self, client_for, tenant_a):
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert owner.get("/system-check/").status_code == 200
        staff = verified_staff_client(client_for, tenant_a, "clerk@a.test", "shop_staff")
        assert staff.get("/system-check/").status_code == 403
        assert staff.post("/system-check/").status_code == 403
        assert staff.post("/api/system-check/run/").status_code == 403
        with schema_context("tenant_a"):
            assert CheckRun.objects.count() == 0

    def test_api(self, client_for, tenant_a):
        it = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        assert it.get("/api/system-check/").json() == {"latest": None, "history": []}
        response = it.post("/api/system-check/run/")
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "warning" and data["run_by"] == "it@a.test"
        assert {"code", "area", "label", "status", "message"} == set(data["results"][0])
        assert it.post("/api/system-check/run/").status_code == 429
        listing = it.get("/api/system-check/").json()
        assert listing["latest"]["id"] == data["id"] and "results" not in listing["history"][0]

    def test_businesses_see_only_their_own_runs(self, client_for, tenant_a, tenant_b):
        run_in("tenant_a", live=False)
        b_admin = verified_staff_client(client_for, tenant_b, "sysadmin@b.test", "system_admin")
        assert b_admin.get("/api/system-check/").json()["latest"] is None

    def test_platform_page(self, verified_admin_client, client_for, public_tenant, no_cooldown):
        boss = verified_admin_client(public_tenant, "boss@platform.test")
        page = boss.post("/system-check/", follow=True).content.decode()
        assert "Business databases" in page and "Secret vault master key" in page
        security = platform_staff(client_for, public_tenant, "sec@platform.test", "platform_security_admin")
        assert security.get("/system-check/").status_code == 200
        support = platform_staff(client_for, public_tenant, "support@platform.test", "platform_support_admin")
        assert support.get("/system-check/").status_code == 403
        assert support.post("/api/system-check/run/").status_code == 403

    def test_header_link(self, verified_admin_client, tenant_a):
        page = verified_admin_client(tenant_a).get("/admin/").content.decode()
        assert 'href="/system-check/"' in page


def test_time_wording():
    now = timezone.now()
    assert checks._ago(now - timedelta(seconds=30)) == "just now"
    assert checks._ago(now - timedelta(minutes=2)) == "2 minutes ago"
    assert checks._ago(now - timedelta(hours=1, minutes=40)) == "2 hours ago"
    assert checks._ago(now - timedelta(hours=40)) == "1 day ago"
