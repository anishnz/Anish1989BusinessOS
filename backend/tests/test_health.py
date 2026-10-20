import pytest


@pytest.mark.django_db
class TestHealth:
    def test_platform_health_is_ok(self, client_for, public_tenant):
        response = client_for(public_tenant).get("/health/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}

    def test_tenant_health_is_ok(self, client_for, tenant_a):
        response = client_for(tenant_a).get("/health/")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_does_not_leak_internal_details(self, client_for, tenant_a):
        body = client_for(tenant_a).get("/health/").content.decode()
        assert "tenant_a" not in body
        assert "postgres" not in body.lower()

    def test_health_reports_503_when_cache_fails(self, client_for, tenant_a, monkeypatch):
        monkeypatch.setattr("apps.core.views.check_cache", lambda: False)
        response = client_for(tenant_a).get("/health/")
        assert response.status_code == 503
        assert response.json()["checks"]["cache"] == "failed"

    def test_health_only_allows_get(self, client_for, tenant_a):
        assert client_for(tenant_a).post("/health/").status_code == 405
