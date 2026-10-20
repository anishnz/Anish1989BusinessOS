"""Tamper-proof audit log (task 1.3)."""
import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.audit.services import audit, verify_chain
from apps.rbac.models import Role
from tests.conftest import PASSWORD, make_user


def raw_sql(sql, params=None):
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, params or [])


@pytest.mark.django_db
class TestAuditWriting:
    def test_event_has_actor_ip_and_hash(self, client_for, tenant_a):
        user = make_user("tenant_a", "sysadmin@a.test")
        with schema_context("tenant_a"):
            from apps.rbac.models import UserRole

            UserRole.objects.create(user=user, role=Role.objects.get(slug="system_admin"))
        client = client_for(tenant_a)
        client.post("/api/auth/login/", {"email": "sysadmin@a.test", "password": PASSWORD})
        client.post("/api/rbac/roles/", {"slug": "helper", "name": "Helper", "permissions": ["crm.view"]}, content_type="application/json")
        with schema_context("tenant_a"):
            event = AuditEvent.objects.filter(action="rbac.role.create").first()
        assert event.actor_email == "sysadmin@a.test"
        assert event.actor_type == "user"
        assert event.ip_address == "127.0.0.1"
        assert event.target_repr == "Helper"
        assert len(event.hash) == 64

    def test_logins_are_audited(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        client.post("/api/auth/login/", {"email": "cashier@a.test", "password": "wrong-password-123"})
        client.post("/api/auth/login/", {"email": "cashier@a.test", "password": PASSWORD})
        with schema_context("tenant_a"):
            actions = list(AuditEvent.objects.filter(actor_email="cashier@a.test").order_by("id").values_list("action", "outcome"))
        assert ("auth.login_failed", "failed") in actions
        assert ("auth.login_success", "success") in actions

    def test_password_change_is_recorded_without_the_password(self, tenant_a):
        user = make_user("tenant_a", "cashier@a.test")
        with schema_context("tenant_a"):
            user.set_password("another-long-password-1")
            user.save()
            event = AuditEvent.objects.filter(action="accounts.user.update", target_id=str(user.pk)).first()
        assert event.changes == {"password": {"changed": True}}
        assert "argon2" not in str(event.changes)

    def test_secrets_are_redacted(self, tenant_a):
        with schema_context("tenant_a"):
            event = audit("integration.test", metadata={"api_key": "sk-123", "nested": {"password": "p", "provider": "openai"}})
        assert event.metadata == {"api_key": "[redacted]", "nested": {"password": "[redacted]", "provider": "openai"}}

    def test_system_actor_outside_requests(self, tenant_a):
        with schema_context("tenant_a"):
            event = audit("backup.completed")
        assert event.actor_type == "system"

    def test_audit_logs_are_separate_per_business(self, tenant_a, tenant_b):
        with schema_context("tenant_a"):
            audit("only.in.a")
        with schema_context("tenant_b"):
            assert not AuditEvent.objects.filter(action="only.in.a").exists()


@pytest.mark.django_db
class TestAuditCannotBeChanged:
    def _event(self):
        with schema_context("tenant_a"):
            return audit("test.event")

    def test_model_refuses_changes(self, tenant_a):
        event = self._event()
        with schema_context("tenant_a"):
            event.action = "changed"
            with pytest.raises(PermissionError):
                event.save()
            with pytest.raises(PermissionError):
                event.delete()
            with pytest.raises(PermissionError):
                AuditEvent.objects.filter(pk=event.pk).update(action="changed")
            with pytest.raises(PermissionError):
                AuditEvent.objects.filter(pk=event.pk).delete()

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE audit_auditevent SET action = 'changed'",
            "DELETE FROM audit_auditevent",
            "TRUNCATE audit_auditevent",
        ],
    )
    def test_database_refuses_changes_even_with_raw_sql(self, tenant_a, sql):
        self._event()
        with schema_context("tenant_a"):
            with pytest.raises(DatabaseError, match="cannot be changed or deleted"):
                raw_sql(sql)


@pytest.mark.django_db
class TestTamperDetection:
    """If someone with database owner rights switches the trigger off and edits rows, the chain shows it."""

    def _make_events(self, n=5):
        with schema_context("tenant_a"):
            return [audit(f"test.event.{i}") for i in range(n)]

    def _tamper(self, sql, params):
        with schema_context("tenant_a"):
            raw_sql("ALTER TABLE audit_auditevent DISABLE TRIGGER USER")
            raw_sql(sql, params)
            raw_sql("ALTER TABLE audit_auditevent ENABLE TRIGGER USER")

    def test_untouched_chain_is_ok(self, tenant_a):
        self._make_events()
        with schema_context("tenant_a"):
            assert verify_chain() == (True, [])

    def test_changed_event_is_detected(self, tenant_a):
        events = self._make_events()
        self._tamper("UPDATE audit_auditevent SET actor_email = 'someone-else@a.test' WHERE id = %s", [events[2].pk])
        with schema_context("tenant_a"):
            ok, problems = verify_chain()
        assert not ok
        assert any(f"Event {events[2].pk}" in p and "changed" in p for p in problems)

    def test_removed_event_is_detected(self, tenant_a):
        events = self._make_events()
        self._tamper("DELETE FROM audit_auditevent WHERE id = %s", [events[2].pk])
        with schema_context("tenant_a"):
            ok, problems = verify_chain()
        assert not ok
        assert any(f"Event {events[3].pk}" in p and "broken" in p for p in problems)

    def test_verify_command_checks_every_schema(self, tenant_a, capsys):
        self._make_events(2)
        call_command("verify_audit_chain")
        out = capsys.readouterr().out
        assert "tenant_a: audit log OK" in out
        assert "public: audit log OK" in out
