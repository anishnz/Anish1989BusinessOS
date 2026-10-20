"""Licences, module on/off, limits and the business lifecycle (task 1.4)."""
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.licensing import services
from apps.licensing.models import Licence, TenantModule
from apps.rbac import policy
from apps.rbac.models import Role, UserRole
from apps.tenants.models import Tenant
from tests.conftest import PASSWORD, make_user


def give_role(schema, user, slug):
    with schema_context(schema):
        UserRole.objects.create(user=user, role=Role.objects.get(slug=slug))


def logged_in(client_for, tenant, email, role=None):
    user = make_user(tenant.schema_name, email)
    if role:
        give_role(tenant.schema_name, user, role)
    client = client_for(tenant)
    assert client.post("/api/auth/login/", {"email": email, "password": PASSWORD}).status_code == 200
    return client


def set_licence(tenant, **fields):
    Licence.objects.filter(tenant=tenant).update(**fields)


# ---------------------------------------------------------------------------
# New businesses
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNewBusiness:
    def test_new_business_gets_a_30_day_trial(self, tenant_a):
        licence = tenant_a.licence
        assert tenant_a.status == "trial"
        assert licence.plan_name == "Trial"
        days = (licence.trial_ends_at - licence.starts_at).days
        assert days == 30
        assert services.access_state(tenant_a) == "trial"

    def test_industry_template_chooses_modules(self, tenant_a, tenant_b):
        a = services.active_modules(tenant_a)
        b = services.active_modules(tenant_b)
        assert {"orders", "inventory", "products"} <= a and "learning" not in a  # butchery
        assert "events" in b  # catering

    def test_core_modules_are_always_on(self, tenant_a):
        assert {"users", "roles", "settings", "integrations", "audit"} <= services.active_modules(tenant_a)

    def test_platform_has_no_licence_and_is_always_active(self, public_tenant):
        assert not Licence.objects.filter(tenant=public_tenant).exists()
        assert services.access_state(public_tenant) == "active"


# ---------------------------------------------------------------------------
# Licence states
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLicenceStates:
    def _licence(self, tenant, status, **fields):
        Tenant.objects.filter(pk=tenant.pk).update(status=status)
        set_licence(tenant, **fields)
        return Licence.objects.select_related("tenant").get(tenant=tenant)

    def test_trial_then_grace_then_expired(self, tenant_a):
        now = timezone.now()
        licence = self._licence(tenant_a, "trial", trial_ends_at=now + timedelta(days=1), grace_days=7)
        assert licence.state(now) == "trial"
        assert licence.state(now + timedelta(days=2)) == "grace"
        assert licence.state(now + timedelta(days=9)) == "expired"

    def test_paid_licence_without_end_date_stays_active(self, tenant_a):
        licence = self._licence(tenant_a, "active", ends_at=None)
        assert licence.state(timezone.now() + timedelta(days=3650)) == "active"

    def test_paid_licence_with_end_date_expires_after_grace(self, tenant_a):
        now = timezone.now()
        licence = self._licence(tenant_a, "active", ends_at=now, grace_days=3)
        assert licence.state(now + timedelta(days=1)) == "grace"
        assert licence.state(now + timedelta(days=4)) == "expired"

    def test_suspended_and_cancelled(self, tenant_a):
        assert self._licence(tenant_a, "suspended").state() == "suspended"
        assert self._licence(tenant_a, "cancelled").state() == "cancelled"


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBlocking:
    def _expire(self, tenant):
        set_licence(tenant, trial_ends_at=timezone.now() - timedelta(days=30), grace_days=7)

    def test_expired_business_is_blocked_everywhere(self, client_for, tenant_a):
        client = logged_in(client_for, tenant_a, "owner@a.test", "system_admin")
        self._expire(tenant_a)
        api = client.get("/api/rbac/roles/")
        assert api.status_code == 403 and api.json()["code"] == "account_expired"
        page = client.get("/admin/")
        assert page.status_code == 403 and b"expired" in page.content
        login_page = client_for(tenant_a).get("/admin/login/")
        assert login_page.status_code == 403

    def test_health_check_still_works_when_blocked(self, client_for, tenant_a):
        self._expire(tenant_a)
        assert client_for(tenant_a).get("/health/").status_code == 200

    def test_grace_period_works_with_a_warning_header(self, client_for, tenant_a):
        client = logged_in(client_for, tenant_a, "owner@a.test", "system_admin")
        set_licence(tenant_a, trial_ends_at=timezone.now() - timedelta(days=1), grace_days=7)
        response = client.get("/api/rbac/roles/")
        assert response.status_code == 200
        assert response["X-Account-Status"] == "grace"

    def test_suspend_requires_a_reason_and_is_audited(self, client_for, tenant_a):
        with pytest.raises(ValidationError):
            services.suspend(tenant_a, "  ")
        services.suspend(tenant_a, "Unpaid invoice INV-1")
        assert client_for(tenant_a).get("/api/auth/me/").json()["code"] == "account_suspended"
        with schema_context("public"):
            event = AuditEvent.objects.filter(action="tenant.suspend").first()
        assert event.metadata == {"reason": "Unpaid invoice INV-1"}
        assert event.target_id == str(tenant_a.pk)

    def test_reactivate_restores_the_previous_status(self, client_for, tenant_a):
        services.suspend(tenant_a, "Check")
        services.reactivate(Tenant.objects.get(pk=tenant_a.pk))
        tenant = Tenant.objects.get(pk=tenant_a.pk)
        assert tenant.status == "trial"
        assert tenant.licence.suspension_reason == ""
        assert client_for(tenant).get("/api/auth/csrf/").status_code == 200

    def test_mark_paid_makes_licence_active(self, tenant_a):
        services.reactivate(tenant_a, paid=True)
        assert Tenant.objects.get(pk=tenant_a.pk).status == "active"
        assert services.access_state(Tenant.objects.get(pk=tenant_a.pk)) == "active"

    def test_extend_trial(self, tenant_a):
        before = tenant_a.licence.trial_ends_at
        services.extend_trial(tenant_a, 14)
        assert (Licence.objects.get(tenant=tenant_a).trial_ends_at - before).days == 14
        with pytest.raises(ValidationError):
            services.extend_trial(tenant_a, 365)

    def test_one_business_blocked_does_not_affect_another(self, client_for, tenant_a, tenant_b):
        services.suspend(tenant_a, "Check")
        assert client_for(tenant_a).get("/api/auth/csrf/").status_code == 403
        assert client_for(tenant_b).get("/api/auth/csrf/").status_code == 200

    def test_platform_site_is_never_blocked(self, client_for, public_tenant, tenant_a):
        services.suspend(tenant_a, "Check")
        assert client_for(public_tenant).get("/api/auth/csrf/").status_code == 200


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestModules:
    def test_business_admin_can_switch_a_module_off_and_on(self, client_for, tenant_a):
        admin = logged_in(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        rep = make_user("tenant_a", "rep@a.test")
        give_role("tenant_a", rep, "sales_rep")

        off = admin.patch("/api/tenant/modules/crm/", {"enabled": False}, content_type="application/json")
        assert off.status_code == 200 and off.json()["enabled"] is False
        with schema_context("tenant_a"):
            assert policy.check(rep, "crm.view").reason == "module_disabled"

        on = admin.patch("/api/tenant/modules/crm/", {"enabled": True}, content_type="application/json")
        assert on.json()["enabled"] is True
        with schema_context("tenant_a"):
            policy.clear_cache(rep)
            assert policy.has_perm(rep, "crm.view")

    def test_switching_modules_is_audited(self, client_for, tenant_a):
        admin = logged_in(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        admin.patch("/api/tenant/modules/marketing/", {"enabled": False}, content_type="application/json")
        event = AuditEvent.objects.filter(action="licence.module_switched").first()
        assert event.changes == {"marketing": False}

    def test_cannot_switch_on_a_module_not_in_the_licence(self, client_for, tenant_a):
        admin = logged_in(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        response = admin.patch("/api/tenant/modules/learning/", {"enabled": True}, content_type="application/json")
        assert response.status_code == 400
        assert "licence does not include" in response.json()["detail"]

    def test_core_modules_cannot_be_switched_off(self, client_for, tenant_a):
        admin = logged_in(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        assert admin.patch("/api/tenant/modules/audit/", {"enabled": False}, content_type="application/json").status_code == 400

    def test_switching_modules_needs_settings_configure(self, client_for, tenant_a):
        owner = logged_in(client_for, tenant_a, "owner@a.test", "business_owner")  # settings.view only
        assert owner.get("/api/tenant/modules/").status_code == 200
        assert owner.patch("/api/tenant/modules/crm/", {"enabled": False}, content_type="application/json").status_code == 403

    def test_module_list(self, client_for, tenant_a):
        owner = logged_in(client_for, tenant_a, "owner@a.test", "business_owner")
        modules = {m["code"]: m for m in owner.get("/api/tenant/modules/").json()}
        assert modules["users"]["core"] and modules["users"]["enabled"]
        assert modules["orders"]["entitled"] and modules["orders"]["enabled"]
        assert not modules["learning"]["entitled"]

    def test_platform_removing_a_module_switches_it_off(self, tenant_a):
        current = set(TenantModule.objects.filter(tenant=tenant_a, entitled=True).values_list("module", flat=True))
        services.set_entitlements(tenant_a, current - {"orders"})
        fresh = Tenant.objects.get(pk=tenant_a.pk)
        assert "orders" not in services.active_modules(fresh)

    def test_modules_are_separate_per_business(self, client_for, tenant_a, tenant_b):
        admin = logged_in(client_for, tenant_a, "sysadmin@a.test", "system_admin")
        admin.patch("/api/tenant/modules/crm/", {"enabled": False}, content_type="application/json")
        assert "crm" in services.active_modules(Tenant.objects.get(pk=tenant_b.pk))


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserLimit:
    def test_cannot_go_over_the_active_user_limit(self, tenant_a):
        set_licence(tenant_a, max_users=2)
        make_user("tenant_a", "one@a.test")
        make_user("tenant_a", "two@a.test")
        with pytest.raises(services.LimitReached):
            make_user("tenant_a", "three@a.test")

    def test_inactive_users_do_not_count_and_reactivation_is_checked(self, tenant_a):
        set_licence(tenant_a, max_users=1)
        first = make_user("tenant_a", "one@a.test")
        make_user("tenant_a", "left@a.test", is_active=False)  # allowed: inactive
        with schema_context("tenant_a"):
            left = type(first).objects.get(email="left@a.test")
            left.is_active = True
            with pytest.raises(services.LimitReached):
                left.save()

    def test_editing_an_existing_user_at_the_limit_is_fine(self, tenant_a):
        set_licence(tenant_a, max_users=1)
        user = make_user("tenant_a", "one@a.test")
        with schema_context("tenant_a"):
            user.first_name = "Changed"
            user.save()

    def test_platform_users_are_not_limited(self, public_tenant):
        for i in range(12):
            make_user("public", f"admin{i}@platform.test")

    def test_licence_api_shows_usage(self, client_for, tenant_a):
        owner = logged_in(client_for, tenant_a, "owner@a.test", "business_owner")
        data = owner.get("/api/tenant/licence/").json()
        assert data["plan"] == "Trial" and data["status"] == "trial"
        assert data["usage"]["users"] == {"used": 1, "limit": 10}

    def test_licence_api_is_not_on_the_platform_site(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        assert client.get("/api/tenant/licence/").status_code == 404


# ---------------------------------------------------------------------------
# Super Admin: create a business and invite its System Admin
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSuperAdminFlow:
    def test_create_business_in_admin_and_invite_admin(self, verified_admin_client, public_tenant, client_for):
        client = verified_admin_client(public_tenant)
        response = client.post(
            "/admin/tenants/tenant/add/",
            {"name": "Joe's Catering Test", "schema_name": "joes_test", "industry": "catering", "admin_email": "Joe@Catering.test"},
        )
        assert response.status_code == 302, response.content[:500]

        tenant = Tenant.objects.get(schema_name="joes_test")
        assert tenant.get_primary_domain().domain.startswith("joes-test.")
        assert services.access_state(tenant) == "trial"
        assert "events" in services.active_modules(tenant)

        # The invited admin lives in the new business's schema, with no usable password yet.
        with schema_context("joes_test"):
            from apps.accounts.models import User

            joe = User.objects.get(email="joe@catering.test")
            assert joe.is_staff and not joe.has_usable_password()
            assert UserRole.objects.filter(user=joe, role__slug="system_admin").exists()

        assert len(mail.outbox) == 1
        link = re.search(r"https?://joes-test\.[^/]+(/account/reset/\S+/)", mail.outbox[0].body).group(1)

        # Joe sets a password through the link on his own site, then must set up MFA.
        joe_client = client_for(tenant)
        page = joe_client.get(link, follow=True)
        set_url = page.redirect_chain[-1][0]
        new_password = "joes-new-password-123"
        assert joe_client.post(set_url, {"new_password1": new_password, "new_password2": new_password}).status_code == 302
        login = client_for(tenant).post("/api/auth/login/", {"email": "joe@catering.test", "password": new_password})
        assert login.status_code == 200
        assert login.json()["mfa"]["setup_required"] is True

        with schema_context("public"):
            assert AuditEvent.objects.filter(action="tenant.admin_invited").exists()

    def test_invalid_business_id_shows_a_form_error(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        response = client.post("/admin/tenants/tenant/add/", {"name": "Bad", "schema_name": "Bad Name!", "industry": "retail"})
        assert response.status_code == 200
        assert b"lowercase letters" in response.content

    def test_suspend_page_in_admin(self, verified_admin_client, public_tenant, tenant_a):
        client = verified_admin_client(public_tenant)
        assert client.post(f"/admin/tenants/tenant/{tenant_a.pk}/suspend/", {"reason": ""}).status_code == 200
        response = client.post(f"/admin/tenants/tenant/{tenant_a.pk}/suspend/", {"reason": "Unpaid"})
        assert response.status_code == 302
        assert Tenant.objects.get(pk=tenant_a.pk).status == "suspended"

    def test_extend_trial_action_in_admin(self, verified_admin_client, public_tenant, tenant_a):
        client = verified_admin_client(public_tenant)
        before = tenant_a.licence.trial_ends_at
        client.post("/admin/tenants/tenant/", {"action": "action_extend_trial_14", "_selected_action": [tenant_a.pk]})
        assert (Licence.objects.get(tenant=tenant_a).trial_ends_at - before).days == 14

    def test_licence_limits_editable_on_tenant_page(self, verified_admin_client, public_tenant, tenant_a):
        client = verified_admin_client(public_tenant)
        page = client.get(f"/admin/tenants/tenant/{tenant_a.pk}/change/")
        assert page.status_code == 200
        assert b'name="licence-0-max_users"' in page.content  # editable licence limits
        assert b'name="modules-0-entitled"' in page.content  # module checkboxes
        assert b"Invite System Admin" in page.content and b"Suspend business" in page.content

    def test_invite_respects_the_user_limit(self, tenant_a):
        set_licence(tenant_a, max_users=1)
        make_user("tenant_a", "one@a.test")
        with pytest.raises(services.LimitReached):
            services.invite_system_admin(Tenant.objects.get(pk=tenant_a.pk), "new@a.test")
