"""Secret vault and integrations (task 1.5)."""
import base64
import json
import os

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.db import connection
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.rbac.models import Role, UserRole
from apps.vault import crypto, providers, services
from apps.vault.models import Connection
from tests.conftest import PASSWORD, make_user
from tests.test_rbac import verified_staff_client

SECRET = "sk-test-SUPERSECRET-1234567890abcd"


def new_key(kid):
    return f"{kid}:{base64.b64encode(os.urandom(32)).decode()}"


@pytest.fixture(autouse=True)
def vault_key(settings):
    settings.VAULT_MASTER_KEYS = new_key("k1")
    settings.ALLOW_PRIVATE_NETWORK_URLS = False


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def install(status=200, body=None, raise_exc=None):
        def _http(method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            if raise_exc:
                raise raise_exc
            return FakeResponse(status, body)

        monkeypatch.setattr(providers, "_http", _http)
        return calls

    return install


def create_openai(schema="tenant_a", **kw):
    with schema_context(schema):
        return services.create_connection(provider_code="openai", label="Main AI", config={}, secrets={"api_key": SECRET}, **kw)


def api_client(client_for, tenant, email, role):
    user = make_user(tenant.schema_name, email)
    with schema_context(tenant.schema_name):
        UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
    client = client_for(tenant)
    assert client.post("/api/auth/login/", {"email": email, "password": PASSWORD}).status_code == 200
    return client


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
class TestCrypto:
    def test_round_trip(self, settings):
        sealed = crypto.seal(b"hello", b"tenant_a:1")
        assert crypto.open_sealed(sealed, b"tenant_a:1") == b"hello"
        assert b"hello" not in sealed.ciphertext

    def test_wrong_context_cannot_open(self):
        sealed = crypto.seal(b"hello", b"tenant_a:1")
        with pytest.raises(crypto.VaultError):
            crypto.open_sealed(sealed, b"tenant_b:1")

    def test_tampered_data_cannot_open(self):
        sealed = crypto.seal(b"hello", b"ctx")
        sealed.ciphertext = bytes([sealed.ciphertext[0] ^ 1]) + sealed.ciphertext[1:]
        with pytest.raises(crypto.VaultError):
            crypto.open_sealed(sealed, b"ctx")

    def test_missing_master_key_cannot_open(self, settings):
        sealed = crypto.seal(b"hello", b"ctx")
        settings.VAULT_MASTER_KEYS = new_key("other")
        with pytest.raises(crypto.VaultError, match="not configured"):
            crypto.open_sealed(sealed, b"ctx")

    def test_production_refuses_without_master_key(self, settings):
        settings.VAULT_MASTER_KEYS = ""
        settings.DEBUG = False
        with pytest.raises(ImproperlyConfigured):
            crypto.seal(b"x", b"ctx")

    def test_development_works_without_master_key(self, settings):
        settings.VAULT_MASTER_KEYS = ""
        settings.DEBUG = True
        assert crypto.open_sealed(crypto.seal(b"x", b"ctx"), b"ctx") == b"x"

    @pytest.mark.parametrize("bad", ["nokeyid", "k1:" + base64.b64encode(b"short").decode()])
    def test_bad_key_format_is_rejected(self, settings, bad):
        settings.VAULT_MASTER_KEYS = bad
        with pytest.raises(ImproperlyConfigured):
            crypto.master_keys()

    def test_key_rotation(self, settings):
        old = settings.VAULT_MASTER_KEYS
        sealed = crypto.seal(b"hello", b"ctx")
        settings.VAULT_MASTER_KEYS = f"{new_key('k2')},{old}"
        rewrapped = crypto.rewrap(sealed, b"ctx")
        assert rewrapped.kid == "k2"
        settings.VAULT_MASTER_KEYS = settings.VAULT_MASTER_KEYS.split(",")[0]  # old key removed
        assert crypto.open_sealed(rewrapped, b"ctx") == b"hello"


# ---------------------------------------------------------------------------
# Storing connections
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStorage:
    def test_secret_is_never_stored_in_plain_text(self, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"), connection.cursor() as cursor:
            cursor.execute("SELECT * FROM vault_connection WHERE id = %s", [conn.pk])
            row = cursor.fetchone()
        everything = b"".join(bytes(v) if isinstance(v, (bytes, memoryview)) else str(v).encode() for v in row)
        assert SECRET.encode() not in everything
        assert b"SUPERSECRET" not in everything

    def test_only_a_masked_hint_is_kept(self, tenant_a):
        conn = create_openai()
        assert conn.secret_hints == {"api_key": "••••abcd"}

    def test_server_can_read_the_secret(self, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"):
            assert services.read_secrets(Connection.objects.get(pk=conn.pk)) == {"api_key": SECRET}

    def test_secret_copied_to_another_connection_cannot_be_opened(self, tenant_a):
        a = create_openai()
        with schema_context("tenant_a"):
            b = services.create_connection(provider_code="openai", label="Other", config={}, secrets={"api_key": "sk-other-key-123456"})
            Connection.objects.filter(pk=b.pk).update(
                secret_kid=a.secret_kid, secret_wrapped_key=a.secret_wrapped_key, secret_key_nonce=a.secret_key_nonce,
                secret_nonce=a.secret_nonce, secret_ciphertext=a.secret_ciphertext,
            )
            with pytest.raises(crypto.VaultError):
                services.read_secrets(Connection.objects.get(pk=b.pk))

    def test_secret_copied_to_another_business_cannot_be_opened(self, tenant_a, tenant_b):
        a = create_openai()
        with schema_context("tenant_b"):
            fake = Connection(uid=a.uid, provider="openai", category="ai", label="Copy", secret_kid=a.secret_kid,
                              secret_wrapped_key=a.secret_wrapped_key, secret_key_nonce=a.secret_key_nonce,
                              secret_nonce=a.secret_nonce, secret_ciphertext=a.secret_ciphertext)
            fake.save()
            with pytest.raises(crypto.VaultError):
                services.read_secrets(fake)

    def test_blank_secret_on_update_keeps_the_saved_one(self, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"):
            services.update_connection(conn, label="Renamed", secrets={"api_key": ""})
            assert services.read_secrets(Connection.objects.get(pk=conn.pk)) == {"api_key": SECRET}

    def test_new_secret_replaces_the_old_one(self, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"):
            services.update_connection(conn, secrets={"api_key": "sk-new-value-99998888"})
            fresh = Connection.objects.get(pk=conn.pk)
            assert services.read_secrets(fresh) == {"api_key": "sk-new-value-99998888"}
            assert fresh.secret_hints == {"api_key": "••••8888"}
            assert fresh.status == Connection.Status.NOT_TESTED

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"provider_code": "openai", "secrets": {}},  # required key missing
            {"provider_code": "stripe", "secrets": {}},  # not available yet
            {"provider_code": "nope", "secrets": {}},
            {"provider_code": "openai", "secrets": {"api_key": "sk-1234567890", "extra": "x"}},  # unknown field
        ],
    )
    def test_invalid_input_is_rejected(self, tenant_a, kwargs):
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError):
                services.create_connection(label="x", config={}, **kwargs)

    def test_audit_records_field_names_but_never_values(self, tenant_a):
        create_openai()
        with schema_context("tenant_a"):
            event = AuditEvent.objects.filter(action="integration.create").first()
            assert event.metadata == {"provider": "openai", "saved_fields": ["api_key"]}
            assert not AuditEvent.objects.filter(metadata__icontains="SUPERSECRET").exists()
            for e in AuditEvent.objects.all():
                assert "SUPERSECRET" not in json.dumps(e.changes) + json.dumps(e.metadata)

    def test_rotation_command(self, tenant_a, settings, capsys):
        conn = create_openai()
        old = settings.VAULT_MASTER_KEYS
        settings.VAULT_MASTER_KEYS = f"{new_key('k2')},{old}"
        call_command("rotate_vault_key")
        assert "now use key 'k2'" in capsys.readouterr().out
        settings.VAULT_MASTER_KEYS = settings.VAULT_MASTER_KEYS.split(",")[0]
        with schema_context("tenant_a"):
            assert services.read_secrets(Connection.objects.get(pk=conn.pk)) == {"api_key": SECRET}

    def test_backup_is_used_when_main_fails(self, tenant_a):
        main = create_openai()
        with schema_context("tenant_a"):
            backup = services.create_connection(provider_code="anthropic", label="Backup AI", config={}, secrets={"api_key": "sk-ant-1234567890"}, is_backup=True)
            assert services.active_connection("ai").pk == main.pk
            Connection.objects.filter(pk=main.pk).update(status=Connection.Status.FAILED)
            assert services.active_connection("ai").pk == backup.pk


# ---------------------------------------------------------------------------
# Testing connections
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestConnectionTests:
    def test_successful_test(self, tenant_a, fake_http):
        calls = fake_http(200)
        conn = create_openai()
        with schema_context("tenant_a"):
            result = services.test_connection(conn)
            fresh = Connection.objects.get(pk=conn.pk)
        assert result.ok and fresh.status == "connected" and fresh.last_tested_at
        assert calls[0]["url"] == "https://api.openai.com/v1/models"
        assert calls[0]["headers"]["Authorization"] == f"Bearer {SECRET}"

    def test_rejected_key(self, tenant_a, fake_http):
        fake_http(401)
        conn = create_openai()
        with schema_context("tenant_a"):
            result = services.test_connection(conn)
        assert not result.ok and "refused the key" in result.message

    def test_network_errors_never_leak_the_token(self, tenant_a, fake_http):
        token = "123456:TELEGRAM-SECRET-TOKEN"
        fake_http(raise_exc=requests.ConnectionError(f"Failed for https://api.telegram.org/bot{token}/getMe"))
        with schema_context("tenant_a"):
            conn = services.create_connection(provider_code="telegram", label="Bot", config={}, secrets={"bot_token": token})
            result = services.test_connection(conn)
            assert token not in result.message
            assert not AuditEvent.objects.filter(metadata__icontains="TELEGRAM-SECRET").exists()

    def test_timeout(self, tenant_a, fake_http):
        fake_http(raise_exc=requests.Timeout())
        conn = create_openai()
        with schema_context("tenant_a"):
            assert "10 seconds" in services.test_connection(conn).message

    def test_disabled_connection_is_not_tested(self, tenant_a, fake_http):
        calls = fake_http(200)
        conn = create_openai()
        with schema_context("tenant_a"):
            services.set_disabled(conn, True)
            assert not services.test_connection(conn).ok
        assert calls == []

    def test_whatsapp_uses_the_phone_number_id(self, tenant_a, fake_http):
        calls = fake_http(200)
        with schema_context("tenant_a"):
            conn = services.create_connection(provider_code="whatsapp_cloud", label="Shop", config={"phone_number_id": "1098765"}, secrets={"access_token": "EAAG-secret-token-xyz"})
            assert services.test_connection(conn).ok
        assert calls[0]["url"] == "https://graph.facebook.com/v21.0/1098765"


@pytest.mark.django_db
class TestPrivateNetworkProtection:
    @pytest.mark.parametrize(
        "url",
        ["http://127.0.0.1:11434", "http://localhost:11434", "http://169.254.169.254", "http://10.0.0.5", "http://192.168.1.10", "file:///etc/passwd", "ftp://example.com"],
    )
    def test_internal_addresses_are_refused(self, tenant_a, fake_http, url):
        calls = fake_http(200)
        with schema_context("tenant_a"):
            conn = services.create_connection(provider_code="ollama", label="Local", config={"base_url": url}, secrets={})
            result = services.test_connection(conn)
        assert not result.ok
        assert calls == []  # no request was made

    def test_development_setting_allows_private_addresses(self, tenant_a, fake_http, settings):
        settings.ALLOW_PRIVATE_NETWORK_URLS = True
        calls = fake_http(200)
        with schema_context("tenant_a"):
            conn = services.create_connection(provider_code="ollama", label="Local", config={"base_url": "http://127.0.0.1:11434"}, secrets={})
            assert services.test_connection(conn).ok
        assert calls[0]["url"] == "http://127.0.0.1:11434/api/tags"


def test_http_wrapper_disables_redirects_and_sets_timeout(monkeypatch):
    seen = {}

    def fake_request(method, url, **kwargs):
        seen.update(kwargs)
        return FakeResponse(200)

    monkeypatch.setattr(requests, "request", fake_request)
    providers._http("GET", "https://example.com")
    assert seen["allow_redirects"] is False and seen["timeout"] == 10


# ---------------------------------------------------------------------------
# API and permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestApi:
    def test_api_never_returns_secret_values(self, client_for, tenant_a):
        client = api_client(client_for, tenant_a, "it@a.test", "it_admin")
        created = client.post("/api/integrations/connections/", {"provider": "openai", "label": "AI", "secrets": {"api_key": SECRET}}, content_type="application/json")
        assert created.status_code == 201
        assert SECRET not in created.content.decode()
        listed = client.get("/api/integrations/connections/")
        assert SECRET not in listed.content.decode()
        assert listed.json()[0]["secrets"] == {"api_key": "••••abcd"}
        detail = client.get(f"/api/integrations/connections/{created.json()['id']}/")
        assert SECRET not in detail.content.decode()

    def test_roles_without_integrations_permission_are_refused(self, client_for, tenant_a):
        create_openai()
        client = api_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert client.get("/api/integrations/connections/").status_code == 403
        assert client.post("/api/integrations/connections/", {"provider": "openai", "secrets": {"api_key": SECRET}}, content_type="application/json").status_code == 403

    def test_configure_only_role_cannot_change_secrets(self, client_for, tenant_a):
        conn = create_openai()
        with schema_context("tenant_a"):
            role = Role.objects.create(slug="integrations_helper", name="Helper")
            role.set_permissions({"integrations.view", "integrations.configure"})
        user = make_user("tenant_a", "helper@a.test")
        with schema_context("tenant_a"):
            UserRole.objects.create(user=user, role=role)
        client = client_for(tenant_a)
        client.post("/api/auth/login/", {"email": "helper@a.test", "password": PASSWORD})
        assert client.patch(f"/api/integrations/connections/{conn.pk}/", {"label": "Renamed"}, content_type="application/json").status_code == 200
        response = client.patch(f"/api/integrations/connections/{conn.pk}/", {"secrets": {"api_key": "sk-evil-key-12345678"}}, content_type="application/json")
        assert response.status_code == 403
        assert client.delete(f"/api/integrations/connections/{conn.pk}/").status_code == 403
        with schema_context("tenant_a"):
            assert services.read_secrets(Connection.objects.get(pk=conn.pk)) == {"api_key": SECRET}

    def test_test_endpoint(self, client_for, tenant_a, fake_http):
        fake_http(200)
        conn = create_openai()
        client = api_client(client_for, tenant_a, "it@a.test", "it_admin")
        response = client.post(f"/api/integrations/connections/{conn.pk}/test/")
        assert response.json()["ok"] is True
        assert response.json()["connection"]["status"] == "connected"

    def test_connections_are_separate_per_business(self, client_for, tenant_a, tenant_b):
        create_openai("tenant_a")
        client = api_client(client_for, tenant_b, "it@b.test", "it_admin")
        assert client.get("/api/integrations/connections/").json() == []

    def test_providers_list(self, client_for, tenant_a):
        client = api_client(client_for, tenant_a, "it@a.test", "it_admin")
        codes = {p["code"]: p for p in client.get("/api/integrations/providers/").json()}
        assert {"openai", "anthropic", "gemini", "ollama", "whatsapp_cloud", "viber", "telegram", "smtp", "twilio", "bank_transfer"} <= set(codes)
        assert codes["stripe"]["available"] is False


# ---------------------------------------------------------------------------
# Settings pages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSettingsPages:
    def test_add_page_has_password_fields_and_saves(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        page = client.get("/settings/integrations/add/openai/")
        assert page.status_code == 200
        assert b'type="password"' in page.content
        response = client.post("/settings/integrations/add/openai/", {"label": "AI", "config__model": "gpt-4o-mini", "secret__api_key": SECRET})
        assert response.status_code == 302
        listing = client.get("/settings/integrations/").content.decode()
        assert "••••abcd" in listing and SECRET not in listing

    def test_form_with_errors_does_not_echo_the_typed_key(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        response = client.post("/settings/integrations/add/whatsapp_cloud/", {"label": "Shop", "secret__access_token": SECRET})  # phone number ID missing
        assert response.status_code == 200  # form shown again with an error
        assert SECRET not in response.content.decode()

    def test_edit_page_never_shows_the_secret(self, client_for, tenant_a):
        conn = create_openai()
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        page = client.get(f"/settings/integrations/{conn.pk}/edit/").content.decode()
        assert SECRET not in page and "••••abcd" in page

    def test_pages_need_permission(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert client.get("/settings/integrations/").status_code == 403

    def test_pages_need_mfa_for_staff(self, client_for, tenant_a):
        user = make_user("tenant_a", "it@a.test", staff=True)
        with schema_context("tenant_a"):
            UserRole.objects.create(user=user, role=Role.objects.get(slug="it_admin"))
        client = client_for(tenant_a)
        client.post("/admin/login/", {"username": "it@a.test", "password": PASSWORD})
        assert client.get("/settings/integrations/")["Location"].startswith("/account/mfa/")

    def test_admin_entry_opens_the_settings_page(self, verified_admin_client, tenant_a):
        client = verified_admin_client(tenant_a)
        assert client.get("/admin/vault/connection/")["Location"] == "/settings/integrations/"

    def test_platform_uses_platform_settings_permissions(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        assert client.get("/settings/integrations/").status_code == 200
