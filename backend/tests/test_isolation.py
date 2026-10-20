"""
Tenant isolation tests. These must always pass: one business must never see
or log in to another business's data.
"""
import pytest
from django_tenants.utils import schema_context

from apps.accounts.models import User

PASSWORD = "a-long-test-password-123"


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
        from django.test import Client

        response = Client(HTTP_HOST="unknown.localhost", secure=True).get("/health/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestLoginIsolation:
    def _make_admin(self, schema: str, email: str):
        with schema_context(schema):
            User.objects.create_superuser(email, PASSWORD)

    def test_admin_of_tenant_a_can_log_in_to_tenant_a(self, client_for, tenant_a):
        self._make_admin("tenant_a", "boss@a.test")
        client = client_for(tenant_a)
        response = client.post("/admin/login/?next=/admin/", {"username": "boss@a.test", "password": PASSWORD})
        assert response.status_code == 302
        assert client.get("/admin/").status_code == 200

    def test_admin_of_tenant_a_cannot_log_in_to_tenant_b(self, client_for, tenant_a, tenant_b):
        self._make_admin("tenant_a", "boss@a.test")
        client = client_for(tenant_b)
        response = client.post("/admin/login/?next=/admin/", {"username": "boss@a.test", "password": PASSWORD})
        assert response.status_code == 200  # login form shown again with an error
        assert client.get("/admin/").status_code == 302  # still not logged in

    def test_admin_of_tenant_a_cannot_log_in_to_platform(self, client_for, tenant_a, public_tenant):
        self._make_admin("tenant_a", "boss@a.test")
        client = client_for(public_tenant)
        response = client.post("/admin/login/?next=/admin/", {"username": "boss@a.test", "password": PASSWORD})
        assert response.status_code == 200
        assert client.get("/admin/").status_code == 302


@pytest.mark.django_db
class TestTenantRegistryAccess:
    @staticmethod
    def _logged_in_superuser_client(client, schema):
        """Create a superuser in `schema`, log in through the admin form, and confirm it worked."""
        with schema_context(schema):
            User.objects.create_superuser("boss@site.test", PASSWORD)
        client.post("/admin/login/", {"username": "boss@site.test", "password": PASSWORD})
        assert client.get("/admin/").status_code == 200, "login failed"
        return client

    def test_tenant_admin_cannot_see_the_tenant_registry(self, client_for, tenant_a):
        client = self._logged_in_superuser_client(client_for(tenant_a), "tenant_a")
        # 403 (not 302) proves the user is logged in but blocked.
        assert client.get("/admin/tenants/tenant/").status_code == 403
        assert b"/admin/tenants/" not in client.get("/admin/").content

    def test_platform_admin_can_see_the_tenant_registry(self, client_for, public_tenant):
        client = self._logged_in_superuser_client(client_for(public_tenant), "public")
        response = client.get("/admin/tenants/tenant/")
        assert response.status_code == 200
        assert b"Tenant A Butchery" in response.content

    def test_nobody_can_delete_a_tenant_from_admin(self, client_for, public_tenant, tenant_a):
        client = self._logged_in_superuser_client(client_for(public_tenant), "public")
        assert client.get(f"/admin/tenants/tenant/{tenant_a.pk}/delete/").status_code == 403
