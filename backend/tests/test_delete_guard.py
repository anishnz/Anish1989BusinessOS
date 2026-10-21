"""
Safer deleting (task 1.18, D-129): admin delete pages, "Delete selected",
the Remove buttons of integrations and web addresses all need the answer to
a small sum and a 5-second wait. The server checks both; each sum works once.
"""
import pytest
from django_tenants.utils import schema_context

from apps.core import deleteguard
from apps.catalog.models import Category
from tests.conftest import pass_delete_check
from tests.test_rbac import verified_staff_client


@pytest.fixture
def customer(tenant_a):
    """A record the Business Owner may delete (a product category)."""
    with schema_context("tenant_a"):
        return Category.objects.create(name="Khasi (goat)")


def exists(pk) -> bool:
    with schema_context("tenant_a"):
        return Category.objects.filter(pk=pk).exists()


@pytest.mark.django_db
class TestAdminDelete:
    def test_the_page_asks_a_sum_and_waits(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        page = client.get(f"/admin/catalog/category/{customer.pk}/delete/").content.decode()
        assert "What is " in page and 'name="guard_token"' in page and "works in <strong>5</strong> seconds" in page
        assert "Last check: delete permanently?" in page

    def test_without_the_check_nothing_is_deleted(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        url = f"/admin/catalog/category/{customer.pk}/delete/"
        response = client.post(url, {"post": "yes"}, follow=True)
        assert "Not deleted: Answer the sum on the delete page first." in response.content.decode() and exists(customer.pk)

    def test_wrong_answer_too_fast_and_used_twice(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        url = f"/admin/catalog/category/{customer.pk}/delete/"
        fields = pass_delete_check(client, client.get(url))
        wrong = {**fields, "guard_answer": str(int(fields["guard_answer"]) + 1)}
        assert "not correct" in client.post(url, {"post": "yes", **wrong}, follow=True).content.decode() and exists(customer.pk)
        assert "Answer the sum" in client.post(url, {"post": "yes", **fields}, follow=True).content.decode()  # that sum is used up
        page = client.get(url)
        token = page.content.decode().split('name="guard_token" value="')[1].split('"')[0]
        fast = {"guard_token": token, "guard_answer": str(client.session["delete_guard"][token]["answer"])}
        assert "Too fast: wait 5 seconds" in client.post(url, {"post": "yes", **fast}, follow=True).content.decode() and exists(customer.pk)

    def test_with_the_check_it_is_deleted(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        url = f"/admin/catalog/category/{customer.pk}/delete/"
        assert client.post(url, {"post": "yes", **pass_delete_check(client, client.get(url))}).status_code == 302
        assert not exists(customer.pk)

    def test_delete_selected(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        data = {"action": "delete_selected", "_selected_action": [customer.pk]}
        page = client.post("/admin/catalog/category/", data)
        assert "What is " in page.content.decode()
        refused = client.post("/admin/catalog/category/", {**data, "post": "yes"}, follow=True)
        assert "Not deleted" in refused.content.decode() and exists(customer.pk)
        client.post("/admin/catalog/category/", {**data, "post": "yes", **pass_delete_check(client, page)})
        assert not exists(customer.pk)

    def test_old_pages_expire(self, client_for, tenant_a, customer):
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        url = f"/admin/catalog/category/{customer.pk}/delete/"
        fields = pass_delete_check(client, client.get(url))
        session = client.session
        session["delete_guard"][fields["guard_token"]]["at"] -= deleteguard.VALID_SECONDS
        session.save()
        assert "open too long" in client.post(url, {"post": "yes", **fields}, follow=True).content.decode() and exists(customer.pk)


@pytest.mark.django_db
class TestRemoveButtons:
    def test_integration_remove(self, client_for, tenant_a):
        from apps.vault import services as vault
        from apps.vault.models import Connection

        with schema_context("tenant_a"):
            conn = vault.create_connection(provider_code="gmail", label="Shop Gmail", config={"email": "shop@gmail.test"},
                                           secrets={"app_password": "abcd efgh ijkl mnop"})
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        url = f"/settings/integrations/{conn.pk}/delete/"
        page = client.post(url)
        assert page.status_code == 200 and "Remove Shop Gmail?" in page.content.decode()
        bad = client.post(url, {"guard_token": "nope", "guard_answer": "3"})
        assert bad.status_code == 400 and "Not deleted" in bad.content.decode()
        with schema_context("tenant_a"):
            assert Connection.objects.filter(pk=conn.pk).exists()
        assert client.post(url, pass_delete_check(client, bad)).status_code == 302
        with schema_context("tenant_a"):
            assert not Connection.objects.filter(pk=conn.pk).exists()

    def test_the_store_keeps_at_most_20_open_sums(self, rf):
        from django.contrib.sessions.backends.signed_cookies import SessionStore

        request = rf.get("/")
        request.session = SessionStore()
        tokens = [deleteguard.issue(request)["token"] for _ in range(25)]
        assert len(request.session[deleteguard.SESSION_KEY]) == deleteguard.MAX_OPEN
        assert tokens[-1] in request.session[deleteguard.SESSION_KEY]
