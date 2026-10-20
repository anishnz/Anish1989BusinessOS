"""The React staff screens are served at /app/ on business sites (task 1.11)."""
import pytest

from tests.conftest import PASSWORD, make_user
from tests.test_rbac import give_role


@pytest.fixture
def built_app(settings, tmp_path):
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div><script type="module" src="/static/app/assets/app.js"></script>')
    settings.FRONTEND_DIST = tmp_path
    return tmp_path


@pytest.mark.django_db
class TestAppPage:
    @pytest.mark.parametrize("path", ["/app/", "/app/orders/12", "/app/inbox/3"])
    def test_every_app_address_gets_the_page(self, client_for, tenant_a, built_app, path):
        response = client_for(tenant_a).get(path)
        assert response.status_code == 200 and b'id="root"' in response.content
        assert "default-src 'self'" in response["Content-Security-Policy"]
        assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]

    def test_not_built_yet(self, client_for, tenant_a, settings, tmp_path):
        settings.FRONTEND_DIST = tmp_path / "missing"
        response = client_for(tenant_a).get("/app/")
        assert response.status_code == 503 and b"not built" in response.content

    def test_not_on_the_platform_site(self, client_for, public_tenant, built_app):
        assert client_for(public_tenant).get("/app/").status_code == 404

    def test_only_get(self, client_for, tenant_a, built_app):
        assert client_for(tenant_a).post("/app/").status_code == 405


@pytest.mark.django_db
class TestApisTheAppUses:
    def test_csrf_token_and_my_permissions(self, client_for, tenant_a):
        user = make_user("tenant_a", "staff@a.test")
        give_role("tenant_a", user, "shop_staff")
        client = client_for(tenant_a)
        before = client.get("/api/auth/csrf/").json()
        assert before["csrfToken"] and before["authenticated"] is False
        client.post("/api/auth/login/", {"email": "staff@a.test", "password": PASSWORD})
        assert client.get("/api/auth/csrf/").json()["authenticated"] is True
        body = client.get("/api/rbac/me/permissions/").json()
        assert body["business"] == {"name": "Tenant A Butchery", "id": "tenant_a"}
        assert "orders.create" in body["usable"] and "reports.view" not in body["usable"]

    def test_usable_drops_switched_off_modules(self, client_for, tenant_a):
        from apps.licensing.services import set_module_enabled

        user = make_user("tenant_a", "staff@a.test")
        give_role("tenant_a", user, "shop_staff")
        client = client_for(tenant_a)
        client.post("/api/auth/login/", {"email": "staff@a.test", "password": PASSWORD})
        set_module_enabled(tenant_a, "orders", False)
        try:
            body = client.get("/api/rbac/me/permissions/").json()
            assert "orders.view" in body["permissions"] and "orders.view" not in body["usable"]
        finally:
            set_module_enabled(tenant_a, "orders", True)
