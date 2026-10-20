"""Login, lockout, MFA, password reset and login history (task 1.2)."""
import re

import pytest
from django.core import mail
from django_tenants.utils import schema_context

from apps.accounts.models import LoginEvent, User
from tests.conftest import PASSWORD, add_totp_device, admin_login, current_code, make_user


def api_login(client, email, password=PASSWORD):
    return client.post("/api/auth/login/", {"email": email, "password": password})


def let_throttle_window_pass(schema, device):
    """django-otp delays retries after a wrong code. Pretend that delay has passed."""
    from datetime import timedelta

    from django.utils import timezone

    with schema_context(schema):
        device.refresh_from_db()
        if device.throttling_failure_timestamp:
            device.throttling_failure_timestamp = timezone.now() - timedelta(minutes=10)
            device.save(update_fields=["throttling_failure_timestamp"])


def events(schema, email):
    with schema_context(schema):
        return list(LoginEvent.objects.filter(email=email).order_by("created_at").values_list("event", flat=True))


# ---------------------------------------------------------------------------
# Password login and lockout
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPasswordLogin:
    def test_csrf_endpoint_sets_cookie(self, client_for, tenant_a):
        response = client_for(tenant_a).get("/api/auth/csrf/")
        assert response.status_code == 200
        assert "csrftoken" in response.cookies

    def test_normal_user_logs_in_without_mfa(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        response = api_login(client, "cashier@a.test")
        assert response.status_code == 200
        assert response.json()["mfa"]["required"] is False
        assert client.get("/api/auth/me/").json()["user"]["email"] == "cashier@a.test"

    def test_login_email_is_case_insensitive(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        assert api_login(client_for(tenant_a), "  Cashier@A.TEST ").status_code == 200

    def test_wrong_password_and_unknown_email_get_the_same_answer(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        wrong = api_login(client, "cashier@a.test", "wrong-password-123")
        unknown = api_login(client, "nobody@a.test", "wrong-password-123")
        assert wrong.status_code == unknown.status_code == 400
        assert wrong.json() == unknown.json() == {"detail": "Invalid email or password.", "code": "invalid_credentials"}

    def test_inactive_user_cannot_log_in(self, client_for, tenant_a):
        make_user("tenant_a", "left@a.test", is_active=False)
        assert api_login(client_for(tenant_a), "left@a.test").status_code == 400

    def test_lockout_after_five_failures_even_with_right_password(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        for _ in range(5):
            assert api_login(client, "cashier@a.test", "wrong-password-123").status_code == 400
        response = api_login(client, "cashier@a.test")
        assert response.status_code == 429
        assert response.json()["code"] == "locked_out"
        assert events("tenant_a", "cashier@a.test")[-1] == LoginEvent.Event.LOCKED_OUT

    def test_lockout_also_blocks_admin_login_page(self, client_for, tenant_a):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        for _ in range(5):
            admin_login(client, "boss@a.test", "wrong-password-123")
        assert admin_login(client, "boss@a.test").status_code == 200  # refused, form shown again
        assert client.get("/admin/")["Location"].startswith("/admin/login/")

    def test_lockout_in_one_business_does_not_affect_another(self, client_for, tenant_a, tenant_b):
        make_user("tenant_a", "same@person.test")
        make_user("tenant_b", "same@person.test")
        for _ in range(5):
            api_login(client_for(tenant_a), "same@person.test", "wrong-password-123")
        assert api_login(client_for(tenant_a), "same@person.test").status_code == 429
        assert api_login(client_for(tenant_b), "same@person.test").status_code == 200

    def test_successful_login_resets_the_failure_count(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        for _ in range(4):
            api_login(client, "cashier@a.test", "wrong-password-123")
        assert api_login(client, "cashier@a.test").status_code == 200
        client.post("/api/auth/logout/")
        for _ in range(4):
            api_login(client, "cashier@a.test", "wrong-password-123")
        assert api_login(client, "cashier@a.test").status_code == 200

    def test_logout(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        api_login(client, "cashier@a.test")
        assert client.post("/api/auth/logout/").status_code == 204
        assert client.get("/api/auth/me/").status_code == 403


# ---------------------------------------------------------------------------
# Password storage and login history
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPasswordStorageAndHistory:
    def test_new_passwords_use_argon2(self, tenant_a):
        user = make_user("tenant_a", "cashier@a.test")
        assert user.password.startswith("argon2$")

    def test_login_history_records_success_failure_and_logout(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        api_login(client, "cashier@a.test", "wrong-password-123")
        api_login(client, "cashier@a.test")
        client.post("/api/auth/logout/")
        assert events("tenant_a", "cashier@a.test") == ["login_failed", "login_success", "logout"]

    def test_login_history_never_stores_passwords(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        api_login(client_for(tenant_a), "cashier@a.test", "my-secret-typo-999")
        with schema_context("tenant_a"):
            for row in LoginEvent.objects.values():
                assert "my-secret-typo-999" not in str(row)

    def test_login_history_is_kept_per_tenant(self, client_for, tenant_a, tenant_b):
        make_user("tenant_a", "cashier@a.test")
        api_login(client_for(tenant_a), "cashier@a.test")
        assert events("tenant_a", "cashier@a.test") == ["login_success"]
        assert events("tenant_b", "cashier@a.test") == []


# ---------------------------------------------------------------------------
# MFA for staff (API)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStaffMfaApi:
    def test_staff_login_requires_mfa_setup(self, client_for, tenant_a):
        make_user("tenant_a", "manager@a.test", staff=True)
        response = api_login(client_for(tenant_a), "manager@a.test")
        assert response.status_code == 200
        mfa = response.json()["mfa"]
        assert mfa == {"required": True, "enabled": False, "verified": False, "setup_required": True, "backup_codes_remaining": 0}

    def test_unverified_staff_is_blocked_from_other_apis(self, client_for, tenant_a):
        make_user("tenant_a", "manager@a.test", staff=True)
        client = client_for(tenant_a)
        api_login(client, "manager@a.test")
        response = client.get("/api/orders/")
        assert response.status_code == 403
        assert response.json()["code"] == "mfa_required"

    def test_full_totp_setup_flow(self, client_for, tenant_a):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        make_user("tenant_a", "manager@a.test", staff=True)
        client = client_for(tenant_a)
        api_login(client, "manager@a.test")

        setup = client.post("/api/auth/mfa/totp/setup/").json()
        assert setup["otpauth_url"].startswith("otpauth://totp/")
        assert "Tenant%20A%20Butchery" in setup["otpauth_url"]  # business name shown in the app
        assert setup["qr_svg"].startswith("<svg")

        with schema_context("tenant_a"):
            device = TOTPDevice.objects.get(user__email="manager@a.test", confirmed=False)
        assert client.post("/api/auth/mfa/totp/confirm/", {"token": "000000"}).status_code == 400
        let_throttle_window_pass("tenant_a", device)

        response = client.post("/api/auth/mfa/totp/confirm/", {"token": current_code(device)})
        assert response.status_code == 200
        body = response.json()
        assert body["mfa"]["verified"] is True and body["mfa"]["enabled"] is True
        assert len(body["backup_codes"]) == 10
        response = client.get("/api/orders/")  # no longer blocked by MFA; refused only because the user has no role
        assert response.status_code == 403 and response.json().get("code") != "mfa_required"

    def test_verify_with_authenticator_code(self, client_for, tenant_a):
        user = make_user("tenant_a", "manager@a.test", staff=True)
        device = add_totp_device("tenant_a", user)
        client = client_for(tenant_a)
        assert api_login(client, "manager@a.test").json()["mfa"]["setup_required"] is False

        bad = client.post("/api/auth/mfa/verify/", {"token": "123456"})
        assert bad.status_code == 400
        let_throttle_window_pass("tenant_a", device)
        good = client.post("/api/auth/mfa/verify/", {"token": current_code(device)})
        assert good.status_code == 200 and good.json()["mfa"]["verified"] is True
        assert events("tenant_a", "manager@a.test")[-2:] == ["mfa_failed", "mfa_success"]

    def test_wrong_codes_slow_down_guessing(self, client_for, tenant_a):
        """After a wrong code, even the right code is refused until a short delay passes."""
        user = make_user("tenant_a", "manager@a.test", staff=True)
        device = add_totp_device("tenant_a", user)
        client = client_for(tenant_a)
        api_login(client, "manager@a.test")
        assert client.post("/api/auth/mfa/verify/", {"token": "123456"}).status_code == 400
        assert client.post("/api/auth/mfa/verify/", {"token": current_code(device)}).status_code == 400
        let_throttle_window_pass("tenant_a", device)
        assert client.post("/api/auth/mfa/verify/", {"token": current_code(device)}).status_code == 200

    def test_backup_code_works_only_once(self, client_for, tenant_a):
        from apps.accounts.security import create_backup_codes

        user = make_user("tenant_a", "manager@a.test", staff=True)
        add_totp_device("tenant_a", user)
        with schema_context("tenant_a"):
            code = create_backup_codes(user)[0]

        first = client_for(tenant_a)
        api_login(first, "manager@a.test")
        assert first.post("/api/auth/mfa/verify/", {"token": code}).status_code == 200

        second = client_for(tenant_a)
        api_login(second, "manager@a.test")
        assert second.post("/api/auth/mfa/verify/", {"token": code}).status_code == 400


@pytest.mark.django_db
class TestMfaCannotBeBypassed:
    """With only a password, an attacker must not be able to add their own authenticator."""

    def _password_only_session(self, client_for, tenant):
        user = make_user(tenant.schema_name, "manager@a.test", staff=True)
        add_totp_device(tenant.schema_name, user)
        client = client_for(tenant)
        api_login(client, "manager@a.test")
        return client

    def test_api_setup_refused(self, client_for, tenant_a):
        client = self._password_only_session(client_for, tenant_a)
        assert client.post("/api/auth/mfa/totp/setup/").status_code == 403

    def test_api_confirm_refused(self, client_for, tenant_a):
        client = self._password_only_session(client_for, tenant_a)
        assert client.post("/api/auth/mfa/totp/confirm/", {"token": "123456"}).status_code == 403

    def test_api_backup_codes_refused(self, client_for, tenant_a):
        client = self._password_only_session(client_for, tenant_a)
        assert client.post("/api/auth/mfa/backup-codes/").status_code == 403

    def test_setup_page_sends_to_verify(self, client_for, tenant_a):
        client = self._password_only_session(client_for, tenant_a)
        response = client.get("/account/mfa/setup/")
        assert response.status_code == 302
        assert response["Location"].startswith("/account/mfa/verify/")

    def test_admin_blocked_until_verified(self, client_for, tenant_a):
        client = self._password_only_session(client_for, tenant_a)
        assert client.get("/admin/")["Location"].startswith("/account/mfa/verify/")


# ---------------------------------------------------------------------------
# MFA for the admin site (HTML pages)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminMfaPages:
    def test_first_admin_login_goes_to_setup_then_admin_works(self, client_for, tenant_a):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        assert client.get("/admin/")["Location"] == "/account/mfa/setup/?next=/admin/"

        page = client.get("/account/mfa/setup/?next=/admin/")
        assert page.status_code == 200
        assert b"<svg" in page.content
        with schema_context("tenant_a"):
            device = TOTPDevice.objects.get(user__email="boss@a.test", confirmed=False)

        done = client.post("/account/mfa/setup/", {"token": current_code(device), "next": "/admin/"})
        assert done.status_code == 200
        assert b"backup codes" in done.content.lower()
        assert len(done.context["codes"]) == 10
        assert client.get("/admin/").status_code == 200

    def test_wrong_setup_code_shows_error(self, client_for, tenant_a):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        response = client.post("/account/mfa/setup/", {"token": "000000"})
        assert response.status_code == 200
        assert b"did not match" in response.content
        assert client.get("/admin/").status_code == 302

    def test_returning_admin_verifies_with_code(self, client_for, tenant_a):
        user = make_user("tenant_a", "boss@a.test", superuser=True)
        device = add_totp_device("tenant_a", user)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        assert client.get("/admin/")["Location"].startswith("/account/mfa/verify/")
        response = client.post("/account/mfa/verify/", {"token": current_code(device), "next": "/admin/"})
        assert response["Location"] == "/admin/"
        assert client.get("/admin/").status_code == 200

    def test_verify_page_does_not_redirect_to_other_sites(self, client_for, tenant_a):
        user = make_user("tenant_a", "boss@a.test", superuser=True)
        device = add_totp_device("tenant_a", user)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        response = client.post("/account/mfa/verify/", {"token": current_code(device), "next": "https://evil.example/steal"})
        assert response["Location"] == "/admin/"

    def test_mfa_can_be_switched_off_by_setting(self, client_for, tenant_a, settings):
        settings.MFA_REQUIRED_FOR_STAFF = False
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        assert client.get("/admin/").status_code == 200

    def test_login_history_is_read_only_in_admin(self, verified_admin_client, tenant_a):
        client = verified_admin_client(tenant_a)
        assert client.get("/admin/accounts/loginevent/").status_code == 200
        assert client.get("/admin/accounts/loginevent/add/").status_code == 403


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPasswordReset:
    def test_reset_email_links_to_the_users_own_business_site(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        response = client_for(tenant_a).post("/api/auth/password/reset/", {"email": "cashier@a.test"})
        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["cashier@a.test"]
        assert "https://tenant-a.localhost/account/reset/" in mail.outbox[0].body

    def test_unknown_email_gets_same_answer_and_no_email(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        known = client_for(tenant_a).post("/api/auth/password/reset/", {"email": "cashier@a.test"}).json()
        unknown = client_for(tenant_a).post("/api/auth/password/reset/", {"email": "nobody@a.test"}).json()
        assert known == unknown
        assert len(mail.outbox) == 1

    def test_reset_for_tenant_a_user_does_nothing_on_tenant_b(self, client_for, tenant_a, tenant_b):
        make_user("tenant_a", "cashier@a.test")
        client_for(tenant_b).post("/api/auth/password/reset/", {"email": "cashier@a.test"})
        assert len(mail.outbox) == 0

    def test_full_reset_flow_sets_new_password(self, client_for, tenant_a):
        make_user("tenant_a", "cashier@a.test")
        client = client_for(tenant_a)
        client.post("/api/auth/password/reset/", {"email": "cashier@a.test"})
        link = re.search(r"https://tenant-a\.localhost(/account/reset/\S+/)", mail.outbox[0].body).group(1)

        form_page = client.get(link, follow=True)
        assert form_page.status_code == 200
        set_password_url = form_page.redirect_chain[-1][0]
        new_password = "brand-new-password-456"
        done = client.post(set_password_url, {"new_password1": new_password, "new_password2": new_password})
        assert done.status_code == 302

        assert api_login(client_for(tenant_a), "cashier@a.test", PASSWORD).status_code == 400
        assert api_login(client_for(tenant_a), "cashier@a.test", new_password).status_code == 200

    def test_admin_login_page_shows_forgot_password_link(self, client_for, tenant_a):
        assert b"/admin/password_reset/" in client_for(tenant_a).get("/admin/login/").content


@pytest.mark.django_db
def test_user_email_is_stored_lowercase(tenant_a):
    user = make_user("tenant_a", "Mixed.Case@A.Test")
    with schema_context("tenant_a"):
        assert User.objects.get(pk=user.pk).email == "mixed.case@a.test"


# ---------------------------------------------------------------------------
# Admin management of MFA
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminMfaManagement:
    def test_authenticator_secrets_are_not_visible_in_admin(self, verified_admin_client, tenant_a):
        client = verified_admin_client(tenant_a)
        assert client.get("/admin/otp_totp/totpdevice/").status_code == 404
        assert client.get("/admin/otp_static/staticdevice/").status_code == 404

    def test_admin_can_reset_another_users_mfa(self, verified_admin_client, tenant_a):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        client = verified_admin_client(tenant_a, email="boss@a.test")
        staff = make_user("tenant_a", "manager@a.test", staff=True)
        add_totp_device("tenant_a", staff)
        response = client.post(
            "/admin/accounts/user/",
            {"action": "reset_mfa", "_selected_action": [staff.pk]},
            follow=True,
        )
        assert response.status_code == 200
        with schema_context("tenant_a"):
            assert not TOTPDevice.objects.filter(user=staff).exists()
            assert TOTPDevice.objects.filter(user__email="boss@a.test").exists()

    def test_admin_cannot_reset_own_mfa(self, verified_admin_client, tenant_a):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        client = verified_admin_client(tenant_a, email="boss@a.test")
        with schema_context("tenant_a"):
            me = User.objects.get(email="boss@a.test")
        client.post("/admin/accounts/user/", {"action": "reset_mfa", "_selected_action": [me.pk]}, follow=True)
        with schema_context("tenant_a"):
            assert TOTPDevice.objects.filter(user=me).exists()

    def test_mfa_pages_hide_the_admin_menu(self, client_for, tenant_a):
        make_user("tenant_a", "boss@a.test", superuser=True)
        client = client_for(tenant_a)
        admin_login(client, "boss@a.test")
        page = client.get("/account/mfa/setup/")
        assert b'id="nav-sidebar"' not in page.content
