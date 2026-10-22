"""
A business's own domain (task 2.8, D-159 to D-163): names, the DNS check
(TXT code and pointing), live / DNS problem / back to the platform address,
when checks run, routing and the host check, Caddy's certificate question,
the business page, the Super Admin page, Check system and audit records.
"""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.health.checks import check_custom_domains
from apps.tenants import custom_domains as cdm
from apps.tenants import domains
from apps.tenants import tasks
from apps.tenants.models import CustomDomain, Domain, Tenant
from tests.conftest import https_client, make_user, pass_delete_check
from tests.test_rbac import give_role, verified_staff_client

C = CustomDomain.Status
SERVER = "203.0.113.10"  # a documentation address (RFC 5737)


class FakeDNS:
    """Answers DNS questions from a dict: {(name, type): [values]}."""

    def __init__(self):
        self.records = {}

    def __call__(self, name, kind):
        return list(self.records.get((name, kind), []))

    def ready(self, cd, *, txt=True, ip=SERVER):
        if txt:
            self.records[(cd.txt_name, "TXT")] = ["v=spf1 -all", cd.txt_value]
        if ip:
            self.records[(cd.name, "A")] = [ip]


@pytest.fixture
def dns(monkeypatch, settings):
    fake = FakeDNS()
    monkeypatch.setattr(cdm, "lookup", fake)
    settings.PLATFORM_SERVER_IPS = [SERVER]
    return fake


@pytest.fixture
def it_admin(client_for, tenant_a):
    return verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")  # Settings – Configure


def tenant(schema="tenant_a"):
    with schema_context("public"):
        return Tenant.objects.get(schema_name=schema)


def added(name="gorkha.co.nz", schema="tenant_a"):
    with schema_context("public"):
        return cdm.add(tenant(schema), name)


def fresh(cd):
    with schema_context("public"):
        return CustomDomain.objects.select_related("domain").get(pk=cd.pk)


def check(cd, **kw):
    with schema_context("public"):
        return cdm.check(fresh(cd), **kw)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNames:
    @pytest.mark.parametrize("given, expected", [
        ("gorkha.co.nz", "gorkha.co.nz"), ("https://WWW.Gorkha.CO.NZ/menu?x=1", "gorkha.co.nz"), ("shop.gorkha.co.nz.", "shop.gorkha.co.nz"),
        ("gorkha.co.nz:443", "gorkha.co.nz"), ("café.nz", "xn--caf-dma.nz"),
    ])
    def test_good_names(self, tenant_a, given, expected):
        assert cdm.validate(given) == expected

    @pytest.mark.parametrize("bad", [
        "", "gorkha", "192.0.2.1", "gorkha..co.nz", "-gorkha.co.nz", "gorkha_shop.co.nz", "gorkha.c0m", "a" * 64 + ".nz",
        "tenant-a.localhost", "localhost", "shop.local", "shop.test", "x.invalid",
    ])
    def test_bad_names(self, tenant_a, bad):
        with pytest.raises(ValidationError):
            cdm.validate(bad)

    def test_platform_addresses_and_ip_addresses_are_refused(self, tenant_a, settings):
        settings.PLATFORM_DOMAIN = "platform.nz"
        for name in ("platform.nz", "shop.platform.nz"):
            with pytest.raises(ValidationError, match="platform addresses"):
                cdm.validate(name)
        with pytest.raises(ValidationError, match="not an IP address"):
            cdm.validate("192.0.2.1")

    def test_a_used_name_is_refused(self, tenant_a, tenant_b):
        with schema_context("public"):
            Domain.objects.create(tenant=tenant("tenant_b"), domain="taken.co.nz", is_primary=False)
        with pytest.raises(ValidationError, match="already used"):
            added("taken.co.nz")
        added("gorkha.co.nz")
        with pytest.raises(ValidationError, match="already used"):
            added("WWW.gorkha.co.nz", schema="tenant_b")

    def test_at_most_three_per_business(self, tenant_a):
        for n in range(3):
            added(f"shop{n}.gorkha.co.nz")
        with pytest.raises(ValidationError, match="up to 3"):
            added("shop9.gorkha.co.nz")


# ---------------------------------------------------------------------------
# The DNS check
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDnsCheck:
    def test_waits_for_both_records(self, tenant_a, dns):
        cd = added()
        assert check(cd).status == C.PENDING and "does not point anywhere yet" in fresh(cd).last_result
        dns.ready(cd, txt=True, ip=None)
        assert check(cd).status == C.PENDING and "The TXT code was found" in fresh(cd).last_result
        dns.records.clear()
        dns.ready(cd, txt=False)
        assert check(cd).status == C.PENDING and "points to the platform. The TXT code was not found yet." in fresh(cd).last_result
        dns.ready(cd)
        cd = check(cd)
        assert (cd.status, cd.domain.domain, cd.domain.is_primary, cd.domain.tenant.schema_name) == (C.LIVE, "gorkha.co.nz", False, "tenant_a")
        assert cd.verified_at is not None

    def test_a_wrong_code_or_another_server_is_not_enough(self, tenant_a, dns):
        cd = added()
        dns.records[(cd.txt_name, "TXT")] = ["anish1989-verify=" + "0" * 32, f"{cd.txt_value} and more", "x" + cd.txt_value]
        dns.records[(cd.name, "A")] = [SERVER]
        assert check(cd).status == C.PENDING
        dns.ready(cd, ip="198.51.100.7")
        assert check(cd).status == C.PENDING and "points to 198.51.100.7, not to 203.0.113.10" in fresh(cd).last_result
        dns.records[(cd.name, "A")] = [SERVER, "198.51.100.7"]  # some visitors would end up elsewhere
        assert check(cd).status == C.PENDING
        dns.records[(cd.name, "AAAA")] = ["2001:db8::1"]
        dns.records[(cd.name, "A")] = [SERVER]
        assert check(cd).status == C.PENDING  # the IPv6 address is not ours either

    def test_server_address_from_the_platform_domain(self, tenant_a, dns, settings):
        settings.PLATFORM_SERVER_IPS = []
        dns.records[("localhost", "A")] = [SERVER]
        assert cdm.server_ips() == {SERVER}
        dns.records.clear()
        cd = added()
        dns.ready(cd)
        assert check(cd).status == C.PENDING and "could not be found in DNS" in fresh(cd).last_result

    def test_live_emails_the_business_admins(self, tenant_a, dns):
        give_role("tenant_a", make_user("tenant_a", "it@a.test", staff=True), "it_admin")
        give_role("tenant_a", make_user("tenant_a", "counter@a.test", staff=True), "shop_staff")
        cd = added()
        dns.ready(cd)
        check(cd)
        assert [m.to for m in mail.outbox] == [["it@a.test"]] and mail.outbox[0].subject == "Your domain gorkha.co.nz is live"

    def test_problem_then_working_again(self, tenant_a, dns):
        give_role("tenant_a", make_user("tenant_a", "it@a.test", staff=True), "it_admin")
        cd = added()
        dns.ready(cd)
        check(cd)
        dns.records[(cd.name, "A")] = ["198.51.100.7"]
        cd = check(cd)
        assert cd.status == C.FAILING and cd.failing_since is not None and "does not point to us" in mail.outbox[-1].subject
        dns.records.pop((cd.txt_name, "TXT"))  # once live, only the pointing is checked
        dns.records[(cd.name, "A")] = [SERVER]
        cd = check(cd)
        assert (cd.status, cd.failing_since) == (C.LIVE, None) and "works again" in mail.outbox[-1].subject

    def test_back_to_the_platform_address_after_three_days(self, tenant_a, dns):
        cd = added()
        dns.ready(cd)
        cd = check(cd)
        with schema_context("public"):
            cdm.make_main_by_business(cd.domain)
            # Even when the own domain's row is the older one, the platform address is chosen.
            Domain.objects.filter(domain="tenant-a.localhost").update(created_at=timezone.now() + timedelta(seconds=5))
        dns.records[(cd.name, "A")] = []
        start = timezone.now()
        check(cd, now=start)
        check(cd, now=start + timedelta(days=2))
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "gorkha.co.nz"
        cd = check(cd, now=start + timedelta(days=3, minutes=1))
        assert cd.fell_back_at is not None and cd.status == C.FAILING
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "tenant-a.localhost"
            assert Domain.objects.filter(domain="gorkha.co.nz").exists()  # it still works when the DNS is fixed
        dns.records[(cd.name, "A")] = [SERVER]
        cd = check(cd, now=start + timedelta(days=4))
        assert cd.status == C.LIVE
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "tenant-a.localhost"  # the admin chooses again

    def test_not_the_main_address_only_marks_it(self, tenant_a, dns):
        give_role("tenant_a", make_user("tenant_a", "it@a.test", staff=True), "it_admin")
        cd = added()
        dns.ready(cd)
        check(cd)
        dns.records[(cd.name, "A")] = []
        start = timezone.now()
        check(cd, now=start)
        cd = check(cd, now=start + timedelta(days=3, minutes=1))
        assert cd.fell_back_at is not None
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "tenant-a.localhost"
        assert not any("no longer the main address" in m.subject for m in mail.outbox)  # nothing changed, nothing to tell

    def test_when_checks_are_due(self, tenant_a, dns):
        cd = added()
        now = timezone.now()
        with schema_context("public"):
            assert list(cdm.due(now)) == [fresh(cd)]  # never checked
            CustomDomain.objects.filter(pk=cd.pk).update(last_checked_at=now - timedelta(minutes=30))
            assert list(cdm.due(now)) == []
            assert list(cdm.due(now + timedelta(minutes=30))) == [fresh(cd)]  # hourly while waiting
            CustomDomain.objects.filter(pk=cd.pk).update(created_at=now - timedelta(days=8), last_checked_at=now - timedelta(hours=2))
            assert list(cdm.due(now)) == []  # after a week: daily
            assert list(cdm.due(now + timedelta(hours=22))) == [fresh(cd)]
            CustomDomain.objects.filter(pk=cd.pk).update(status=C.LIVE, last_checked_at=now - timedelta(hours=2))
            assert list(cdm.due(now)) == []
            CustomDomain.objects.filter(pk=cd.pk).update(status=C.FAILING)
            assert list(cdm.due(now)) == [fresh(cd)]  # hourly while broken

    def test_scheduled_job_skips_suspended_businesses(self, tenant_a, dns, monkeypatch):
        import apps.licensing.services as licensing

        cd = added()
        dns.ready(cd)
        allowed = {"tenant_a": False}
        original = licensing.is_access_allowed
        monkeypatch.setattr(licensing, "is_access_allowed", lambda t: allowed.get(t.schema_name, True) and original(t))
        assert tasks.check_custom_domains() == {}
        allowed["tenant_a"] = True
        assert tasks.check_custom_domains() == {C.LIVE: 1}


# ---------------------------------------------------------------------------
# Routing, the host check and HTTPS certificates
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRouting:
    def live(self, dns):
        cd = added()
        dns.ready(cd)
        return check(cd)

    def test_a_live_domain_opens_the_business(self, tenant_a, dns):
        cd = self.live(dns)
        response = https_client("gorkha.co.nz").get("/health/")
        assert response.status_code == 200
        login = https_client("gorkha.co.nz").get("/admin/login/")
        assert login.status_code == 302 and login["Location"] == "https://tenant-a.localhost/admin/login/"  # not the main address yet
        with schema_context("public"):
            cdm.make_main_by_business(fresh(cd).domain)
        assert https_client("gorkha.co.nz").get("/admin/login/").status_code == 200
        www = https_client("www.gorkha.co.nz").get("/admin/login/")
        assert www.status_code == 302 and www["Location"] == "https://gorkha.co.nz/admin/login/"

    def test_a_waiting_or_unknown_domain_does_not(self, tenant_a, dns):
        with schema_context("public"):  # an address row that is not an own domain is still bound by DJANGO_ALLOWED_HOSTS
            Domain.objects.create(tenant=tenant(), domain="odd.example.org", is_primary=False)
        assert https_client("odd.example.org").get("/health/").status_code == 404
        added()
        assert https_client("gorkha.co.nz").get("/health/").status_code == 404
        assert https_client("someone-else.co.nz").get("/health/").status_code == 404

    def test_post_with_csrf_on_the_own_domain(self, tenant_a, dns):
        cd = self.live(dns)
        with schema_context("public"):
            cdm.make_main_by_business(fresh(cd).domain)
        make_user("tenant_a", "it@a.test", staff=True)
        client = https_client("gorkha.co.nz")
        client.enforce_csrf_checks = True
        page = client.get("/admin/login/")
        token = page.cookies["csrftoken"].value
        response = client.post("/admin/login/", {"username": "it@a.test", "password": "wrong", "csrfmiddlewaretoken": token},
                               HTTP_REFERER="https://gorkha.co.nz/admin/login/", HTTP_ORIGIN="https://gorkha.co.nz")
        assert response.status_code == 200  # the form came back (wrong password), not a CSRF error (403)

    def test_caddy_may_get_certificates_only_for_real_addresses(self, tenant_a, dns):
        caddy = https_client("web:8000")

        def allowed(name):
            return caddy.get("/internal/tls-allowed/", {"domain": name}).status_code == 200

        cd = added()
        assert allowed("tenant-a.localhost") and allowed("localhost")
        assert not allowed("gorkha.co.nz") and not allowed("anything.co.nz") and not allowed("")
        dns.ready(cd)
        check(cd)
        assert allowed("gorkha.co.nz") and allowed("www.gorkha.co.nz") and allowed("GORKHA.co.nz.")
        assert not allowed("shop.gorkha.co.nz")
        assert caddy.post("/internal/tls-allowed/?domain=gorkha.co.nz").status_code == 404


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBusinessPage:
    def test_add_check_and_make_main(self, tenant_a, dns, it_admin):
        page = it_admin.get("/settings/web-addresses/").content.decode()
        assert "tenant-a.localhost" in page and "Add your own domain" in page
        response = it_admin.post("/settings/web-addresses/", {"action": "add", "name": "https://www.Gorkha.co.nz/"}, follow=True)
        page = response.content.decode()
        with schema_context("public"):
            cd = CustomDomain.objects.get()
        assert cd.added_by == "it@a.test" and cd.txt_value in page and "_anish1989-verify.gorkha.co.nz" in page and SERVER in page
        assert "tenant-a.localhost" in page  # the CNAME target
        dns.ready(cd)
        it_admin.post("/settings/web-addresses/", {"action": "check", "id": cd.pk})
        assert fresh(cd).status == C.LIVE
        again = it_admin.post("/settings/web-addresses/", {"action": "check", "id": cd.pk}, follow=True)
        assert "less than a minute ago" in again.content.decode()
        it_admin.post("/settings/web-addresses/", {"action": "main", "id": fresh(cd).domain_id})
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "gorkha.co.nz"
        with schema_context("tenant_a"):
            event = AuditEvent.objects.filter(action="tenant.main_address_changed").latest("id")
            assert (event.actor_type, event.actor_email) == ("user", "it@a.test")  # the business's own admin, not "platform"
        with schema_context("public"):
            event = AuditEvent.objects.filter(action="tenant.custom_domain_added").latest("id")
            assert (event.actor_email, event.actor_id, event.metadata["business"]) == ("it@a.test", None, "tenant_a")

    def test_a_broken_domain_cannot_become_main_and_the_main_cannot_be_removed(self, tenant_a, dns, it_admin):
        cd = added()
        dns.ready(cd)
        cd = check(cd)
        with schema_context("public"):
            CustomDomain.objects.filter(pk=cd.pk).update(status=C.FAILING)
        response = it_admin.post("/settings/web-addresses/", {"action": "main", "id": cd.domain_id}, follow=True)
        assert "has a DNS problem. Fix it first." in response.content.decode()
        with schema_context("public"):
            assert Domain.objects.get(tenant=tenant(), is_primary=True).domain == "tenant-a.localhost"
        with schema_context("public"):
            CustomDomain.objects.filter(pk=cd.pk).update(status=C.LIVE)
            cdm.make_main_by_business(fresh(cd).domain)
        response = it_admin.post("/settings/web-addresses/", {"action": "remove", "id": cd.pk}, follow=True)
        assert "This is the main address" in response.content.decode() and fresh(cd)

    def test_remove(self, tenant_a, dns, it_admin):
        cd = added()
        dns.ready(cd)
        check(cd)
        first = it_admin.post("/settings/web-addresses/", {"action": "remove", "id": cd.pk})
        assert "Remove gorkha.co.nz?" in first.content.decode()  # the safety check first (task 1.18)
        it_admin.post("/settings/web-addresses/", {"action": "remove", "id": cd.pk, **pass_delete_check(it_admin, first)})
        with schema_context("public"):
            assert not CustomDomain.objects.exists() and not Domain.objects.filter(domain="gorkha.co.nz").exists()

    def test_only_its_own_domains(self, tenant_a, tenant_b, dns, it_admin):
        other = added("other.co.nz", schema="tenant_b")
        dns.ready(other)
        other = check(other)
        checked = fresh(other).last_checked_at
        it_admin.post("/settings/web-addresses/", {"action": "check", "id": other.pk})
        assert fresh(other).last_checked_at == checked
        it_admin.post("/settings/web-addresses/", {"action": "main", "id": other.domain_id})
        removing = it_admin.post("/settings/web-addresses/", {"action": "remove", "id": other.pk}, follow=True).content.decode()
        assert "Remove other.co.nz?" not in removing and "does not belong to this business" in removing
        with schema_context("public"):
            assert Domain.objects.get(domain="other.co.nz").is_primary is False and CustomDomain.objects.filter(pk=other.pk).exists()
        assert "other.co.nz" not in it_admin.get("/settings/web-addresses/").content.decode()

    def test_who_may_see_and_change(self, client_for, tenant_a, dns):
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")  # Settings – View
        page = owner.get("/settings/web-addresses/")
        assert page.status_code == 200 and "Add your own domain" not in page.content.decode()
        assert owner.post("/settings/web-addresses/", {"action": "add", "name": "gorkha.co.nz"}).status_code == 403
        staff = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        assert staff.get("/settings/web-addresses/").status_code == 403


@pytest.mark.django_db
class TestSuperAdminAndChecks:
    def test_super_admin_sees_and_removes_own_domains(self, verified_admin_client, public_tenant, tenant_a, dns):
        cd = added()
        dns.ready(cd)
        cd = check(cd)
        boss = verified_admin_client(public_tenant, "boss@platform.test")
        url = "/platform/businesses/tenant_a/addresses/"
        page = boss.get(url).content.decode()
        assert "gorkha.co.nz" in page and "Live" in page
        response = boss.post(url, {"action": "remove", "domain": cd.domain_id}, follow=True)
        assert "Remove it in the list of own domains" in response.content.decode()
        first = boss.post(url, {"action": "remove_own", "custom": cd.pk})
        boss.post(url, {"action": "remove_own", "custom": cd.pk, **pass_delete_check(boss, first)})
        with schema_context("public"):
            assert not CustomDomain.objects.exists() and not Domain.objects.filter(domain="gorkha.co.nz").exists()

    def test_own_domains_do_not_count_as_platform_addresses(self, tenant_a, dns):
        cd = added()
        dns.ready(cd)
        check(cd)
        with schema_context("public"):
            for n in range(domains.MAX_SUBDOMAINS - 1):
                domains.add_subdomain(tenant(), f"extra{n}")
            with pytest.raises(ValidationError, match="up to 5"):
                domains.add_subdomain(tenant(), "extra9")

    def test_check_system(self, tenant_a, dns):
        assert check_custom_domains(tenant())[0].status == "not_set_up"
        cd = added()
        assert check_custom_domains(tenant())[0].status == "warning"
        dns.ready(cd)
        check(cd)
        result = check_custom_domains(tenant())[0]
        assert (result.status, result.message) == ("ok", "Live: gorkha.co.nz.")
        with schema_context("public"):
            CustomDomain.objects.update(status=C.FAILING)
        assert check_custom_domains(tenant())[0].status == "failed"
