"""Sending email through the Gmail / SMTP connection saved in the vault."""
import smtplib

import pytest
from django.core import mail as django_mail
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django_tenants.utils import schema_context, tenant_context

from apps.audit.models import AuditEvent
from apps.licensing.services import invite_system_admin
from apps.vault import mail, providers, services
from tests.conftest import make_user

APP_PASSWORD = "abcd efgh ijkl mnop"


@pytest.fixture(autouse=True)
def vault_backend(settings):
    settings.EMAIL_BACKEND = "apps.vault.mail.VaultEmailBackend"
    settings.EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


class FakeSMTP:
    instances = []
    fail_login = False
    fail_connect = False

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.fail_connect:
            raise OSError("connection refused")
        self.host, self.port, self.tls, self.login_args, self.sent = host, port, False, None, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.login_args = (user, password)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_login, FakeSMTP.fail_connect = [], False, False
    monkeypatch.setattr(providers.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def sent(monkeypatch):
    """Capture what the vault backend would send over SMTP."""
    record = {"kwargs": [], "messages": []}
    real_get_connection = mail.get_connection

    class Capture:
        def __init__(self, **kwargs):
            record["kwargs"].append(kwargs)

        def send_messages(self, messages):
            if record.get("raise"):
                raise smtplib.SMTPException("server said no")
            record["messages"].extend(messages)
            return len(messages)

    def fake_get_connection(backend=None, **kwargs):
        if backend == "django.core.mail.backends.smtp.EmailBackend":
            return Capture(**kwargs)
        return real_get_connection(backend, **kwargs)

    monkeypatch.setattr(mail, "get_connection", fake_get_connection)
    return record


def add_gmail(schema, address="shop@gmail.com", **kw):
    with schema_context(schema):
        return services.create_connection(provider_code="gmail", label="Gmail", config={"email": address, **kw.pop("config", {})}, secrets={"app_password": APP_PASSWORD}, **kw)


@pytest.mark.django_db
class TestGmailProvider:
    def test_test_connection_logs_in_with_the_app_password(self, tenant_a, fake_smtp):
        conn = add_gmail("tenant_a")
        with schema_context("tenant_a"):
            result = services.test_connection(conn)
        assert result.ok
        server = fake_smtp.instances[0]
        assert (server.host, server.port, server.tls) == ("smtp.gmail.com", 587, True)
        assert server.login_args == ("shop@gmail.com", "abcdefghijklmnop")  # spaces removed

    def test_wrong_password_gives_a_clear_message(self, tenant_a, fake_smtp):
        fake_smtp.fail_login = True
        conn = add_gmail("tenant_a")
        with schema_context("tenant_a"):
            result = services.test_connection(conn)
        assert not result.ok and "app password" in result.message
        assert "abcd" not in result.message

    @pytest.mark.parametrize("config", [{"email": "not-an-email"}, {"email": "a@gmail.com", "from_name": "Shop\r\nBcc: x@evil.test"}])
    def test_bad_settings_are_rejected(self, tenant_a, config):
        with schema_context("tenant_a"), pytest.raises(ValidationError):
            services.create_connection(provider_code="gmail", label="G", config=config, secrets={"app_password": APP_PASSWORD})


@pytest.mark.django_db
class TestChoosingTheSender:
    def test_business_uses_its_own_gmail(self, tenant_a, sent):
        add_gmail("tenant_a", config={"from_name": "Gorkha Butchery"})
        with tenant_context(tenant_a):
            django_mail.send_mail("Hi", "Body", None, ["c@x.test"])
        assert sent["kwargs"][0]["host"] == "smtp.gmail.com"
        assert sent["kwargs"][0]["username"] == "shop@gmail.com"
        assert sent["kwargs"][0]["password"] == "abcdefghijklmnop"
        assert sent["messages"][0].from_email == "Gorkha Butchery <shop@gmail.com>"

    def test_business_without_email_uses_the_platform_gmail(self, tenant_a, public_tenant, sent):
        add_gmail("public", address="platform@gmail.com")
        with tenant_context(tenant_a):
            django_mail.send_mail("Hi", "Body", None, ["c@x.test"])
        assert sent["kwargs"][0]["username"] == "platform@gmail.com"
        assert sent["messages"][0].from_email == "Tenant A Butchery via Anish1989 Business OS <platform@gmail.com>"

    def test_disabled_business_connection_falls_back_to_platform(self, tenant_a, public_tenant, sent):
        conn = add_gmail("tenant_a")
        add_gmail("public", address="platform@gmail.com")
        with schema_context("tenant_a"):
            services.set_disabled(conn, True)
        with tenant_context(tenant_a):
            django_mail.send_mail("Hi", "Body", None, ["c@x.test"])
        assert sent["kwargs"][0]["username"] == "platform@gmail.com"

    def test_one_business_never_uses_another_business_gmail(self, tenant_a, tenant_b, sent):
        add_gmail("tenant_a")
        with tenant_context(tenant_b):
            django_mail.send_mail("Hi", "Body", None, ["c@x.test"])
        assert sent["kwargs"] == []  # no SMTP; went to the fallback backend
        assert len(django_mail.outbox) == 1

    def test_no_connection_uses_the_fallback(self, tenant_a, sent):
        with tenant_context(tenant_a):
            django_mail.send_mail("Hi", "Body", None, ["c@x.test"])
        assert sent["kwargs"] == [] and len(django_mail.outbox) == 1

    def test_custom_from_address_becomes_reply_to(self, tenant_a, sent):
        add_gmail("tenant_a")
        with tenant_context(tenant_a):
            django_mail.send_mail("Hi", "Body", "Orders <orders@gorkha.test>", ["c@x.test"])
        message = sent["messages"][0]
        assert message.from_email.endswith("<shop@gmail.com>")
        assert message.reply_to == ["orders@gorkha.test"]


@pytest.mark.django_db
class TestRealEmails:
    def test_password_reset_email_goes_through_the_business_gmail(self, client_for, tenant_a, sent):
        add_gmail("tenant_a")
        make_user("tenant_a", "staff@a.test")
        response = client_for(tenant_a).post("/api/auth/password/reset/", {"email": "staff@a.test"})
        assert response.status_code == 200
        assert sent["messages"][0].to == ["staff@a.test"]
        assert "/account/reset/" in sent["messages"][0].body

    def test_invitation_goes_through_the_platform_gmail(self, tenant_a, public_tenant, sent):
        add_gmail("public", address="platform@gmail.com")
        invite_system_admin(tenant_a, "owner@a.test")
        assert sent["messages"][0].to == ["owner@a.test"]
        assert sent["kwargs"][0]["username"] == "platform@gmail.com"

    def test_failed_invitation_email_is_reported_and_audited(self, tenant_a, public_tenant, sent):
        add_gmail("public", address="platform@gmail.com")
        sent["raise"] = True
        with pytest.raises(ValidationError, match="could not be sent"):
            invite_system_admin(tenant_a, "owner@a.test")
        assert AuditEvent.objects.filter(action="tenant.admin_invite_failed").exists()

    def test_send_test_email_command(self, tenant_a, sent, capsys):
        add_gmail("tenant_a")
        call_command("send_test_email", "--to", "me@x.test", "--schema", "tenant_a")
        assert "Test email sent" in capsys.readouterr().out
        assert sent["messages"][0].to == ["me@x.test"]

    def test_send_test_email_failure_hides_details(self, tenant_a, sent):
        add_gmail("tenant_a")
        sent["raise"] = True
        with pytest.raises(CommandError, match="SMTPException"):
            call_command("send_test_email", "--to", "me@x.test", "--schema", "tenant_a")
