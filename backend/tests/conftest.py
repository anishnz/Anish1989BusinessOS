"""
Shared test setup.

Two business tenants (A and B) and the platform tenant are created once per
test session in the test database. Each test runs inside a transaction that
is rolled back, so data does not leak between tests.
"""
import pytest
from django.db import connection
from django.test import Client


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    from apps.tenants.services import create_public_tenant, create_tenant

    with django_db_blocker.unblock():
        create_public_tenant()
        create_tenant("Tenant A Butchery", "tenant_a", "butchery")
        create_tenant("Tenant B Catering", "tenant_b", "catering")
    yield


@pytest.fixture(autouse=True)
def reset_schema_to_public():
    yield
    connection.set_schema_to_public()


@pytest.fixture
def tenant_a(db):
    from apps.tenants.models import Tenant

    return Tenant.objects.get(schema_name="tenant_a")


@pytest.fixture
def tenant_b(db):
    from apps.tenants.models import Tenant

    return Tenant.objects.get(schema_name="tenant_b")


@pytest.fixture
def public_tenant(db):
    from apps.tenants.models import Tenant

    return Tenant.objects.get(schema_name="public")


def host_of(tenant) -> str:
    return tenant.get_primary_domain().domain


class HttpsClient(Client):
    """Test client that sends every request over HTTPS, like production."""

    def generic(self, method, path, data="", content_type="application/octet-stream", secure=True, **kwargs):
        return super().generic(method, path, data, content_type, secure=True, **kwargs)


def https_client(host: str) -> Client:
    """A test client whose requests go to `host` over HTTPS."""
    return HttpsClient(HTTP_HOST=host)


@pytest.fixture
def client_for():
    """Return a test client that sends requests to a tenant's host name over HTTPS."""

    def _make(tenant) -> Client:
        return https_client(host_of(tenant))

    return _make
