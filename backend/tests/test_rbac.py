"""Roles and permissions (task 1.3)."""
import pytest
from django.contrib.auth.models import Permission as DjangoPermission
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.rbac import policy
from apps.rbac.catalogue import PLATFORM_PERMISSIONS, TENANT_PERMISSIONS
from apps.rbac.defaults import PLATFORM_ROLES, TENANT_ROLES
from apps.rbac.models import Role, UserRole
from tests.conftest import PASSWORD, add_totp_device, admin_login, current_code, make_user


def give_role(schema, user, slug):
    with schema_context(schema):
        UserRole.objects.create(user=user, role=Role.objects.get(slug=slug))


def make_role(schema, slug, codes):
    with schema_context(schema):
        role = Role.objects.create(slug=slug, name=slug.title())
        role.set_permissions(codes)
        return role


def api_client(client_for, tenant, email):
    client = client_for(tenant)
    assert client.post("/api/auth/login/", {"email": email, "password": PASSWORD}).status_code == 200
    return client


# ---------------------------------------------------------------------------
# Default roles
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDefaultRoles:
    def test_every_business_gets_the_business_roles(self, tenant_a, tenant_b):
        for schema in ("tenant_a", "tenant_b"):
            with schema_context(schema):
                assert set(Role.objects.values_list("slug", flat=True)) == set(TENANT_ROLES)

    def test_platform_gets_only_platform_roles(self, public_tenant):
        with schema_context("public"):
            assert set(Role.objects.values_list("slug", flat=True)) == set(PLATFORM_ROLES)

    def test_default_roles_only_use_known_permissions(self, tenant_a, public_tenant):
        with schema_context("tenant_a"):
            for role in Role.objects.all():
                assert role.permission_codes() <= TENANT_PERMISSIONS
        with schema_context("public"):
            for role in Role.objects.all():
                assert role.permission_codes() <= PLATFORM_PERMISSIONS

    def test_system_admin_has_everything_and_customer_has_nothing(self, tenant_a):
        with schema_context("tenant_a"):
            assert Role.objects.get(slug="system_admin").permission_codes() == set(TENANT_PERMISSIONS)
            assert Role.objects.get(slug="customer").permission_codes() == set()

    def test_platform_billing_admin_has_no_business_accounting(self, public_tenant):
        with schema_context("public"):
            codes = Role.objects.get(slug="platform_billing_admin").permission_codes()
        assert "platform_billing.manage_billing" in codes
        assert not any(c.startswith("finance.") for c in codes)

    def test_default_roles_cannot_be_deleted(self, tenant_a):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"):
            with pytest.raises(ValidationError):
                Role.objects.get(slug="accountant").delete()

    def test_unknown_permission_code_is_rejected(self, tenant_a):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"):
            role = Role.objects.create(slug="custom", name="Custom")
            with pytest.raises(ValidationError):
                role.set_permissions({"crm.view", "crm.launch_rockets"})

    def test_platform_permissions_cannot_be_used_in_a_business(self, tenant_a):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"):
            role = Role.objects.create(slug="custom", name="Custom")
            with pytest.raises(ValidationError):
                role.set_permissions({"tenants.delete"})


# ---------------------------------------------------------------------------
# Policy: deny by default
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPolicy:
    def test_user_with_no_role_has_no_permissions(self, tenant_a):
        user = make_user("tenant_a", "new@a.test", staff=True)
        with schema_context("tenant_a"):
            assert policy.effective_permissions(user) == set()
            assert not policy.has_perm(user, "crm.view")

    def test_role_grants_only_its_permissions(self, tenant_a):
        user = make_user("tenant_a", "rep@a.test")
        give_role("tenant_a", user, "sales_rep")
        with schema_context("tenant_a"):
            assert policy.has_perm(user, "crm.view")
            assert not policy.has_perm(user, "finance.view")
            assert not policy.has_perm(user, "crm.delete")

    def test_several_roles_add_up(self, tenant_a):
        user = make_user("tenant_a", "both@a.test")
        give_role("tenant_a", user, "sales_rep")
        give_role("tenant_a", user, "accountant")
        with schema_context("tenant_a"):
            assert policy.has_perm(user, "crm.view") and policy.has_perm(user, "finance.view")

    def test_full_access_role_has_everything(self, tenant_a):
        user = make_user("tenant_a", "sysadmin@a.test")
        give_role("tenant_a", user, "system_admin")
        with schema_context("tenant_a"):
            assert policy.effective_permissions(user) == set(TENANT_PERMISSIONS)

    def test_superuser_has_everything_in_own_schema(self, tenant_a):
        user = make_user("tenant_a", "boss@a.test", superuser=True)
        with schema_context("tenant_a"):
            assert policy.has_perm(user, "finance.approve")

    def test_inactive_user_is_denied(self, tenant_a):
        user = make_user("tenant_a", "left@a.test", is_active=False)
        give_role("tenant_a", user, "sales_rep")
        with schema_context("tenant_a"):
            assert policy.check(user, "crm.view").reason == "inactive_user"

    def test_anonymous_and_unknown_codes_are_denied(self, tenant_a):
        from django.contrib.auth.models import AnonymousUser

        user = make_user("tenant_a", "boss@a.test", superuser=True)
        with schema_context("tenant_a"):
            assert policy.check(AnonymousUser(), "crm.view").reason == "not_authenticated"
            assert policy.check(user, "crm.not_a_thing").reason == "unknown_permission"

    def test_django_groups_and_user_permissions_are_ignored(self, tenant_a):
        """Django's own permission system must not be a side door around roles."""
        user = make_user("tenant_a", "sneaky@a.test", staff=True)
        with schema_context("tenant_a"):
            user.user_permissions.add(DjangoPermission.objects.get(codename="change_user"))
            user = type(user).objects.get(pk=user.pk)
            assert not user.has_perm("accounts.change_user")


# ---------------------------------------------------------------------------
# API and privilege escalation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRolesApi:
    def test_my_permissions(self, client_for, tenant_a):
        user = make_user("tenant_a", "rep@a.test")
        give_role("tenant_a", user, "sales_rep")
        perms = api_client(client_for, tenant_a, "rep@a.test").get("/api/rbac/me/permissions/").json()["permissions"]
        assert "crm.view" in perms and "finance.view" not in perms

    def test_roles_list_needs_roles_view(self, client_for, tenant_a):
        make_user("tenant_a", "rep@a.test")
        client = api_client(client_for, tenant_a, "rep@a.test")
        assert client.get("/api/rbac/roles/").status_code == 403

    def test_roles_list_with_permission(self, client_for, tenant_a):
        user = make_user("tenant_a", "owner@a.test")
        give_role("tenant_a", user, "business_owner")
        response = api_client(client_for, tenant_a, "owner@a.test").get("/api/rbac/roles/")
        assert response.status_code == 200
        assert {r["slug"] for r in response.json()} == set(TENANT_ROLES)

    def test_denied_request_is_audited(self, client_for, tenant_a):
        make_user("tenant_a", "rep@a.test")
        api_client(client_for, tenant_a, "rep@a.test").get("/api/rbac/roles/")
        with schema_context("tenant_a"):
            event = AuditEvent.objects.filter(action="permission.denied").first()
        assert event.actor_email == "rep@a.test"
        assert event.metadata == {"permission": "roles.view", "reason": "role_missing_permission"}

    def test_suspended_business_is_denied_even_for_full_admins(self, client_for, tenant_a):
        user = make_user("tenant_a", "sysadmin@a.test")
        give_role("tenant_a", user, "system_admin")
        client = api_client(client_for, tenant_a, "sysadmin@a.test")
        assert client.get("/api/rbac/roles/").status_code == 200
        tenant_a.status = "suspended"
        tenant_a.save(update_fields=["status"])
        assert client.get("/api/rbac/roles/").status_code == 403

    def test_create_custom_role_within_own_permissions(self, client_for, tenant_a):
        actor = make_user("tenant_a", "lead@a.test")
        make_role("tenant_a", "role_maker", {"roles.view", "roles.create", "crm.view", "crm.edit"})
        give_role("tenant_a", actor, "role_maker")
        client = api_client(client_for, tenant_a, "lead@a.test")
        response = client.post(
            "/api/rbac/roles/",
            {"slug": "crm_helper", "name": "CRM helper", "permissions": ["crm.view", "crm.edit"]},
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["permissions"] == ["crm.edit", "crm.view"]

    def test_cannot_create_role_with_permissions_you_do_not_have(self, client_for, tenant_a):
        actor = make_user("tenant_a", "lead@a.test")
        make_role("tenant_a", "role_maker", {"roles.view", "roles.create", "crm.view"})
        give_role("tenant_a", actor, "role_maker")
        client = api_client(client_for, tenant_a, "lead@a.test")
        response = client.post(
            "/api/rbac/roles/",
            {"slug": "money", "name": "Money", "permissions": ["crm.view", "finance.approve"]},
            content_type="application/json",
        )
        assert response.status_code == 403
        with schema_context("tenant_a"):
            assert not Role.objects.filter(slug="money").exists()

    def test_cannot_add_permissions_you_do_not_have_to_a_role(self, client_for, tenant_a):
        actor = make_user("tenant_a", "lead@a.test")
        make_role("tenant_a", "perm_editor", {"roles.view", "roles.manage_permissions", "crm.view"})
        target = make_role("tenant_a", "target", {"crm.view"})
        give_role("tenant_a", actor, "perm_editor")
        client = api_client(client_for, tenant_a, "lead@a.test")
        bad = client.put(f"/api/rbac/roles/{target.pk}/permissions/", {"permissions": ["crm.view", "finance.view"]}, content_type="application/json")
        assert bad.status_code == 403

    def test_cannot_give_a_role_stronger_than_yourself(self, client_for, tenant_a):
        actor = make_user("tenant_a", "it@a.test")
        give_role("tenant_a", actor, "it_admin")  # has roles.assign, not finance
        victim = make_user("tenant_a", "staff@a.test")
        with schema_context("tenant_a"):
            accountant = Role.objects.get(slug="accountant")
        client = api_client(client_for, tenant_a, "it@a.test")
        response = client.post(f"/api/rbac/users/{victim.pk}/roles/", {"role_id": accountant.pk}, content_type="application/json")
        assert response.status_code == 403

    def test_cannot_change_your_own_roles(self, client_for, tenant_a):
        actor = make_user("tenant_a", "it@a.test")
        give_role("tenant_a", actor, "it_admin")
        with schema_context("tenant_a"):
            employee = Role.objects.get(slug="employee")
        client = api_client(client_for, tenant_a, "it@a.test")
        response = client.post(f"/api/rbac/users/{actor.pk}/roles/", {"role_id": employee.pk}, content_type="application/json")
        assert response.status_code == 403
        assert "own roles" in response.json()["detail"]

    def test_only_full_admins_can_give_full_access(self, client_for, tenant_a):
        actor = make_user("tenant_a", "lead@a.test")
        make_role("tenant_a", "almost_all", set(TENANT_PERMISSIONS))  # every code, but not a full-access role
        give_role("tenant_a", actor, "almost_all")
        victim = make_user("tenant_a", "staff@a.test")
        with schema_context("tenant_a"):
            sysadmin = Role.objects.get(slug="system_admin")
        client = api_client(client_for, tenant_a, "lead@a.test")
        assert client.post(f"/api/rbac/users/{victim.pk}/roles/", {"role_id": sysadmin.pk}, content_type="application/json").status_code == 403

    def test_system_admin_can_assign_and_remove_roles(self, client_for, tenant_a):
        actor = make_user("tenant_a", "sysadmin@a.test")
        give_role("tenant_a", actor, "system_admin")
        staff = make_user("tenant_a", "staff@a.test")
        with schema_context("tenant_a"):
            rep = Role.objects.get(slug="sales_rep")
        client = api_client(client_for, tenant_a, "sysadmin@a.test")
        assert client.post(f"/api/rbac/users/{staff.pk}/roles/", {"role_id": rep.pk}, content_type="application/json").status_code == 201
        with schema_context("tenant_a"):
            assert policy.has_perm(type(staff).objects.get(pk=staff.pk), "crm.view")
        assert client.delete(f"/api/rbac/users/{staff.pk}/roles/{rep.pk}/").status_code == 204
        with schema_context("tenant_a"):
            assert not policy.has_perm(type(staff).objects.get(pk=staff.pk), "crm.view")

    def test_default_role_cannot_be_deleted_via_api(self, client_for, tenant_a):
        actor = make_user("tenant_a", "sysadmin@a.test")
        give_role("tenant_a", actor, "system_admin")
        with schema_context("tenant_a"):
            accountant = Role.objects.get(slug="accountant")
        response = api_client(client_for, tenant_a, "sysadmin@a.test").delete(f"/api/rbac/roles/{accountant.pk}/")
        assert response.status_code == 400

    def test_roles_in_one_business_do_not_apply_in_another(self, client_for, tenant_a, tenant_b):
        a = make_user("tenant_a", "same@person.test")
        make_user("tenant_b", "same@person.test")
        give_role("tenant_a", a, "business_owner")
        assert api_client(client_for, tenant_a, "same@person.test").get("/api/rbac/roles/").status_code == 200
        assert api_client(client_for, tenant_b, "same@person.test").get("/api/rbac/roles/").status_code == 403


# ---------------------------------------------------------------------------
# Admin site uses roles
# ---------------------------------------------------------------------------
def verified_staff_client(client_for, tenant, email, role_slug=None):
    user = make_user(tenant.schema_name, email, staff=True)
    if role_slug:
        give_role(tenant.schema_name, user, role_slug)
    device = add_totp_device(tenant.schema_name, user)
    client = client_for(tenant)
    admin_login(client, email)
    client.post("/account/mfa/verify/", {"token": current_code(device), "next": "/admin/"})
    return client


@pytest.mark.django_db
class TestAdminUsesRoles:
    def test_staff_without_roles_sees_nothing(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "nobody@a.test")
        assert client.get("/admin/accounts/user/").status_code == 403

    def test_auditor_can_read_audit_log_but_not_edit_users(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "auditor@a.test", "auditor")
        assert client.get("/admin/audit/auditevent/").status_code == 200
        assert client.get("/admin/accounts/user/add/").status_code == 403

    def test_it_admin_can_manage_users_but_not_edit_roles(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        assert client.get("/admin/accounts/user/").status_code == 200
        assert client.get("/admin/rbac/role/").status_code == 200  # can look
        assert client.get("/admin/rbac/role/add/").status_code == 403  # cannot edit in admin


@pytest.mark.django_db
class TestRoleEditorInAdmin:
    def test_editor_shows_current_permissions_and_saves_changes(self, verified_admin_client, tenant_a):
        import re

        client = verified_admin_client(tenant_a)
        with schema_context("tenant_a"):
            role = Role.objects.get(slug="accountant")
        page = client.get(f"/admin/rbac/role/{role.pk}/change/").content.decode()
        checked = set(re.findall(r'value="([a-z_]+\.[a-z_]+)"[^>]*checked', page))
        with schema_context("tenant_a"):
            assert checked == role.permission_codes()

        response = client.post(
            f"/admin/rbac/role/{role.pk}/change/",
            {"slug": "accountant", "name": "Accountant", "description": "Books", "permission_codes": ["finance.view", "reports.view"]},
        )
        assert response.status_code == 302
        with schema_context("tenant_a"):
            assert Role.objects.get(pk=role.pk).permission_codes() == {"finance.view", "reports.view"}
            event = AuditEvent.objects.filter(action="role.permissions_set", target_id=str(role.pk)).first()
        assert "finance.export" in event.changes["removed"]
        assert event.actor_email == "boss@site.test"

    def test_full_access_role_cannot_be_narrowed_in_admin(self, verified_admin_client, tenant_a):
        client = verified_admin_client(tenant_a)
        with schema_context("tenant_a"):
            role = Role.objects.get(slug="system_admin")
        client.post(
            f"/admin/rbac/role/{role.pk}/change/",
            {"slug": "system_admin", "name": "System Admin", "description": "x", "permission_codes": ["crm.view"]},
        )
        with schema_context("tenant_a"):
            assert Role.objects.get(pk=role.pk).permission_codes() == set(TENANT_PERMISSIONS)

    def test_groups_page_is_hidden(self, verified_admin_client, tenant_a):
        assert verified_admin_client(tenant_a).get("/admin/auth/group/").status_code == 404
