"""
"Log in as" (task 1.18, D-128): only the platform Super Admin; a one-time
link for 60 seconds; a reason for real businesses; a red bar with "Back to
Super Admin"; ends after 60 minutes; recorded in both audit logs.
"""
import time
from urllib.parse import urlparse

import pytest
from django.core import signing
from django_tenants.utils import schema_context

from apps.accounts import login_as
from apps.audit.models import AuditEvent
from apps.tenants.models import Tenant
from tests.conftest import make_user
from tests.test_mfa_admin import platform_staff


@pytest.fixture
def super_admin(verified_admin_client, public_tenant):
    return verified_admin_client(public_tenant, "boss@platform.test")


@pytest.fixture
def staff(tenant_a):
    """A business staff member who must use two-step verification (not set up)."""
    return make_user("tenant_a", "staff@a.test", staff=True, first_name="Gita", last_name="Gurung")


def link_for(client, schema: str, user_id: int, **data) -> str:
    response = client.post(f"/platform/login-as/{schema}/{user_id}/", data)
    assert response.status_code == 302, response.content
    return response["Location"]


def follow(client_for, tenant, url: str):
    client = client_for(tenant)
    parts = urlparse(url)
    return client, client.get(f"{parts.path}?{parts.query}")


@pytest.mark.django_db
class TestStart:
    def test_only_the_super_admin(self, client_for, public_tenant, tenant_a, staff):
        support = platform_staff(client_for, public_tenant, "support@platform.test", "platform_support_admin")
        assert support.post(f"/platform/login-as/tenant_a/{staff.pk}/", {"reason": "help"}).status_code == 403
        security = platform_staff(client_for, public_tenant, "sec@platform.test", "platform_security_admin")
        assert security.post(f"/platform/login-as/tenant_a/{staff.pk}/", {"reason": "help"}).status_code == 403
        assert client_for(tenant_a).post(f"/platform/login-as/tenant_a/{staff.pk}/").status_code == 404

    def test_a_real_business_needs_a_reason(self, super_admin, staff):
        response = super_admin.post(f"/platform/login-as/tenant_a/{staff.pk}/", {"reason": "  "}, follow=True)
        assert "it is a real business" in response.content.decode()
        assert not AuditEvent.objects.filter(action="security.login_as").exists()

    def test_a_test_business_needs_no_reason(self, super_admin, tenant_b):
        Tenant.objects.filter(pk=tenant_b.pk).update(is_test=True)
        person = make_user("tenant_b", "cook@b.test")
        assert "/login-as/?token=" in link_for(super_admin, "tenant_b", person.pk)

    def test_locked_people_and_the_platform_itself(self, super_admin, staff):
        with schema_context("tenant_a"):
            staff.is_active = False
            staff.save()
        assert "does not exist or is locked" in super_admin.post(f"/platform/login-as/tenant_a/{staff.pk}/", {"reason": "x"}, follow=True).content.decode()
        assert super_admin.post("/platform/login-as/public/1/", {"reason": "x"}).status_code == 403

    def test_the_way_back_stays_on_the_platform(self, super_admin, staff):
        url = link_for(super_admin, "tenant_a", staff.pk, reason="help", back="https://evil.test/")
        data = signing.loads(urlparse(url).query.split("token=")[1], salt=login_as.SALT)
        assert data["back"].endswith("/platform/people/tenant_a/") and "evil" not in data["back"]


@pytest.mark.django_db
class TestOnTheBusinessSite:
    def test_full_round_trip(self, super_admin, client_for, tenant_a, staff):
        url = link_for(super_admin, "tenant_a", staff.pk, reason="Checking a printer problem")
        assert url.startswith("https://tenant-a.localhost/login-as/?token=")
        client, response = follow(client_for, tenant_a, url)
        assert response.status_code == 302 and response["Location"] == "/admin/"
        page = client.get("/admin/").content.decode()  # no two-step code asked: the Super Admin passed it on the platform
        assert "You are logged in as staff@a.test" in page and "Back to Super Admin" in page and "boss@platform.test" in page
        me = client.get("/api/auth/me/").json()
        assert me["login_as"]["by"] == "boss@platform.test" and me["mfa"]["verified"] and not me["mfa"]["required"]
        with schema_context("public"):
            assert AuditEvent.objects.filter(action="security.login_as", metadata__reason="Checking a printer problem").exists()
        with schema_context("tenant_a"):
            started = AuditEvent.objects.get(action="security.login_as_started")
            assert "boss@platform.test" in started.actor_email and started.target_repr == "staff@a.test"
        back = client.post("/login-as/stop/")
        assert back.status_code == 302 and back["Location"].endswith("/platform/people/tenant_a/")
        assert client.get("/admin/").status_code == 302  # signed out of the business
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="security.login_as_ended", metadata__why="back to Super Admin").exists()

    def test_the_staff_app_gets_the_way_back_as_json(self, super_admin, client_for, tenant_a, staff):
        client, _ = follow(client_for, tenant_a, link_for(super_admin, "tenant_a", staff.pk, reason="help"))
        answer = client.post("/login-as/stop/", HTTP_ACCEPT="application/json")
        assert answer.json()["back"].endswith("/platform/people/tenant_a/")

    def test_a_link_works_once_and_only_on_its_business(self, super_admin, client_for, tenant_a, tenant_b, staff):
        url = link_for(super_admin, "tenant_a", staff.pk, reason="help")
        _, wrong = follow(client_for, tenant_b, url)
        assert wrong.status_code == 400 and "another business" in wrong.content.decode()
        _, first = follow(client_for, tenant_a, url)
        _, again = follow(client_for, tenant_a, url)
        assert first.status_code == 302 and again.status_code == 400 and "used already" in again.content.decode()

    def test_a_person_locked_after_the_link_was_made(self, super_admin, client_for, tenant_a, staff):
        url = link_for(super_admin, "tenant_a", staff.pk, reason="help")
        with schema_context("tenant_a"):
            staff.is_active = False
            staff.save()
        _, response = follow(client_for, tenant_a, url)
        assert response.status_code == 400 and "locked" in response.content.decode()

    def test_old_and_fake_links(self, client_for, tenant_a, staff, monkeypatch):
        token = signing.dumps({"s": "tenant_a", "u": staff.pk, "by": "x@y.test", "n": "abc", "back": "/"}, salt="wrong-salt")
        client = client_for(tenant_a)
        assert "not valid" in client.get(f"/login-as/?token={token}").content.decode()
        real_time = time.time
        monkeypatch.setattr(signing.time, "time", lambda: real_time() - 120)
        old = signing.dumps({"s": "tenant_a", "u": staff.pk, "by": "x@y.test", "n": "abc", "back": "/"}, salt=login_as.SALT)
        monkeypatch.setattr(signing.time, "time", real_time)
        assert "older than 60 seconds" in client.get(f"/login-as/?token={old}").content.decode()

    def test_ends_after_60_minutes(self, super_admin, client_for, tenant_a, staff):
        client, _ = follow(client_for, tenant_a, link_for(super_admin, "tenant_a", staff.pk, reason="help"))
        session = client.session
        session[login_as.SESSION_KEY]["until"] = time.time() - 1
        session.save()
        api = client.get("/api/auth/me/")
        assert api.status_code == 403 and api.json()["code"] == "login_as_ended"
        assert client.get("/admin/").status_code == 302 and "login" in client.get("/admin/")["Location"]
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="security.login_as_ended", metadata__why="time limit").exists()

    def test_normal_logins_still_need_two_step_verification(self, client_for, tenant_a, staff):
        from tests.conftest import admin_login

        assert client_for(tenant_a).get("/login-as/?token=").status_code == 400
        client = client_for(tenant_a)
        admin_login(client, "staff@a.test")
        assert "/account/mfa/" in client.get("/admin/")["Location"]
        session = client.session
        session[login_as.SESSION_KEY] = {"by": "", "until": 0, "back": "/"}  # an old, ended "Log in as" opens nothing
        session.save()
        assert client.get("/admin/").status_code == 302


@pytest.mark.django_db
class TestPeoplePage:
    def test_buttons_for_the_super_admin_only(self, super_admin, client_for, public_tenant, staff):
        page = super_admin.get("/platform/people/tenant_a/").content.decode()
        assert f'/platform/login-as/tenant_a/{staff.pk}/' in page and 'name="reason" required' in page
        viewer = platform_staff(client_for, public_tenant, "billing@platform.test", "platform_billing_admin")
        assert "/platform/login-as/" not in viewer.get("/platform/people/tenant_a/").content.decode()
