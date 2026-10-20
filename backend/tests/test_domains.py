"""
Web addresses (task 1.12): subdomain rules, the main address, redirects from
extra addresses, the unknown-address page, the Super Admin page, the
read-only admin, moving the platform domain, and audit records.
"""
import re
from io import StringIO

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.tenants import domains
from apps.tenants.models import Domain, Tenant
from tests.conftest import https_client, make_user
from tests.test_mfa_admin import platform_staff
from tests.test_rbac import verified_staff_client


@pytest.fixture
def super_admin(verified_admin_client, public_tenant):
    return verified_admin_client(public_tenant, "boss@platform.test")


def fresh(tenant):
    return Tenant.objects.get(pk=tenant.pk)


def main_of(tenant) -> str:
    return Domain.objects.get(tenant=tenant, is_primary=True).domain


# ---------------------------------------------------------------------------
# Rules for names
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNameRules:
    @pytest.mark.parametrize("given, expected", [
        ("gorkha", "gorkha"), ("Gorkha-Butchery", "gorkha-butchery"), ("  joes2  ", "joes2"),
        ("gorkha.localhost", "gorkha"),  # the whole address pasted
        ("a" * 63, "a" * 63),
    ])
    def test_good_names(self, given, expected):
        assert domains.validate_label(given) == expected

    @pytest.mark.parametrize("bad", [
        "", "ab", "-gorkha", "gorkha-", "gorkha_butchery", "gor kha", "gorkha.co", "a" * 64,
        "xn--abc", "ab--cd", "12345", "ümlaut", "www", "admin", "api", "app", "mail", "support", "webhooks", "localhost",
    ])
    def test_bad_names(self, bad):
        with pytest.raises(ValidationError):
            domains.validate_label(bad)

    def test_a_used_name_is_refused(self, tenant_a):
        with pytest.raises(ValidationError, match="already used"):
            domains.validate_label("tenant-a")
        with pytest.raises(ValidationError, match="already used"):
            domains.validate_label("TENANT-A")

    def test_a_reserved_name_is_refused_before_the_schema_is_made(self, db):
        from apps.tenants.services import create_tenant

        with pytest.raises(ValidationError, match="kept for the platform"):
            create_tenant("Webhooks Ltd", "webhooks", "retail")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'webhooks'")
            assert cursor.fetchone() is None
        assert not Tenant.objects.filter(schema_name="webhooks").exists()

    def test_create_business_form_checks_the_address(self, db):
        from apps.licensing.admin import TenantCreateForm

        form = TenantCreateForm(data={"name": "Shop", "schema_name": "webhooks", "industry": "retail"})
        assert "gorkha.localhost" in form.fields["subdomain"].help_text
        assert not form.is_valid() and "subdomain" in form.errors
        form = TenantCreateForm(data={"name": "Shop", "schema_name": "webhooks", "industry": "retail", "subdomain": "webhooks-shop"})
        assert form.is_valid(), form.errors
        form = TenantCreateForm(data={"name": "Shop", "schema_name": "newshop", "industry": "retail", "subdomain": "tenant-a"})
        assert not form.is_valid() and "already used" in str(form.errors["subdomain"])


# ---------------------------------------------------------------------------
# Changing addresses
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChanges:
    def test_a_new_address_is_not_the_main_one_unless_asked(self, tenant_a):
        extra = domains.add_subdomain(tenant_a, "a-second")
        assert extra.is_primary is False
        assert main_of(tenant_a) == "tenant-a.localhost"
        third = domains.add_subdomain(tenant_a, "a-third", make_main=True)
        assert third.is_primary and main_of(tenant_a) == "a-third.localhost"
        assert Domain.objects.filter(tenant=tenant_a, is_primary=True).count() == 1

    def test_make_main_and_remove(self, tenant_a):
        extra = domains.add_subdomain(tenant_a, "a-second")
        domains.make_main(extra)
        assert main_of(tenant_a) == "a-second.localhost"
        old = Domain.objects.get(domain="tenant-a.localhost")
        assert old.is_primary is False
        with pytest.raises(ValidationError, match="main address cannot be removed"):
            domains.remove(Domain.objects.get(domain="a-second.localhost"))
        domains.remove(old)
        assert list(Domain.objects.filter(tenant=tenant_a).values_list("domain", flat=True)) == ["a-second.localhost"]

    def test_at_most_five_addresses(self, tenant_a):
        for n in range(domains.MAX_SUBDOMAINS - 1):
            domains.add_subdomain(tenant_a, f"a-extra-{n}")
        with pytest.raises(ValidationError, match="up to 5"):
            domains.add_subdomain(tenant_a, "a-one-too-many")

    def test_the_platform_address_cannot_be_changed_here(self, public_tenant):
        with pytest.raises(ValidationError, match="platform"):
            domains.add_subdomain(public_tenant, "platform-two")
        with pytest.raises(ValidationError, match="platform"):
            domains.remove(Domain.objects.get(tenant=public_tenant))

    def test_changes_are_in_both_audit_logs(self, tenant_a):
        actor = make_user("public", "boss@platform.test", superuser=True)
        extra = domains.add_subdomain(tenant_a, "a-second", actor=actor)
        domains.make_main(extra, actor=actor)
        domains.remove(Domain.objects.get(domain="tenant-a.localhost"), actor=actor)
        actions = ["tenant.address_added", "tenant.main_address_changed", "tenant.address_removed"]
        platform = list(AuditEvent.objects.filter(action__in=actions).order_by("id"))
        assert [e.action for e in platform] == actions
        assert all(e.actor_email == "boss@platform.test" for e in platform)
        assert platform[1].metadata["previous"] == "tenant-a.localhost"
        with schema_context("tenant_a"):
            business = list(AuditEvent.objects.filter(action__in=actions).order_by("id"))
            assert [e.action for e in business] == actions
            assert all(e.actor_type == "platform" and e.actor_email == "boss@platform.test" for e in business)
            assert business[2].target_repr == "tenant-a.localhost"

    def test_invitation_links_use_the_main_address(self, tenant_a):
        from apps.licensing import services

        domains.add_subdomain(tenant_a, "a-new-name", make_main=True)
        services.invite_system_admin(fresh(tenant_a), "owner@a.test")
        assert re.search(r"https://a-new-name\.localhost/account/reset/\S+/", mail.outbox[-1].body)

    def test_licence_api_lists_the_addresses(self, client_for, tenant_a):
        domains.add_subdomain(tenant_a, "a-second")
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "system_admin")
        data = owner.get("/api/tenant/licence/").json()
        assert data["web_addresses"] == [
            {"address": "tenant-a.localhost", "main": True},
            {"address": "a-second.localhost", "main": False},
        ]


# ---------------------------------------------------------------------------
# Finding the business, redirects and unknown addresses
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRouting:
    @pytest.fixture
    def alias(self, tenant_a):
        domains.add_subdomain(tenant_a, "a-old-name")
        return "a-old-name.localhost"

    def test_extra_address_sends_visitors_to_the_main_address(self, alias):
        response = https_client(alias).get("/admin/login/?next=/admin/")
        assert response.status_code == 302  # temporary on purpose (decision D-085)
        assert response["Location"] == "https://tenant-a.localhost/admin/login/?next=/admin/"

    def test_port_and_head_requests(self, alias):
        response = https_client(f"{alias}:8000").head("/app/orders")
        assert response.status_code == 302
        assert response["Location"] == "https://tenant-a.localhost:8000/app/orders"

    def test_www_goes_to_the_main_address(self, tenant_a):
        response = https_client("www.tenant-a.localhost").get("/admin/")
        assert response.status_code == 302 and response["Location"].startswith("https://tenant-a.localhost/admin/")

    def test_main_address_is_not_redirected_and_case_does_not_matter(self, tenant_a):
        assert https_client("tenant-a.localhost").get("/admin/login/").status_code == 200
        assert https_client("TENANT-A.LocalHost").get("/admin/login/").status_code == 200

    @pytest.mark.parametrize("path", ["/api/auth/csrf/", "/health/", "/webhooks/whatsapp/?hub.mode=subscribe"])
    def test_api_webhooks_and_health_work_on_every_address(self, alias, path):
        response = https_client(alias).get(path)
        assert response.status_code != 302, f"{path} was redirected"

    def test_posts_reach_the_same_business_on_an_extra_address(self, alias):
        from tests.test_auth import api_login

        make_user("tenant_a", "staff@a.test")
        client = https_client(alias)
        response = api_login(client, "staff@a.test", "a-long-test-password-123")
        assert response.status_code == 200 and response.json()["user"]["email"] == "staff@a.test"

    def test_unknown_address_gets_a_friendly_page(self, db):
        response = https_client("nobody-here.localhost").get("/admin/")
        assert response.status_code == 404
        body = response.content.decode()
        assert "No business at this address" in body and "nobody-here.localhost" in body
        assert "Set-Cookie" not in response.headers and not response.cookies

    def test_unknown_address_page_escapes_the_address(self, db):
        response = https_client("x.localhost").get("/", HTTP_HOST="evil<script>.localhost")
        # Django refuses hosts that are not valid names before any page is made.
        assert response.status_code in (400, 404)
        assert b"<script>" not in response.content

    def test_a_removed_address_opens_nothing(self, tenant_a, alias):
        domains.remove(Domain.objects.get(domain=alias))
        response = https_client(alias).get("/api/auth/csrf/")
        assert response.status_code == 404 and b"No business at this address" in response.content


# ---------------------------------------------------------------------------
# Super Admin page
# ---------------------------------------------------------------------------
URL = "/platform/businesses/tenant_a/addresses/"


@pytest.mark.django_db
class TestPlatformPage:
    def test_shows_the_addresses(self, super_admin, tenant_a):
        domains.add_subdomain(tenant_a, "a-second")
        page = super_admin.get(URL).content.decode()
        assert "Web addresses of Tenant A Butchery" in page
        assert "tenant-a.localhost" in page and "a-second.localhost" in page and "Main address" in page
        assert 'href="https://tenant-a.localhost/"' in page

    def test_add_make_main_and_remove(self, super_admin, tenant_a):
        response = super_admin.post(URL, {"action": "add", "label": "Gorkha-Fresh"})
        assert response.status_code == 302
        new = Domain.objects.get(domain="gorkha-fresh.localhost")
        assert new.tenant_id == tenant_a.pk and not new.is_primary
        super_admin.post(URL, {"action": "main", "domain": new.pk})
        assert main_of(tenant_a) == "gorkha-fresh.localhost"
        old = Domain.objects.get(domain="tenant-a.localhost")
        super_admin.post(URL, {"action": "remove", "domain": old.pk})
        assert not Domain.objects.filter(pk=old.pk).exists()

    def test_bad_name_shows_an_error(self, super_admin, tenant_a):
        response = super_admin.post(URL, {"action": "add", "label": "admin"})
        assert response.status_code == 200 and "kept for the platform" in response.content.decode()
        assert not Domain.objects.filter(domain="admin.localhost").exists()

    def test_cannot_remove_the_main_address(self, super_admin, tenant_a):
        main = Domain.objects.get(tenant=tenant_a, is_primary=True)
        response = super_admin.post(URL, {"action": "remove", "domain": main.pk}, follow=True)
        assert "main address cannot be removed" in response.content.decode()
        assert Domain.objects.filter(pk=main.pk).exists()

    def test_cannot_touch_another_business_through_this_page(self, super_admin, tenant_a, tenant_b):
        other = Domain.objects.get(tenant=tenant_b, is_primary=True)
        extra = domains.add_subdomain(tenant_b, "b-second")
        super_admin.post(URL, {"action": "remove", "domain": extra.pk})
        super_admin.post(URL, {"action": "main", "domain": extra.pk})
        assert Domain.objects.filter(pk=extra.pk, is_primary=False).exists()
        assert Domain.objects.get(pk=other.pk).is_primary

    def test_platform_itself_has_no_page(self, super_admin):
        assert super_admin.get("/platform/businesses/public/addresses/").status_code == 404
        assert super_admin.get("/platform/businesses/nope/addresses/").status_code == 404

    def test_view_only_platform_staff_can_look_but_not_change(self, client_for, public_tenant, tenant_a):
        support = platform_staff(client_for, public_tenant, "support@platform.test", "platform_support_admin")
        page = support.get(URL)
        assert page.status_code == 200 and "Add address" not in page.content.decode()
        assert support.post(URL, {"action": "add", "label": "sneaky-name"}).status_code == 403
        assert not Domain.objects.filter(domain="sneaky-name.localhost").exists()

    def test_platform_staff_without_tenant_rights_see_nothing(self, client_for, public_tenant):
        nobody = platform_staff(client_for, public_tenant, "nobody@platform.test")
        assert nobody.get(URL).status_code == 403

    def test_business_sites_do_not_have_this_page(self, verified_admin_client, tenant_a):
        assert verified_admin_client(tenant_a).get(URL).status_code == 404

    def test_tenant_page_links_here_and_list_shows_main_address(self, super_admin, tenant_a):
        page = super_admin.get(f"/admin/tenants/tenant/{tenant_a.pk}/change/").content.decode()
        assert URL in page
        # The address list on this page is read-only: no editing, deleting or adding rows.
        assert 'name="domains-0-domain"' not in page and 'name="domains-0-DELETE"' not in page and "domains-__prefix__" not in page
        listing = super_admin.get("/admin/tenants/tenant/").content.decode()
        assert '<a href="https://tenant-a.localhost/"' in listing

    def test_domain_admin_is_read_only(self, super_admin, tenant_a):
        assert super_admin.get("/admin/tenants/domain/").status_code == 200
        assert super_admin.get("/admin/tenants/domain/add/").status_code == 403
        main = Domain.objects.get(tenant=tenant_a, is_primary=True)
        super_admin.post(f"/admin/tenants/domain/{main.pk}/change/", {"domain": "stolen.localhost", "tenant": tenant_a.pk, "is_primary": "on"})
        super_admin.post(f"/admin/tenants/domain/{main.pk}/delete/", {"post": "yes"})
        assert Domain.objects.get(pk=main.pk).domain == "tenant-a.localhost"


# ---------------------------------------------------------------------------
# Moving the platform (laptop -> real domain)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMovingThePlatform:
    def test_dry_run_changes_nothing(self, tenant_a):
        out = StringIO()
        call_command("change_platform_domain", "--from", "localhost", "--to", "example.nz", stdout=out)
        assert "tenant-a.localhost  ->  tenant-a.example.nz" in out.getvalue()
        assert "localhost  ->  example.nz" in out.getvalue()
        assert Domain.objects.filter(domain="tenant-a.localhost").exists()

    def test_apply_moves_every_address(self, tenant_a, tenant_b, public_tenant):
        call_command("change_platform_domain", "--from", "localhost", "--to", "example.nz", "--apply", stdout=StringIO())
        assert main_of(public_tenant) == "example.nz"
        assert main_of(tenant_a) == "tenant-a.example.nz" and main_of(tenant_b) == "tenant-b.example.nz"
        assert not Domain.objects.filter(domain__endswith="localhost").exists()
        assert AuditEvent.objects.filter(action="platform.domain_changed").exists()

    def test_clash_changes_nothing(self, tenant_a, tenant_b):
        Domain.objects.create(domain="tenant-a.example.nz", tenant=tenant_b, is_primary=False)
        with pytest.raises(Exception, match="already exist"):
            call_command("change_platform_domain", "--from", "localhost", "--to", "example.nz", "--apply", stdout=StringIO())
        assert main_of(tenant_a) == "tenant-a.localhost"

    def test_bootstrap_does_not_add_a_second_platform_address(self, public_tenant):
        out = StringIO()
        call_command("bootstrap_platform", "--domain", "example.nz", stdout=out)
        assert "change_platform_domain --from localhost --to example.nz" in out.getvalue()
        assert list(Domain.objects.filter(tenant=public_tenant).values_list("domain", flat=True)) == ["localhost"]
