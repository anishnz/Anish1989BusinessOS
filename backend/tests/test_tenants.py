import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant, subdomain_for, validate_slug


def schema_tables(schema: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [schema])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
class TestTenantCreation:
    def test_each_tenant_has_its_own_schema(self, tenant_a, tenant_b):
        with connection.cursor() as cursor:
            cursor.execute("SELECT schema_name FROM information_schema.schemata")
            schemas = {row[0] for row in cursor.fetchall()}
        assert {"public", "tenant_a", "tenant_b"} <= schemas

    def test_tenant_gets_platform_subdomain(self, tenant_a, settings):
        assert tenant_a.get_primary_domain().domain == f"tenant-a.{settings.PLATFORM_DOMAIN}"

    def test_tenant_registry_lives_only_in_public_schema(self, tenant_a):
        assert "tenants_tenant" in schema_tables("public")
        assert "tenants_tenant" not in schema_tables("tenant_a")
        assert "tenants_domain" not in schema_tables("tenant_a")

    def test_tenant_schema_has_its_own_users_table(self, tenant_a, tenant_b):
        assert "accounts_user" in schema_tables("tenant_a")
        assert "accounts_user" in schema_tables("tenant_b")
        assert "accounts_user" in schema_tables("public")

    def test_new_tenant_starts_in_trial(self, tenant_a):
        assert tenant_a.status == Tenant.Status.TRIAL
        assert tenant_a.industry == Tenant.Industry.BUTCHERY

    def test_duplicate_slug_is_rejected(self, tenant_a):
        with pytest.raises(ValidationError):
            create_tenant("Another", "tenant_a", "butchery")

    def test_unknown_industry_is_rejected(self):
        with pytest.raises(ValidationError):
            create_tenant("Another", "tenant_x", "spaceship")

    def test_platform_industry_cannot_be_used_for_a_business(self):
        with pytest.raises(ValidationError):
            create_tenant("Another", "tenant_x", "platform")


class TestSlugValidation:
    @pytest.mark.parametrize("slug", ["gorkhabutchery", "joes_catering", "abc", "a1_b2"])
    def test_valid_slugs(self, slug):
        assert validate_slug(slug) == slug

    def test_slug_is_lowercased(self):
        assert validate_slug("  GorkhaButchery ") == "gorkhabutchery"

    @pytest.mark.parametrize(
        "slug", ["ab", "1abc", "has-dash", "has space", "gorkha!", "public", "admin", "www", "pg_temp", "x" * 41]
    )
    def test_invalid_or_reserved_slugs(self, slug):
        with pytest.raises(ValidationError):
            validate_slug(slug)

    def test_subdomain_uses_hyphens(self, settings):
        settings.PLATFORM_DOMAIN = "example.nz"
        assert subdomain_for("joes_catering") == "joes-catering.example.nz"
