"""Products and categories (task 1.6)."""
import csv
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.catalog import services
from apps.catalog.models import Category, Product, gst_in
from apps.licensing.services import set_module_enabled
from tests.conftest import make_user
from tests.test_rbac import api_client, give_role, verified_staff_client


def user_client(client_for, tenant, email, role):
    user = make_user(tenant.schema_name, email)
    give_role(tenant.schema_name, user, role)
    return api_client(client_for, tenant, email)


@pytest.fixture
def manager(client_for, tenant_a):
    return user_client(client_for, tenant_a, "stock@a.test", "inventory_manager")


@pytest.fixture
def rep(client_for, tenant_a):
    return user_client(client_for, tenant_a, "rep@a.test", "sales_rep")  # products.view only


def make_product(schema="tenant_a", **kw):
    data = {"name": "Goat curry cut", "unit": "kg", "price": Decimal("23.00"), "sku": "GOAT-1", "search_terms": "khasi ko masu, mutton"}
    data.update(kw)
    with schema_context(schema):
        return Product.objects.create(**data)


def csv_file(rows, name="products.csv", encoding="utf-8"):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(name, buffer.getvalue().encode(encoding), content_type="text/csv")


# ---------------------------------------------------------------------------
# Model rules
# ---------------------------------------------------------------------------
class TestGst:
    @pytest.mark.parametrize("price,gst", [("23.00", "3.00"), ("11.50", "1.50"), ("10.00", "1.30"), ("0", "0.00")])
    def test_gst_is_three_twenty_thirds(self, price, gst):
        assert gst_in(Decimal(price)) == Decimal(gst)


@pytest.mark.django_db
class TestProductApi:
    def test_create_and_read(self, manager, tenant_a):
        cat = manager.post("/api/products/categories/", {"name": "Goat"}, content_type="application/json").json()
        response = manager.post(
            "/api/products/",
            {"name": "Goat curry cut", "sku": "G1", "category": cat["id"], "unit": "kg", "price": "23.00", "cost_price": "15.00", "min_quantity": "0.5", "quantity_step": "0.5"},
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["gst_amount"] == "3.00" and body["sold_by_weight"] is True and body["category_name"] == "Goat"
        with schema_context("tenant_a"):
            assert Product.objects.get(pk=body["id"]).created_by.email == "stock@a.test"

    @pytest.mark.parametrize(
        "bad",
        [{"price": "-1"}, {"min_quantity": "0"}, {"quantity_step": "-0.5"}, {"name": "  "}, {"unit": "litre"}, {"price": "abc"}],
    )
    def test_invalid_values_are_rejected(self, manager, bad):
        data = {"name": "X", "price": "1.00", **bad}
        assert manager.post("/api/products/", data, content_type="application/json").status_code == 400

    def test_sku_must_be_unique_ignoring_case(self, manager):
        make_product(sku="GOAT-1")
        response = manager.post("/api/products/", {"name": "Y", "sku": "goat-1", "price": "1"}, content_type="application/json")
        assert response.status_code == 400 and "SKU" in str(response.json())

    def test_category_name_must_be_unique(self, manager):
        manager.post("/api/products/categories/", {"name": "Goat"}, content_type="application/json")
        assert manager.post("/api/products/categories/", {"name": "goat"}, content_type="application/json").status_code == 400

    def test_cost_price_only_for_people_who_can_edit(self, manager, rep):
        product = make_product(cost_price=Decimal("15.00"))
        assert manager.get(f"/api/products/{product.pk}/").json()["cost_price"] == "15.00"
        assert "cost_price" not in rep.get(f"/api/products/{product.pk}/").json()
        assert "cost_price" not in rep.get("/api/products/").json()["results"][0]

    def test_view_only_role_cannot_change(self, rep):
        product = make_product()
        assert rep.post("/api/products/", {"name": "X", "price": "1"}, content_type="application/json").status_code == 403
        assert rep.patch(f"/api/products/{product.pk}/", {"price": "1"}, content_type="application/json").status_code == 403
        assert rep.delete(f"/api/products/{product.pk}/").status_code == 403

    def test_delete_archives_and_restore_brings_back(self, manager):
        product = make_product()
        assert manager.delete(f"/api/products/{product.pk}/").json()["is_archived"] is True
        assert manager.get("/api/products/").json()["count"] == 0
        assert manager.get("/api/products/?archived=true").json()["count"] == 1
        assert manager.post(f"/api/products/{product.pk}/restore/").json()["is_archived"] is False
        with schema_context("tenant_a"):
            assert Product.objects.filter(pk=product.pk).exists()

    def test_search_uses_other_names(self, manager):
        make_product()
        make_product(name="Chicken breast", sku="CH-1", search_terms="")
        assert [p["name"] for p in manager.get("/api/products/?q=khasi").json()["results"]] == ["Goat curry cut"]
        assert manager.get("/api/products/?q=ch-1").json()["count"] == 1
        assert manager.get("/api/products/?available=false").json()["count"] == 0
        assert manager.get("/api/products/?category=abc").json()["count"] == 0

    def test_switched_off_module_is_blocked(self, manager, tenant_a):
        make_product()
        set_module_enabled(tenant_a, "products", False)
        assert manager.get("/api/products/").status_code == 403
        set_module_enabled(tenant_a, "products", True)
        assert manager.get("/api/products/").status_code == 200

    def test_audit_records_changes(self, manager):
        product = make_product()
        manager.patch(f"/api/products/{product.pk}/", {"price": "25.00"}, content_type="application/json")
        with schema_context("tenant_a"):
            event = AuditEvent.objects.filter(action="catalog.product.update").latest("id")
        assert event.changes["price"] == {"from": "23.00", "to": "25.00"}
        assert event.actor_email == "stock@a.test"


@pytest.mark.django_db
class TestIsolation:
    def test_businesses_never_see_each_others_products(self, client_for, tenant_a, tenant_b):
        product = make_product("tenant_a")
        other = user_client(client_for, tenant_b, "stock@b.test", "inventory_manager")
        assert other.get("/api/products/").json()["count"] == 0
        assert other.get(f"/api/products/{product.pk}/").status_code == 404
        assert other.patch(f"/api/products/{product.pk}/", {"price": "0"}, content_type="application/json").status_code == 404

    def test_platform_site_has_no_products(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        assert client.get("/api/products/").status_code == 404
        index = client.get("/admin/").content.decode()
        assert "/admin/catalog/" not in index and "/admin/customers/" not in index
        assert client.get("/admin/catalog/product/").status_code in (403, 404)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
HEADER = ["sku", "name", "category", "unit", "price", "cost_price", "available", "search_terms"]


@pytest.mark.django_db
class TestCsvImport:
    def test_adds_updates_and_creates_categories(self, tenant_a):
        make_product(sku="GOAT-1", price=Decimal("20.00"))
        upload = csv_file([HEADER, ["goat-1", "Goat curry cut", "Goat", "kg", "$24.50", "16", "yes", ""], ["", "Lamb chops", "Lamb", "per kg", "29.99", "", "no", "lamb"]])
        with schema_context("tenant_a"):
            result = services.import_products(upload)
            assert result.as_dict() == {"dry_run": False, "ok": True, "created": 1, "updated": 1, "errors": []}
            goat = Product.objects.get(sku__iexact="GOAT-1")
            assert goat.price == Decimal("24.50") and goat.category.name == "Goat"
            lamb = Product.objects.get(name="Lamb chops")
            assert lamb.unit == "kg" and lamb.is_available is False
            assert set(Category.objects.values_list("name", flat=True)) == {"Goat", "Lamb"}
            assert AuditEvent.objects.filter(action="products.import").exists()

    def test_check_only_saves_nothing(self, tenant_a):
        with schema_context("tenant_a"):
            result = services.import_products(csv_file([HEADER, ["A1", "Apple", "Fruit", "each", "1", "", "", ""]]), dry_run=True)
            assert result.ok and result.created == 1
            assert not Product.objects.exists() and not Category.objects.exists()

    def test_one_bad_row_saves_nothing(self, tenant_a):
        rows = [HEADER, ["A1", "Apple", "", "each", "1", "", "", ""], ["A2", "Pear", "", "each", "-3", "", "", ""], ["A3", "", "", "each", "1", "", "", ""], ["A1", "Again", "", "each", "1", "", "", ""]]
        with schema_context("tenant_a"):
            result = services.import_products(csv_file(rows))
            assert not result.ok
            assert [e["row"] for e in result.errors] == [3, 4, 5]
            assert not Product.objects.exists()

    @pytest.mark.parametrize(
        "rows,message",
        [
            ([["name"], ["Apple"]], "price"),
            ([["name", "price", "colour"], ["Apple", "1", "red"]], "Unknown column"),
            ([["name", "price"]], "no rows"),
        ],
    )
    def test_file_problems(self, tenant_a, rows, message):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"), pytest.raises(ValidationError, match=message):
            services.import_products(csv_file(rows))

    def test_not_utf8_is_refused(self, tenant_a):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"), pytest.raises(ValidationError, match="UTF-8"):
            services.import_products(SimpleUploadedFile("p.csv", "name,price\nCafé,1\n".encode("utf-16"), content_type="text/csv"))

    def test_api_import_needs_import_permission(self, manager, rep):
        upload = csv_file([["name", "price"], ["Apple", "1"]])
        assert rep.post("/api/products/import/", {"file": upload}).status_code == 403
        response = manager.post("/api/products/import/", {"file": csv_file([["name", "price"], ["Apple", "1"]]), "dry_run": "true"})
        assert response.status_code == 200 and response.json()["dry_run"] is True


@pytest.mark.django_db
class TestCsvExport:
    def test_export_protects_against_formulas_and_round_trips(self, manager, tenant_a):
        make_product(name="=HYPERLINK(\"http://evil\")", sku="E1", cost_price=Decimal("9.00"), min_quantity=Decimal("0.500"))
        response = manager.get("/api/products/export/")
        assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
        text = response.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == services.CSV_COLUMNS
        assert rows[1][1].startswith("'=")
        assert rows[1][5] == "9.00" and rows[1][7] == "0.5"
        with schema_context("tenant_a"):
            result = services.import_products(SimpleUploadedFile("p.csv", response.content, content_type="text/csv"))
            assert result.ok and result.updated == 1 and result.created == 0
            assert Product.objects.get(sku="E1").name == "=HYPERLINK(\"http://evil\")"

    def test_export_hides_cost_without_edit_permission(self, client_for, tenant_a):
        from apps.rbac.models import Role

        with schema_context("tenant_a"):
            role = Role.objects.create(slug="exporter", name="Exporter")
            role.set_permissions({"products.view", "products.export"})
        make_product(cost_price=Decimal("9.00"))
        client = user_client(client_for, tenant_a, "exp@a.test", "exporter")
        rows = list(csv.reader(io.StringIO(client.get("/api/products/export/").content.decode("utf-8-sig"))))
        assert rows[1][5] == ""
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="products.export", metadata__cost_included=False).exists()

    def test_export_needs_permission(self, rep):
        assert rep.get("/api/products/export/").status_code == 403


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestProductAdmin:
    def test_manager_sees_list_import_and_export(self, client_for, tenant_a):
        make_product()
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        page = client.get("/admin/catalog/product/").content.decode()
        assert "Goat curry cut" in page and "Import CSV" in page and "Export CSV" in page
        response = client.post("/admin/catalog/product/import/", {"file": csv_file([["name", "price"], ["Apple", "1"]]), "check": "1"})
        assert "would add 1" in response.content.decode()
        with schema_context("tenant_a"):
            assert not Product.objects.filter(name="Apple").exists()
        assert client.get("/admin/catalog/product/export/").status_code == 200

    def test_archived_products_are_hidden_by_default(self, client_for, tenant_a):
        make_product(is_archived=True)
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        assert "Goat curry cut" not in client.get("/admin/catalog/product/").content.decode()
        assert "Goat curry cut" in client.get("/admin/catalog/product/?archived=yes").content.decode()

    def test_view_only_staff_cannot_see_cost_or_import(self, client_for, tenant_a):
        product = make_product(cost_price=Decimal("15.00"))
        client = verified_staff_client(client_for, tenant_a, "rep@a.test", "sales_rep")
        page = client.get(f"/admin/catalog/product/{product.pk}/change/").content.decode()
        assert "Goat curry cut" in page and "15.00" not in page
        assert "Import CSV" not in client.get("/admin/catalog/product/").content.decode()
        assert client.get("/admin/catalog/product/import/").status_code == 403

    def test_products_cannot_be_hard_deleted_in_admin(self, client_for, tenant_a):
        product = make_product()
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        assert client.get(f"/admin/catalog/product/{product.pk}/delete/").status_code == 403
