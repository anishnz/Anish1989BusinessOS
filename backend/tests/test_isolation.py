"""
Tenant isolation tests. These must always pass: one business must never see
or log in to another business's data.
"""
import pytest
from django_tenants.utils import schema_context

from apps.accounts.models import User
from tests.conftest import PASSWORD, admin_login, https_client, make_user


@pytest.mark.django_db
class TestDataIsolation:
    def test_user_in_tenant_a_is_invisible_in_tenant_b_and_public(self, tenant_a, tenant_b):
        with schema_context("tenant_a"):
            User.objects.create_user("owner@a.test", PASSWORD)
            assert User.objects.filter(email="owner@a.test").exists()

        with schema_context("tenant_b"):
            assert not User.objects.filter(email="owner@a.test").exists()

        with schema_context("public"):
            assert not User.objects.filter(email="owner@a.test").exists()

    def test_same_email_can_exist_separately_in_two_tenants(self, tenant_a, tenant_b):
        with schema_context("tenant_a"):
            a = User.objects.create_user("same@person.test", PASSWORD, first_name="A")
        with schema_context("tenant_b"):
            b = User.objects.create_user("same@person.test", PASSWORD, first_name="B")
            assert User.objects.get(email="same@person.test").first_name == "B"
        with schema_context("tenant_a"):
            assert User.objects.get(email="same@person.test").first_name == "A"
        assert a.pk is not None and b.pk is not None


@pytest.mark.django_db
class TestHostRouting:
    def test_each_host_is_routed_to_its_own_schema(self, client_for, tenant_a, tenant_b, public_tenant):
        for tenant in (tenant_a, tenant_b, public_tenant):
            response = client_for(tenant).get("/health/")
            assert response.status_code == 200
            assert response.wsgi_request.tenant.schema_name == tenant.schema_name

    def test_unknown_host_returns_404(self, db):
        response = https_client("unknown.localhost").get("/health/")
        assert response.status_code == 404

    def test_requests_are_really_https(self, client_for, tenant_a):
        # Guards the test setup itself: production redirects plain HTTP.
        assert client_for(tenant_a).get("/health/").wsgi_request.is_secure()


@pytest.mark.django_db
class TestLoginIsolation:
    def test_admin_of_tenant_a_can_log_in_to_tenant_a(self, client_for, tenant_a):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        assert admin_login(client, "boss@a.test").status_code == 302
        # Logged in with a password; next step is MFA setup (not the login page).
        assert client.get("/admin/")["Location"].startswith("/account/mfa/setup/")

    def test_admin_of_tenant_a_cannot_log_in_to_tenant_b(self, client_for, tenant_a, tenant_b):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_b)
        assert admin_login(client, "boss@a.test").status_code == 200  # form shown again with an error
        assert client.get("/admin/")["Location"].startswith("/admin/login/")  # still not logged in

    def test_admin_of_tenant_a_cannot_log_in_to_platform(self, client_for, tenant_a, public_tenant):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(public_tenant)
        assert admin_login(client, "boss@a.test").status_code == 200
        assert client.get("/admin/")["Location"].startswith("/admin/login/")

    def test_api_login_of_tenant_a_user_fails_on_tenant_b(self, client_for, tenant_a, tenant_b):
        make_user("tenant_a", "staff@a.test")
        response = client_for(tenant_b).post("/api/auth/login/", {"email": "staff@a.test", "password": PASSWORD})
        assert response.status_code == 400


@pytest.mark.django_db
class TestTenantRegistryAccess:
    def test_tenant_admin_cannot_see_the_tenant_registry(self, verified_admin_client, tenant_a):
        client = verified_admin_client(tenant_a)
        # 403 (not 302) proves the user is logged in and verified but blocked.
        assert client.get("/admin/tenants/tenant/").status_code == 403
        assert b"/admin/tenants/" not in client.get("/admin/").content

    def test_platform_admin_can_see_the_tenant_registry(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        response = client.get("/admin/tenants/tenant/")
        assert response.status_code == 200
        assert b"Tenant A Butchery" in response.content

    def test_nobody_can_delete_a_tenant_from_admin(self, verified_admin_client, public_tenant, tenant_a):
        client = verified_admin_client(public_tenant)
        assert client.get(f"/admin/tenants/tenant/{tenant_a.pk}/delete/").status_code == 403


@pytest.mark.django_db
class TestMfaIsolation:
    def test_mfa_devices_are_stored_per_tenant(self, tenant_a, tenant_b):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from tests.conftest import add_totp_device

        user = make_user("tenant_a", "boss@a.test", superuser=True)
        add_totp_device("tenant_a", user)
        with schema_context("tenant_a"):
            assert TOTPDevice.objects.count() == 1
        with schema_context("tenant_b"):
            assert TOTPDevice.objects.count() == 0
