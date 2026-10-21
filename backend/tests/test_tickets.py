"""
Tickets (task 1.15): reporting, who sees what, messages and internal notes,
status and assignment, response targets, sending a ticket on to platform
support, automatic tickets from Check system and backups, emails, the API,
and isolation between businesses.
"""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.tickets import services
from apps.tickets.models import Ticket, TicketComment
from tests.conftest import PASSWORD, make_user
from tests.test_rbac import give_role, verified_staff_client


def person(schema, email, role=None, staff=True):
    user = make_user(schema, email, staff=staff, first_name=email.split("@")[0].title())
    if role:
        give_role(schema, user, role)
    return user


def report(schema, user, **kw):
    with schema_context(schema):
        return services.report(user, title=kw.pop("title", "Orders page error"), description=kw.pop("description", "It shows an error."), **kw)


@pytest.mark.django_db
class TestReporting:
    def test_shop_staff_reports_and_admins_are_told(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        it = person("tenant_a", "it@a.test", "system_admin")
        ticket = report("tenant_a", shop, page="https://a.test/admin/orders/?token=SECRET123", browser="Firefox")
        assert ticket.status == "new" and ticket.reporter_email == "shop@a.test" and ticket.page == "/admin/orders/"
        assert "SECRET123" not in ticket.page
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["it@a.test"] and "New ticket" in mail.outbox[0].subject
        assert it.email not in [m.to for m in mail.outbox if "shop@a.test" in m.to]
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="ticket.create").exists()

    def test_validation(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        with schema_context("tenant_a"):
            for bad in ({"title": " ", "description": "x"}, {"title": "x", "description": ""}):
                with pytest.raises(ValidationError):
                    services.report(shop, **bad)
            with pytest.raises(ValidationError):
                services.report(shop, title="x", description="y", priority="nuclear")

    def test_response_targets(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        urgent = report("tenant_a", shop, priority="urgent")
        low = report("tenant_a", shop, priority="low")
        assert urgent.response_due - urgent.created_at == timedelta(hours=1)
        assert low.response_due - low.created_at == timedelta(hours=72)
        with schema_context("tenant_a"):
            Ticket.objects.filter(pk=urgent.pk).update(created_at=timezone.now() - timedelta(hours=2))
            urgent.refresh_from_db()
        assert urgent.response_overdue


@pytest.mark.django_db
class TestWhoSeesWhat:
    def test_reporters_see_only_their_own(self, tenant_a):
        one = person("tenant_a", "one@a.test", "shop_staff")
        two = person("tenant_a", "two@a.test", "shop_staff")
        admin = person("tenant_a", "it@a.test", "it_admin")
        give_role("tenant_a", admin, "operations_manager")  # tickets: all permissions
        t1 = report("tenant_a", one)
        t2 = report("tenant_a", two)
        with schema_context("tenant_a"):
            assert list(services.visible(one)) == [t1]
            assert not services.can_see(one, t2)
            assert set(services.visible(admin)) == {t1, t2}

    def test_internal_notes_are_hidden_from_the_reporter(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        boss = person("tenant_a", "boss@a.test", "system_admin")
        t = report("tenant_a", shop)
        mail.outbox.clear()
        with schema_context("tenant_a"):
            services.comment(boss, t, "Looks like the printer driver.", internal=True)
            services.comment(boss, t, "We are looking at it.")
            assert [c.body for c in services.comments_for(shop, t)] == ["We are looking at it."]
            assert len(services.comments_for(boss, t)) == 2
            with pytest.raises(PermissionDenied):
                services.comment(shop, t, "sneaky", internal=True)
            t.refresh_from_db()
        assert t.first_response_at is not None  # the public answer counts, the internal note does not
        assert [m.to for m in mail.outbox] == [["shop@a.test"]] and "printer" not in mail.outbox[0].body

    def test_the_reporter_cannot_change_status_or_assign(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        t = report("tenant_a", shop)
        with schema_context("tenant_a"):
            with pytest.raises(PermissionDenied):
                services.set_status(shop, t, "closed")
            with pytest.raises(PermissionDenied):
                services.assign(shop, t, shop)

    def test_tickets_module_off(self, tenant_a, client_for):
        from apps.licensing.services import set_module_enabled

        client = verified_staff_client(client_for, tenant_a, "sys@a.test", "system_admin")
        set_module_enabled(tenant_a, "tickets", False)
        assert client.get("/tickets/").status_code == 403


@pytest.mark.django_db
class TestHandling:
    def test_status_assign_and_emails(self, tenant_a):
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        boss = person("tenant_a", "boss@a.test", "system_admin")
        helper = person("tenant_a", "helper@a.test", "operations_manager")
        t = report("tenant_a", shop)
        mail.outbox.clear()
        with schema_context("tenant_a"):
            services.assign(boss, t, helper)
            assert t.status == "in_progress" and t.assigned_to == helper
            assert mail.outbox[-1].to == ["helper@a.test"]
            with pytest.raises(ValidationError, match="cannot work on tickets"):
                services.assign(boss, t, shop)
            services.set_status(helper, t, "waiting")
            assert mail.outbox[-1].to == ["shop@a.test"] and "Waiting for reply" in mail.outbox[-1].subject
            services.comment(shop, t, "Here is a photo of the error.")
            t.refresh_from_db()
            assert t.status == "in_progress" and mail.outbox[-1].to == ["helper@a.test"]
            services.set_status(helper, t, "resolved")
            assert t.resolved_at is not None
            services.set_status(helper, t, "in_progress")
            assert t.resolved_at is None
            actions = set(AuditEvent.objects.values_list("action", flat=True))
        assert {"ticket.assign", "ticket.status", "ticket.comment"} <= actions

    def test_email_problems_do_not_stop_tickets(self, tenant_a, monkeypatch):
        person("tenant_a", "boss@a.test", "system_admin")
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        monkeypatch.setattr(services, "send_mail", lambda *a, **k: 1 / 0)
        assert report("tenant_a", shop).pk


@pytest.mark.django_db
class TestPlatformSupport:
    def test_send_on_reply_and_follow(self, tenant_a, public_tenant):
        root = make_user("public", "root@platform.test", superuser=True)
        shop = person("tenant_a", "shop@a.test", "shop_staff")
        boss = person("tenant_a", "boss@a.test", "system_admin")
        t = report("tenant_a", shop, title="Cannot print receipts")
        mail.outbox.clear()
        with schema_context("tenant_a"):
            with pytest.raises(PermissionDenied):
                services.send_to_platform(shop, t)
            number = services.send_to_platform(boss, t, "Tried restarting the printer.")
            with pytest.raises(ValidationError, match="already"):
                services.send_to_platform(boss, t)
        assert mail.outbox[-1].to == ["root@platform.test"] and "Tenant A Butchery" in mail.outbox[-1].subject
        with schema_context("public"):
            remote = Ticket.objects.get(pk=number)
            assert remote.from_schema == "tenant_a" and remote.from_ticket_id == t.pk and remote.source == "business"
            assert "Tried restarting the printer." in remote.description and remote.reporter is None
            services.comment(root, remote, "Internal: check the logs.", internal=True)
            services.comment(root, remote, "Please update the printer app.")
            services.set_status(root, remote, "waiting")
        assert mail.outbox[-1].to == ["boss@a.test"] and "Waiting for reply" in mail.outbox[-1].body
        assert "/tickets/" in mail.outbox[-1].body and "check the logs" not in "".join(m.body for m in mail.outbox)
        with schema_context("tenant_a"):
            seen, notes = services.platform_view(t)
            assert seen.status == "waiting" and [n.body for n in notes] == ["Please update the printer app."]
            services.reply_to_platform(boss, t, "Updated, works now.")
        with schema_context("public"):
            remote.refresh_from_db()
            assert remote.status == "in_progress" and remote.comments.last().body == "Updated, works now."

    def test_a_business_cannot_read_another_business_platform_ticket(self, tenant_a, tenant_b, public_tenant):
        a_boss = person("tenant_a", "boss@a.test", "system_admin")
        b_boss = person("tenant_b", "boss@b.test", "system_admin")
        ta = report("tenant_a", a_boss)
        with schema_context("tenant_a"):
            number = services.send_to_platform(a_boss, ta)
        tb = report("tenant_b", b_boss)
        with schema_context("tenant_b"):
            Ticket.objects.filter(pk=tb.pk).update(platform_ticket_id=number)  # forged link
            tb.refresh_from_db()
            assert services.platform_view(tb) == (None, [])
            with pytest.raises(ValidationError):
                services.reply_to_platform(b_boss, tb, "hello")
        with schema_context("public"):
            assert not TicketComment.objects.filter(body="hello").exists()

    def test_platform_list_shows_only_platform_tickets(self, tenant_a, public_tenant, client_for):
        from tests.test_mfa_admin import platform_staff

        report("tenant_a", person("tenant_a", "shop@a.test", "shop_staff"), title="Business-only problem")
        support = platform_staff(client_for, public_tenant, "help@platform.test", "platform_support_admin")
        page = support.get("/tickets/?show=all").content.decode()
        assert "Business-only problem" not in page and "Platform support tickets" in page


@pytest.mark.django_db
class TestAutomaticTickets:
    def test_one_open_ticket_per_problem(self, tenant_a):
        person("tenant_a", "boss@a.test", "system_admin")
        with schema_context("tenant_a"):
            first = services.system_ticket(source="check", key="check:failed", title="Check failed", description="Database: Failed")
            again = services.system_ticket(source="check", key="check:failed", title="Check failed", description="Database: Failed")
            assert first.pk == again.pk and first.comments.count() == 1 and first.reporter_label == "System"
            services.set_status(make_user("tenant_a", "x@a.test", superuser=True), first, "resolved")
            third = services.system_ticket(source="check", key="check:failed", title="Check failed", description="x")
            assert third.pk != first.pk

    def test_scheduled_red_check_creates_a_ticket(self, tenant_a, monkeypatch):
        from apps.health import checks
        from apps.health import services as health
        from apps.health.models import CheckRun

        person("tenant_a", "boss@a.test", "system_admin")
        monkeypatch.setattr(checks, "check_database", lambda: checks.Result("database", "System", "Database", "failed", "Cannot read."))
        with schema_context("tenant_a"):
            health.run(CheckRun.Trigger.SCHEDULE, live=False)
            ticket = Ticket.objects.get(source="check")
            assert "Database: Cannot read." in ticket.description and ticket.priority == "high"
            health.run(CheckRun.Trigger.BUTTON, live=False)  # a button run never makes tickets
            assert Ticket.objects.count() == 1

    def test_scheduled_failed_backup_creates_a_ticket(self, public_tenant, monkeypatch):
        from apps.backups import dbtools
        from apps.backups import services as backups
        from apps.backups.models import BackupRun

        make_user("public", "root@platform.test", superuser=True)
        monkeypatch.setattr(dbtools, "dump", lambda *a, **k: (_ for _ in ()).throw(dbtools.DatabaseToolError("Disk full.")))
        with schema_context("public"):
            run = BackupRun.objects.create(kind="backup", trigger="schedule", queued_at=timezone.now())
            backups.execute(run)
            ticket = Ticket.objects.get(source="backup")
            assert "Disk full." in ticket.description

    def test_create_ticket_buttons(self, tenant_a, client_for):
        from apps.health.models import CheckRun

        client = verified_staff_client(client_for, tenant_a, "sys@a.test", "system_admin")
        with schema_context("tenant_a"):
            now = timezone.now()
            run = CheckRun.objects.create(started_at=now, finished_at=now, trigger="button", status="failed", counts={},
                                          results=[{"code": "db", "area": "System", "label": "Database", "status": "failed", "message": "Cannot read."}])
        response = client.post(f"/tickets/from-check/{run.pk}/", follow=True)
        assert "Database: Cannot read." in response.content.decode()
        assert "Create ticket" in client.get(f"/system-check/{run.pk}/").content.decode()


@pytest.mark.django_db
class TestPagesAndApi:
    def test_report_page_and_list(self, client_for, tenant_a):
        shop = verified_staff_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        page = shop.get("/tickets/new/?from=/admin/orders/order/%3Fq%3Dx").content.decode()
        assert "Report a problem" in page and "/admin/orders/order/" in page and "q=x" not in page
        response = shop.post("/tickets/new/", {"title": "Scale not working", "description": "Shows 0 kg", "category": "problem",
                                               "priority": "high", "page": "/admin/"}, follow=True)
        body = response.content.decode()
        assert "Ticket #" in body and "Scale not working" in body
        assert "Scale not working" in shop.get("/tickets/").content.decode()
        assert 'name="status"' not in body  # the reporter cannot change the status

    def test_report_a_problem_link_on_every_admin_page(self, client_for, tenant_a):
        shop = verified_staff_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        assert "/tickets/new/?from=/admin/" in shop.get("/admin/").content.decode()

    def test_other_peoples_tickets_are_404(self, client_for, tenant_a):
        other = report("tenant_a", person("tenant_a", "other@a.test", "shop_staff"))
        shop = verified_staff_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        assert shop.get(f"/tickets/{other.pk}/").status_code == 404
        assert shop.post(f"/tickets/{other.pk}/", {"action": "comment", "body": "hi"}).status_code == 404

    def test_handler_page_actions(self, client_for, tenant_a):
        t = report("tenant_a", person("tenant_a", "shop@a.test", "shop_staff"))
        boss = verified_staff_client(client_for, tenant_a, "sys@a.test", "system_admin")
        page = boss.get(f"/tickets/{t.pk}/").content.decode()
        assert "Send to platform support" in page and 'name="assigned_to"' in page
        boss.post(f"/tickets/{t.pk}/", {"action": "status", "status": "resolved"})
        with schema_context("tenant_a"):
            t.refresh_from_db()
        assert t.status == "resolved"

    def test_api(self, client_for, tenant_a, tenant_b):
        from tests.test_vault import api_client

        shop = api_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        created = shop.post("/api/tickets/", {"title": "App slow", "description": "Very slow today", "priority": "normal"}, content_type="application/json")
        assert created.status_code == 201
        pk = created.json()["id"]
        assert shop.patch(f"/api/tickets/{pk}/", {"status": "closed"}, content_type="application/json").status_code == 403
        assert shop.post(f"/api/tickets/{pk}/comments/", {"body": "Still slow"}, content_type="application/json").status_code == 201
        assert shop.post("/api/tickets/", {"title": "", "description": "x"}, content_type="application/json").status_code == 400
        boss = api_client(client_for, tenant_a, "boss@a.test", "system_admin")
        assert boss.patch(f"/api/tickets/{pk}/", {"status": "resolved", "assigned_to": "boss@a.test"}, content_type="application/json").json()["status"] == "resolved"
        data = boss.get(f"/api/tickets/{pk}/").json()
        assert data["assigned_to"] == "boss@a.test" and len(data["comments"]) == 1
        other = api_client(client_for, tenant_b, "boss@b.test", "system_admin")
        assert other.get(f"/api/tickets/{pk}/").status_code == 404
        assert all(t["title"] != "App slow" for t in other.get("/api/tickets/").json())
