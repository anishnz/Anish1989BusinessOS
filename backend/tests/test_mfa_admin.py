"""MFA self-service, the reset command, and the Super Admin's business/user pages."""
import re
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_tenants.utils import schema_context

from apps.accounts import security
from apps.accounts.models import LoginEvent, User
from apps.audit.models import AuditEvent
from apps.licensing.models import Licence
from apps.rbac.models import Role, UserRole
from tests.conftest import PASSWORD, add_totp_device, admin_login, current_code, make_user
from tests.test_auth import let_throttle_window_pass
from tests.test_rbac import give_role, make_role, verified_staff_client

CODE_RE = re.compile(r"^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$")


def login_with_code(client_for, tenant, email, code):
    client = client_for(tenant)
    admin_login(client, email)
    return client, client.post("/account/mfa/verify/", {"token": code, "next": "/admin/"})


# ---------------------------------------------------------------------------
# Backup codes and "My two-step verification"
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBackupCodes:
    def test_codes_are_16_characters_in_groups(self, tenant_a):
        user = make_user("tenant_a", "a@a.test", staff=True)
        with schema_context("tenant_a"):
            codes = security.create_backup_codes(user)
        assert len(codes) == 10 and all(CODE_RE.match(c) for c in codes) and len(set(codes)) == 10

    @pytest.mark.parametrize("style", ["as shown", "no dashes", "lower case with spaces"])
    def test_codes_can_be_typed_in_different_ways_and_work_once(self, client_for, tenant_a, style):
        user = make_user("tenant_a", "a@a.test", staff=True)
        add_totp_device("tenant_a", user)
        with schema_context("tenant_a"):
            code = security.create_backup_codes(user)[0]
        typed = {"as shown": code, "no dashes": code.replace("-", ""), "lower case with spaces": code.replace("-", " ").lower()}[style]
        client, response = login_with_code(client_for, tenant_a, "a@a.test", typed)
        assert response.status_code == 302 and response["Location"] == "/admin/"
        _, again = login_with_code(client_for, tenant_a, "a@a.test", typed)
        assert again.status_code == 200  # used codes do not work twice

    def test_old_short_codes_still_work(self, client_for, tenant_a):
        user = make_user("tenant_a", "a@a.test", staff=True)
        add_totp_device("tenant_a", user)
        with schema_context("tenant_a"):
            device = StaticDevice.objects.create(user=user, name="Backup codes")
            StaticToken.objects.create(device=device, token="b4ktgemp")
        _, response = login_with_code(client_for, tenant_a, "a@a.test", "b4ktgemp")
        assert response.status_code == 302


@pytest.mark.django_db
class TestMyTwoStepPage:
    def _client(self, client_for, tenant):
        user = make_user(tenant.schema_name, "me@a.test", staff=True)
        device = add_totp_device(tenant.schema_name, user)
        client = client_for(tenant)
        admin_login(client, "me@a.test")
        client.post("/account/mfa/verify/", {"token": current_code(device), "next": "/admin/"})
        return client, user, device

    def test_page_and_header_link(self, client_for, tenant_a):
        client, _, _ = self._client(client_for, tenant_a)
        assert "Two-step verification" in client.get("/admin/").content.decode()
        page = client.get("/account/mfa/").content.decode()
        assert "Two-step verification is on" in page and "Move to a new phone" in page

    def test_new_backup_codes_need_the_password(self, client_for, tenant_a):
        client, user, _ = self._client(client_for, tenant_a)
        wrong = client.post("/account/mfa/", {"action": "codes", "password": "wrong"}).content.decode()
        assert "password is not correct" in wrong
        page = client.post("/account/mfa/", {"action": "codes", "password": PASSWORD}).content.decode()
        assert "Print" in page and "Download as a text file" in page
        assert len(re.findall(r"[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}", page)) == 10

    def test_new_qr_code_replaces_the_old_app_only_after_confirming(self, client_for, tenant_a):
        client, user, old = self._client(client_for, tenant_a)
        page = client.post("/account/mfa/", {"action": "new_qr", "password": PASSWORD}).content.decode()
        assert "<svg" in page
        with schema_context("tenant_a"):
            new = TOTPDevice.objects.get(user=user, confirmed=False)
            assert TOTPDevice.objects.filter(pk=old.pk, confirmed=True).exists()  # old app still works meanwhile
        assert "did not match" in client.post("/account/mfa/", {"action": "confirm_qr", "token": "000000"}).content.decode()
        let_throttle_window_pass("tenant_a", new)
        response = client.post("/account/mfa/", {"action": "confirm_qr", "token": current_code(new)})
        assert response.status_code == 302
        with schema_context("tenant_a"):
            assert list(TOTPDevice.objects.filter(user=user).values_list("pk", flat=True)) == [new.pk]
            assert LoginEvent.objects.filter(user=user, event="authenticator_replaced").exists()

    def test_password_attempts_are_limited(self, client_for, tenant_a):
        client, _, _ = self._client(client_for, tenant_a)
        for _ in range(5):
            client.post("/account/mfa/", {"action": "codes", "password": "wrong"})
        page = client.post("/account/mfa/", {"action": "codes", "password": PASSWORD}).content.decode()
        assert "Too many wrong passwords" in page


# ---------------------------------------------------------------------------
# reset_mfa command
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResetCommand:
    def test_resets_a_platform_super_admin(self, public_tenant, capsys):
        user = make_user("public", "boss@platform.test", superuser=True)
        add_totp_device("public", user)
        call_command("reset_mfa", "--email", "BOSS@platform.test")
        assert "reset" in capsys.readouterr().out
        assert not TOTPDevice.objects.filter(user=user).exists()
        event = AuditEvent.objects.filter(action="auth.mfa_reset").latest("id")
        assert event.metadata["by"] == "server command (reset_mfa)" and event.actor_type == "system"

    def test_resets_a_business_user(self, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        add_totp_device("tenant_a", user)
        call_command("reset_mfa", "--email", "staff@a.test", "--schema", "tenant_a")
        with schema_context("tenant_a"):
            assert not TOTPDevice.objects.filter(user=user).exists()

    def test_unknown_email(self, public_tenant):
        with pytest.raises(CommandError, match="No user"):
            call_command("reset_mfa", "--email", "nobody@x.test")


# ---------------------------------------------------------------------------
# Super Admin pages
# ---------------------------------------------------------------------------
@pytest.fixture
def super_admin(verified_admin_client, public_tenant):
    return verified_admin_client(public_tenant, "boss@platform.test")


def platform_staff(client_for, public_tenant, email, role=None):
    return verified_staff_client(client_for, public_tenant, email, role)


@pytest.mark.django_db
class TestSuperAdminPages:
    def test_overview_lists_businesses_and_mfa_counts(self, super_admin, tenant_a):
        make_user("tenant_a", "staff@a.test", staff=True)
        with schema_context("tenant_a"):
            User.objects.filter(email="staff@a.test").update(mfa_exempt=True)
        page = super_admin.get("/platform/people/").content.decode()
        assert "Tenant A Butchery" in page and "Tenant B Catering" in page and "Platform administrators" in page
        assert "Businesses and users" in super_admin.get("/admin/").content.decode()

    def test_user_list_shows_roles_and_mfa(self, super_admin, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        give_role("tenant_a", user, "shop_staff")
        add_totp_device("tenant_a", user)
        page = super_admin.get("/platform/people/tenant_a/").content.decode()
        assert "staff@a.test" in page and "Shop Staff" in page and ">On<" in page

    def test_change_roles_of_a_business_user(self, super_admin, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        give_role("tenant_a", user, "shop_staff")
        with schema_context("tenant_a"):
            manager = Role.objects.get(slug="operations_manager")
        response = super_admin.post(f"/platform/people/tenant_a/{user.pk}/", {"action": "roles", "roles": [manager.pk]}, follow=True)
        assert "Operations Manager" in response.content.decode()
        with schema_context("tenant_a"):
            assert list(UserRole.objects.filter(user=user).values_list("role__slug", flat=True)) == ["operations_manager"]
            event = AuditEvent.objects.filter(action="rbac.userrole.create").latest("id")
            assert (event.actor_type, event.actor_email, event.actor_id) == ("platform", "boss@platform.test", None)
        assert AuditEvent.objects.filter(action="platform.user_changed", metadata__business="tenant_a").exists()

    def test_reset_and_switch_mfa_off_and_on(self, super_admin, client_for, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        add_totp_device("tenant_a", user)
        url = f"/platform/people/tenant_a/{user.pk}/"
        assert "Give a reason" in super_admin.post(url, {"action": "mfa_off", "reason": " "}, follow=True).content.decode()
        super_admin.post(url, {"action": "mfa_off", "reason": "Lost phone, travelling"})
        with schema_context("tenant_a"):
            user.refresh_from_db()
            assert user.mfa_exempt and user.mfa_exempt_by == "boss@platform.test" and not TOTPDevice.objects.filter(user=user).exists()
            assert AuditEvent.objects.filter(action="auth.mfa_switched_off", metadata__reason="Lost phone, travelling").exists()
        # The person can now use the admin with a password only.
        client = client_for(tenant_a)
        admin_login(client, "staff@a.test")
        assert client.get("/admin/").status_code == 200
        assert "switched off for your account" in client.get("/account/mfa/").content.decode()
        page = super_admin.get("/platform/people/tenant_a/").content.decode()
        assert "Switched off" in page
        # Switch on again: MFA is required at the next request.
        super_admin.post(url, {"action": "mfa_on"})
        assert client.get("/admin/")["Location"].startswith("/account/mfa/setup/")

    def test_reset_mfa_of_a_business_user(self, super_admin, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        add_totp_device("tenant_a", user)
        super_admin.post(f"/platform/people/tenant_a/{user.pk}/", {"action": "reset_mfa"})
        with schema_context("tenant_a"):
            assert not TOTPDevice.objects.filter(user=user).exists()
            assert LoginEvent.objects.filter(user=user, event="mfa_reset").exists()

    def test_lock_and_unlock_respects_the_user_limit(self, super_admin, client_for, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        url = f"/platform/people/tenant_a/{user.pk}/"
        super_admin.post(url, {"action": "lock"})
        with schema_context("tenant_a"):
            user.refresh_from_db()
        assert user.is_active is False
        Licence.objects.filter(tenant__schema_name="tenant_a").update(max_users=0)
        assert "allows 0 active users" in super_admin.post(url, {"action": "unlock"}, follow=True).content.decode()
        Licence.objects.filter(tenant__schema_name="tenant_a").update(max_users=50)
        super_admin.post(url, {"action": "unlock"})
        with schema_context("tenant_a"):
            user.refresh_from_db()
        assert user.is_active is True

    def test_super_admin_cannot_lock_self_or_change_own_roles(self, super_admin, public_tenant):
        me = User.objects.get(email="boss@platform.test")
        assert "cannot lock your own" in super_admin.post(f"/platform/people/public/{me.pk}/", {"action": "lock"}, follow=True).content.decode()
        assert "cannot change your own roles" in super_admin.post(f"/platform/people/public/{me.pk}/", {"action": "roles"}, follow=True).content.decode()
        me.refresh_from_db()
        assert me.is_active

    def test_last_super_admin_cannot_be_locked(self, client_for, public_tenant):
        boss = make_user("public", "only-boss@platform.test", superuser=True)
        make_role("public", "user_manager", {"platform_users.view", "platform_users.edit", "tenants.view"})
        manager = platform_staff(client_for, public_tenant, "manager@platform.test", "user_manager")
        response = manager.post(f"/platform/people/public/{boss.pk}/", {"action": "lock"}, follow=True)
        assert "last active Super Admin" in response.content.decode()
        boss.refresh_from_db()
        assert boss.is_active
        # With a second Super Admin, the first one can be locked.
        second = make_user("public", "second@platform.test", staff=True)
        give_role("public", second, "super_admin")
        manager.post(f"/platform/people/public/{boss.pk}/", {"action": "lock"})
        boss.refresh_from_db()
        assert boss.is_active is False

    def test_view_only_platform_role_cannot_change(self, client_for, public_tenant, tenant_a):
        user = make_user("tenant_a", "staff@a.test", staff=True)
        security_admin = platform_staff(client_for, public_tenant, "sec@platform.test", "platform_security_admin")
        assert security_admin.get(f"/platform/people/tenant_a/{user.pk}/").status_code == 200
        assert security_admin.post(f"/platform/people/tenant_a/{user.pk}/", {"action": "reset_mfa"}).status_code == 403
        nobody = platform_staff(client_for, public_tenant, "nobody@platform.test")
        assert nobody.get("/platform/people/").status_code == 403

    def test_pages_need_mfa_and_do_not_exist_on_business_sites(self, client_for, public_tenant, tenant_a):
        make_user("public", "boss2@platform.test", superuser=True)
        client = client_for(public_tenant)
        admin_login(client, "boss2@platform.test")
        assert client.get("/platform/people/")["Location"].startswith("/account/mfa/")
        business_admin = verified_staff_client(client_for, tenant_a, "admin@a.test", "system_admin")
        assert business_admin.get("/platform/people/").status_code == 404

    def test_unknown_business_or_user(self, super_admin, public_tenant):
        assert super_admin.get("/platform/people/nope/").status_code == 404
        assert super_admin.get("/platform/people/tenant_a/999999/").status_code == 404


# ---------------------------------------------------------------------------
# Deleting users (bug fix)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeletingUsers:
    def test_platform_user_can_be_deleted(self, public_tenant):
        user = make_user("public", "old@platform.test", staff=True)
        user.delete()
        assert not User.objects.filter(email="old@platform.test").exists()

    def test_business_user_delete_keeps_their_records(self, tenant_a):
        from apps.catalog.models import Product

        user = make_user("tenant_a", "old@a.test", staff=True)
        with schema_context("tenant_a"):
            product = Product.objects.create(name="Lamb", price=Decimal("1"), created_by=user)
            user.delete()
            product.refresh_from_db()
            assert product.created_by is None
