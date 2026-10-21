"""
Shared test setup.

Two business tenants (A and B) and the platform tenant are created once per
test session in the test database. Each test runs inside a transaction that
is rolled back, so data does not leak between tests.
"""
import pytest
from django.db import connection
from django.test import Client
from django_tenants.utils import schema_context

PASSWORD = "a-long-test-password-123"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    from apps.tenants.services import create_public_tenant, create_tenant

    with django_db_blocker.unblock():
        create_public_tenant()
        create_tenant("Tenant A Butchery", "tenant_a", "butchery")
        create_tenant("Tenant B Catering", "tenant_b", "catering")
        # The test businesses count as already set up, so the first-login wizard (task 1.16)
        # does not take over the admin home page. tests/test_setup.py undoes this per test.
        from django.utils import timezone

        from apps.setup.models import SetupProgress

        for schema in ("tenant_a", "tenant_b"):
            with schema_context(schema):
                SetupProgress.objects.update_or_create(pk=1, defaults={"completed_at": timezone.now()})
    yield


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    """Use an in-memory cache per test (lockout counters, throttles), with tenant-prefixed keys."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "tests",
            "KEY_FUNCTION": "django_tenants.cache.make_key",
            "REVERSE_KEY_FUNCTION": "django_tenants.cache.reverse_key",
        }
    }
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def vault_master_key(settings):
    """Every test gets a test-only vault master key (DEBUG is off in tests)."""
    if not settings.VAULT_MASTER_KEYS:
        settings.VAULT_MASTER_KEYS = "test:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


@pytest.fixture(autouse=True)
def backup_key(settings, tmp_path):
    """Every test gets a test-only backup key and its own backup folder (task 1.14)."""
    if not settings.BACKUP_ENCRYPTION_KEYS:
        settings.BACKUP_ENCRYPTION_KEYS = "test:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
    settings.BACKUP_DIR = tmp_path / "backups"


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


# ---------------------------------------------------------------------------
# Users and MFA helpers
# ---------------------------------------------------------------------------
def make_user(schema: str, email: str, *, staff=False, superuser=False, password=PASSWORD, **extra):
    from apps.accounts.models import User

    with schema_context(schema):
        if superuser:
            return User.objects.create_superuser(email, password, **extra)
        return User.objects.create_user(email, password, is_staff=staff, **extra)


def add_totp_device(schema: str, user):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    with schema_context(schema):
        return TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=True)


def current_code(device) -> str:
    """The code an authenticator app would show right now."""
    from django_otp.oath import totp

    return str(totp(device.bin_key, device.step, device.t0, device.digits, device.drift)).zfill(device.digits)


def admin_login(client, email, password=PASSWORD):
    return client.post("/admin/login/?next=/admin/", {"username": email, "password": password})


@pytest.fixture
def verified_admin_client(client_for):
    """Log a new superuser in to `tenant`'s admin, with MFA verified. Returns the client."""

    def _make(tenant, email="boss@site.test"):
        user = make_user(tenant.schema_name, email, superuser=True)
        device = add_totp_device(tenant.schema_name, user)
        client = client_for(tenant)
        admin_login(client, email)
        response = client.post("/account/mfa/verify/", {"token": current_code(device), "next": "/admin/"})
        assert response.status_code == 302 and response["Location"] == "/admin/", "MFA verification failed"
        assert client.get("/admin/").status_code == 200
        return client

    return _make


@pytest.fixture(autouse=True)
def no_worker_ping(monkeypatch):
    """Tests have no Celery worker; asking for one would wait 1.5 seconds per check run."""
    import apps.health.checks as health_checks

    monkeypatch.setattr(health_checks, "ping_workers", lambda: 0)


def pass_delete_check(client, page) -> dict:
    """The fields that pass the delete safety check shown on `page` (task 1.18). Tests skip the 5-second wait."""
    import re

    html = page.content.decode()
    token = re.search(r'name="guard_token" value="([^"]+)"', html).group(1)
    a, b = (int(n) for n in re.search(r"What is (\d+) \+ (\d+)\?", html).groups())
    session = client.session
    session["delete_guard"][token]["at"] -= 10
    session.save()
    return {"guard_token": token, "guard_answer": str(a + b)}
