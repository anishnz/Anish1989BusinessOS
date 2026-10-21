"""
First-login setup wizard (task 1.16): when it opens, who may use it, business
details, the backups step (passphrase, Google Drive, test backup) and the way
back from the Backups page and Google sign-in, connections, finishing, and
the backups reminder on admin pages.
"""
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.backups import services as backups
from apps.backups.models import BackupRun
from apps.setup import services
from apps.setup.models import BusinessProfile, SetupProgress
from tests.conftest import PASSWORD
from tests.test_backups import FakeGoogle, connect_drive, google, no_real_tasks, sign_in_app  # noqa: F401 - fixtures
from tests.test_rbac import verified_staff_client


@pytest.fixture
def fresh(tenant_a):
    """Tenant A as a brand-new business: setup not done yet."""
    with schema_context("tenant_a"):
        SetupProgress.objects.all().delete()
    return tenant_a


def admin_of(client_for, tenant, role="it_admin", email="it@a.test"):
    return verified_staff_client(client_for, tenant, email, role)


@pytest.mark.django_db
class TestOpening:
    def test_opens_for_admins_of_a_new_business(self, client_for, fresh):
        for role, email in (("it_admin", "it@a.test"), ("system_admin", "sys@a.test")):
            client = admin_of(client_for, fresh, role, email)
            response = client.get("/admin/")
            assert response.status_code == 302 and response["Location"] == "/setup/"
            page = client.get("/setup/").content.decode()
            assert "Welcome!" in page and "Tenant A Butchery" in page and "Business details" in page

    def test_not_for_other_people(self, client_for, fresh):
        for role, email in (("business_owner", "owner@a.test"), ("shop_staff", "shop@a.test")):
            client = admin_of(client_for, fresh, role, email)
            assert client.get("/admin/").status_code == 200
            assert client.get("/setup/").status_code == 403

    def test_not_once_finished_or_on_the_platform(self, client_for, tenant_a, public_tenant):
        assert admin_of(client_for, tenant_a).get("/admin/").status_code == 200  # tenant A counts as set up
        from tests.test_mfa_admin import platform_staff

        root = platform_staff(client_for, public_tenant, "root@platform.test", "super_admin")
        assert root.get("/admin/").status_code == 200
        assert root.get("/setup/").status_code == 404

    def test_later_closes_it_for_this_sign_in(self, client_for, fresh):
        client = admin_of(client_for, fresh)
        assert client.post("/setup/later/").status_code == 302
        assert client.get("/admin/").status_code == 200
        again = admin_of(client_for, fresh, "system_admin", "sys@a.test")  # another sign-in still sees it
        assert again.get("/admin/")["Location"] == "/setup/"

    def test_other_admin_pages_are_never_blocked(self, client_for, fresh):
        client = admin_of(client_for, fresh)
        assert client.get("/admin/accounts/user/").status_code == 200
        assert client.get("/backups/").status_code == 200


@pytest.mark.django_db
class TestBusinessDetails:
    def test_save_and_continue(self, client_for, fresh):
        client = admin_of(client_for, fresh)
        response = client.post("/setup/?step=business", {
            "action": "business", "trading_name": " Gorkha  Butchery ", "phone": "09 123 4567", "email": "hello@gorkha.test",
            "address": "1 Queen Street", "suburb": "CBD", "city": "Auckland", "postcode": "1010", "gst_number": "123-456-789",
            "website": "www.gorkha.co.nz"})
        assert response.status_code == 302 and response["Location"] == "/setup/?step=backups"
        with schema_context("tenant_a"):
            p = BusinessProfile.objects.get()
            assert p.trading_name == "Gorkha Butchery" and p.website == "https://www.gorkha.co.nz" and p.updated_by_email == "it@a.test"
            assert services.step_done("business") and services.business_name() == "Gorkha Butchery"
            assert AuditEvent.objects.filter(action="setup.business_details").exists()

    @pytest.mark.parametrize("field,value,message", [
        ("phone", "call me", "Use numbers only"), ("gst_number", "12", "8 or 9 digits"), ("postcode", "10101", "4 digits"),
        ("email", "not-an-email", "valid email"), ("website", "https://", "web address"),
    ])
    def test_checks(self, client_for, fresh, field, value, message):
        page = admin_of(client_for, fresh).post("/setup/?step=business", {"action": "business", field: value}).content.decode()
        assert message in page
        with schema_context("tenant_a"):
            assert not BusinessProfile.objects.exclude(**{field: ""}).exists()

    def test_everything_is_optional(self, client_for, fresh):
        assert admin_of(client_for, fresh).post("/setup/?step=business", {"action": "business"}).status_code == 302


@pytest.mark.django_db
class TestBackupsStep:
    def test_passphrase_and_google_drive_come_back_to_the_wizard(self, client_for, fresh, public_tenant, google):
        sign_in_app("public")
        client = admin_of(client_for, fresh)
        page = client.get("/setup/?step=backups").content.decode()
        assert "Make a passphrase for me" in page and 'name="next" value="/setup/?step=backups"' in page
        saved = client.post("/backups/", {"action": "passphrase", "password": PASSWORD, "generate": "1", "next": "/setup/?step=backups"})
        assert 'href="/setup/?step=backups">I have saved it' in saved.content.decode()

        start = client.post("/backups/", {"action": "connect", "password": PASSWORD, "next": "/setup/?step=backups"})
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        back = urlparse(client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "code": "abc"})["Location"])
        done = client.get(f"{back.path}?{back.query}")
        assert done.status_code == 302 and done["Location"] == "/setup/?step=backups"
        page = client.get("/setup/?step=backups").content.decode()
        assert "✓ Set" in page and "✓ Connected (owner@gmail.test)" in page and "Make a test backup" in page

    def test_without_a_google_sign_in_app_it_says_so(self, client_for, fresh):
        page = admin_of(client_for, fresh).get("/setup/?step=backups").content.decode()
        assert "the platform's Google sign-in app is not set up" in page and 'value="Connect Google Drive"' not in page

    def test_wrong_password_returns_to_the_wizard(self, client_for, fresh):
        response = admin_of(client_for, fresh).post("/backups/", {"action": "passphrase", "password": "wrong", "generate": "1", "next": "/setup/?step=backups"})
        assert response.status_code == 302 and response["Location"] == "/setup/?step=backups"

    @pytest.mark.parametrize("bad", ["https://evil.test/", "//evil.test/setup/", "/admin/", "/setup/\\\\evil", "javascript:alert(1)", "/setup//evil.test/"])
    def test_only_the_wizard_can_be_the_way_back(self, client_for, fresh, bad):
        response = admin_of(client_for, fresh).post("/backups/", {"action": "settings", "every_hours": "6", "next": bad})
        assert response["Location"] == "/backups/"

    def test_test_backup_shows_backup_working(self, client_for, fresh, google, no_real_tasks, django_capture_on_commit_callbacks):
        from apps.backups import tasks

        connect_drive("tenant_a", google)
        client = admin_of(client_for, fresh)
        with django_capture_on_commit_callbacks(execute=True):
            assert client.post("/setup/?step=backups", {"action": "test_backup"}).status_code == 302
        assert 'http-equiv="refresh"' in client.get("/setup/?step=backups").content.decode()
        tasks.run_task(*no_real_tasks[0])
        page = client.get("/setup/?step=backups").content.decode()
        assert "✓ Backup working" in page and "copied to Google Drive" in page
        with schema_context("tenant_a"):
            assert services.step_done("backups")

    def test_skip(self, client_for, fresh):
        client = admin_of(client_for, fresh)
        assert client.post("/setup/?step=backups", {"action": "skip"})["Location"] == "/setup/?step=connections"
        with schema_context("tenant_a"):
            assert services.progress().backups_skipped_at and not services.step_done("backups")
            assert AuditEvent.objects.filter(action="setup.step_skipped").exists()


@pytest.mark.django_db
class TestConnectionsAndFinish:
    def test_connections_list_and_finish(self, client_for, fresh):
        from apps.vault import services as vault

        with schema_context("tenant_a"):
            vault.create_connection(provider_code="gmail", label="Shop Gmail", config={"email": "shop@gmail.test"}, secrets={"app_password": "abcd efgh ijkl mnop"})
        client = admin_of(client_for, fresh)
        page = client.get("/setup/?step=connections").content.decode()
        assert "✓ Shop Gmail" in page and "/settings/integrations/add/whatsapp_cloud/" in page
        assert client.post("/setup/?step=connections", {"action": "connections"})["Location"] == "/setup/?step=done"
        done = client.get("/setup/?step=done").content.decode()
        assert "Not done yet" in done and "Finish setup" in done
        assert client.post("/setup/?step=done", {"action": "finish"})["Location"] == "/admin/"
        assert client.get("/admin/").status_code == 200
        with schema_context("tenant_a"):
            prog = SetupProgress.objects.get()
            assert prog.completed_at and prog.completed_by_email == "it@a.test"
            assert AuditEvent.objects.filter(action="setup.completed").exists()

    def test_first_open_step(self, fresh):
        with schema_context("tenant_a"):
            assert services.first_open_step() == "business"
            services.save_profile({})
            assert services.first_open_step() == "backups"
            services.skip("backups")
            assert services.first_open_step() == "connections"
            services.mark_connections_seen()
            assert services.first_open_step() == "done"


@pytest.mark.django_db
class TestReminder:
    def test_shown_until_backups_are_set_up(self, client_for, tenant_a, google):
        it = admin_of(client_for, tenant_a)
        page = it.get("/admin/").content.decode()
        assert "Backups to your Google Drive are not set up yet." in page and "/setup/?step=backups" in page
        owner = admin_of(client_for, tenant_a, "business_owner", "owner@a.test")
        assert "Ask your IT Admin" in owner.get("/admin/").content.decode()
        shop = admin_of(client_for, tenant_a, "shop_staff", "shop@a.test")
        assert "not set up yet" not in shop.get("/tickets/").content.decode()
        connect_drive("tenant_a", google)
        assert "not set up yet" not in it.get("/admin/").content.decode()

    def test_not_on_the_platform(self, client_for, public_tenant):
        from tests.test_mfa_admin import platform_staff

        root = platform_staff(client_for, public_tenant, "root@platform.test", "super_admin")
        page = root.get("/admin/").content.decode()
        assert "not set up yet" not in page and "Set up your business" not in page

    def test_setup_link_in_the_header(self, client_for, tenant_a):
        assert "Set up your business" in admin_of(client_for, tenant_a).get("/admin/").content.decode()
        assert "Set up your business" not in admin_of(client_for, tenant_a, "shop_staff", "shop@a.test").get("/tickets/").content.decode()
