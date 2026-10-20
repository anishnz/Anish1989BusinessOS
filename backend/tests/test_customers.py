"""Customers, phone numbers, marketing consent and privacy (task 1.6)."""
import csv
import io
import json

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.customers import services
from apps.customers.models import ConsentRecord, Customer
from tests.test_catalog import csv_file, user_client
from tests.test_rbac import verified_staff_client

PHONE = "+64211234567"


@pytest.fixture
def staff(client_for, tenant_a):
    return user_client(client_for, tenant_a, "sales@a.test", "sales_manager")  # all crm permissions


def make_customer(schema="tenant_a", **kw):
    data = {"name": "Sita Sharma", "phone": PHONE, "email": "sita@example.test"}
    data.update(kw)
    with schema_context(schema):
        return Customer.objects.create(**data)


def all_audit_text(schema="tenant_a") -> str:
    with schema_context(schema):
        return " ".join(json.dumps([e.changes, e.metadata, e.target_repr], default=str) for e in AuditEvent.objects.all())


class TestPhoneNumbers:
    @pytest.mark.parametrize(
        "typed,saved",
        [
            ("021 123 4567", PHONE),
            ("(021) 123-4567", PHONE),
            ("+64 21 123 4567", PHONE),
            ("0064211234567", PHONE),
            ("09 379 1234", "+6493791234"),
            ("+977 984 1234567", "+9779841234567"),
            ("", ""),
        ],
    )
    def test_numbers_are_saved_in_international_format(self, typed, saved):
        assert services.normalise_phone(typed) == saved

    @pytest.mark.parametrize("bad", ["12345", "phone me", "+1 555", "021 12"])
    def test_invalid_numbers_are_refused(self, bad):
        with pytest.raises(ValidationError):
            services.normalise_phone(bad)


@pytest.mark.django_db
class TestCustomerApi:
    def test_create_normalises_phone_and_email(self, staff, tenant_a):
        response = staff.post("/api/customers/", {"name": " Ram ", "phone": "021 123 4567", "email": "Ram@Example.TEST", "tags": "regular, halal"}, content_type="application/json")
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["phone"] == PHONE and body["email"] == "ram@example.test" and body["name"] == "Ram"
        assert body["tag_list"] == ["regular", "halal"] and body["source"] == "manual" and body["marketing_consent"] is False

    @pytest.mark.parametrize("field,value", [("phone", "0211234567"), ("email", "SITA@example.test")])
    def test_duplicates_are_refused(self, staff, field, value):
        make_customer()
        data = {"name": "Someone", field: value}
        response = staff.post("/api/customers/", data, content_type="application/json")
        assert response.status_code == 400 and "already belongs" in str(response.json())

    def test_bad_phone_is_refused(self, staff):
        response = staff.post("/api/customers/", {"name": "X", "phone": "123"}, content_type="application/json")
        assert response.status_code == 400 and "phone" in response.json()

    def test_consent_cannot_be_set_by_patch(self, staff):
        customer = make_customer()
        staff.patch(f"/api/customers/{customer.pk}/", {"marketing_consent": True}, content_type="application/json")
        customer.refresh_from_db()
        assert customer.marketing_consent is False

    def test_consent_is_recorded_with_history(self, staff, tenant_a):
        customer = make_customer()
        body = staff.post(f"/api/customers/{customer.pk}/consent/", {"given": True, "note": "Asked at the counter"}, content_type="application/json").json()
        assert body["marketing_consent"] is True and body["marketing_consent_at"]
        staff.post(f"/api/customers/{customer.pk}/consent/", {"given": False}, content_type="application/json")
        detail = staff.get(f"/api/customers/{customer.pk}/").json()
        assert detail["marketing_consent"] is False
        assert [(r["given"], r["source"]) for r in detail["consent_records"]] == [(False, "staff"), (True, "staff")]
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="crm.consent_given").exists()
            assert AuditEvent.objects.filter(action="crm.consent_withdrawn").exists()

    def test_search_by_phone_digits_name_and_tag(self, staff):
        make_customer(tags="wholesale")
        make_customer(name="Hari", phone="+6493791234", email="")
        assert [c["name"] for c in staff.get("/api/customers/?q=021 123").json()["results"]] == ["Sita Sharma"]
        assert staff.get("/api/customers/?q=hari").json()["count"] == 1
        assert staff.get("/api/customers/?tag=wholesale").json()["count"] == 1

    def test_delete_archives(self, staff):
        customer = make_customer()
        assert staff.delete(f"/api/customers/{customer.pk}/").json()["is_archived"] is True
        assert staff.get("/api/customers/").json()["count"] == 0
        assert staff.post(f"/api/customers/{customer.pk}/restore/").json()["is_archived"] is False

    def test_permissions(self, client_for, tenant_a):
        customer = make_customer()
        agent = user_client(client_for, tenant_a, "agent@a.test", "support_agent")  # crm.view only
        assert agent.get("/api/customers/").status_code == 200
        assert agent.post("/api/customers/", {"name": "X"}, content_type="application/json").status_code == 403
        assert agent.post(f"/api/customers/{customer.pk}/consent/", {"given": True}, content_type="application/json").status_code == 403
        assert agent.post(f"/api/customers/{customer.pk}/anonymise/").status_code == 403
        assert agent.get("/api/customers/export/").status_code == 403
        owner_less = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")  # no crm at all
        assert owner_less.get("/api/customers/").status_code == 403


@pytest.mark.django_db
class TestPrivacy:
    def test_audit_log_never_keeps_personal_details(self, staff):
        response = staff.post("/api/customers/", {"name": "Gita Thapa", "phone": "022 987 6543", "email": "gita@example.test", "address": "12 Queen St", "notes": "Allergic to nuts"}, content_type="application/json")
        cid = response.json()["id"]
        staff.patch(f"/api/customers/{cid}/", {"phone": "022 987 6544", "tags": "vip"}, content_type="application/json")
        text = all_audit_text()
        for secret in ("Gita", "Thapa", "9876543", "9876544", "gita@example", "Queen St", "Allergic"):
            assert secret not in text, secret
        with schema_context("tenant_a"):
            update = AuditEvent.objects.filter(action="customers.customer.update").latest("id")
        assert update.changes["phone"] == {"changed": True}
        assert update.changes["tags"] == {"from": "", "to": "vip"}

    def test_anonymise_removes_personal_data_but_keeps_the_record(self, staff, tenant_a):
        customer = make_customer(address="1 Main Rd", notes="likes lamb", tags="regular", marketing_consent=True)
        with schema_context("tenant_a"):
            services.set_marketing_consent(customer, True, source="staff", note="said yes in shop")
        body = staff.post(f"/api/customers/{customer.pk}/anonymise/").json()
        assert body["name"] == f"Removed customer #{customer.pk}"
        assert (body["phone"], body["email"], body["address"], body["notes"], body["tags"]) == ("", "", "", "", "")
        assert body["is_anonymised"] and body["is_archived"] and body["marketing_consent"] is False
        assert body["consent_records"][0]["note"] == ""
        assert staff.patch(f"/api/customers/{customer.pk}/", {"name": "Back"}, content_type="application/json").status_code == 400
        assert staff.post(f"/api/customers/{customer.pk}/restore/").status_code == 400
        # The same phone can be used for a new customer afterwards.
        assert staff.post("/api/customers/", {"name": "New", "phone": PHONE}, content_type="application/json").status_code == 201

    def test_isolation(self, client_for, tenant_a, tenant_b):
        customer = make_customer("tenant_a")
        other = user_client(client_for, tenant_b, "sales@b.test", "sales_manager")
        assert other.get("/api/customers/").json()["count"] == 0
        assert other.get(f"/api/customers/{customer.pk}/").status_code == 404
        assert other.post(f"/api/customers/{customer.pk}/anonymise/").status_code == 404
        # The same phone number can belong to customers of two different businesses.
        assert other.post("/api/customers/", {"name": "Sita", "phone": PHONE}, content_type="application/json").status_code == 201


@pytest.mark.django_db
class TestCustomerCsv:
    HEADER = ["name", "phone", "email", "tags", "marketing_consent"]

    def test_import_adds_updates_and_records_consent(self, tenant_a):
        make_customer(tags="old")
        rows = [self.HEADER, ["Sita S.", "021-123-4567", "", "regular", "yes"], ["Hari", "+977 984 1234567", "hari@example.test", "", ""]]
        with schema_context("tenant_a"):
            result = services.import_customers(csv_file(rows))
            assert result.as_dict() == {"dry_run": False, "ok": True, "created": 1, "updated": 1, "errors": []}
            sita = Customer.objects.get(phone=PHONE)
            assert sita.name == "Sita S." and sita.tags == "regular" and sita.email == "sita@example.test"
            assert sita.marketing_consent and sita.consent_records.get().source == ConsentRecord.Source.IMPORT
            assert Customer.objects.get(phone="+9779841234567").source == "import"

    def test_bad_rows_save_nothing(self, tenant_a):
        rows = [self.HEADER, ["Ok", "0211111111", "", "", ""], ["Bad phone", "123", "", "", ""], ["", "0212222222", "", "", ""], ["Twice", "021 111 1111", "", "", ""], ["Consent", "", "", "", "maybe"]]
        with schema_context("tenant_a"):
            result = services.import_customers(csv_file(rows))
            assert [e["row"] for e in result.errors] == [3, 4, 5, 6]
            assert not Customer.objects.exists()

    def test_clash_with_another_customer_is_reported(self, tenant_a):
        make_customer()
        rows = [["name", "phone", "email"], ["Other", "0219999999", "sita@example.test"]]
        with schema_context("tenant_a"):
            result = services.import_customers(csv_file(rows))
            assert not result.ok and "already belongs" in result.errors[0]["error"]

    def test_export_round_trip_and_hides_removed_customers(self, staff, tenant_a):
        make_customer()
        gone = make_customer(name="Gone", phone="+6493791234", email="")
        with schema_context("tenant_a"):
            services.anonymise(gone)
        response = staff.get("/api/customers/export/")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert len(rows) == 2 and rows[1][1] == "'" + PHONE  # protected from spreadsheet formulas
        with schema_context("tenant_a"):
            result = services.import_customers(SimpleUploadedFile("c.csv", response.content, content_type="text/csv"))
            assert result.ok and result.updated == 1 and result.created == 0
            assert AuditEvent.objects.filter(action="crm.export").exists()


@pytest.mark.django_db
class TestCustomerAdmin:
    def test_ticking_consent_in_admin_is_recorded(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "sales@a.test", "sales_manager")
        response = client.post("/admin/customers/customer/add/", {
            "name": "Maya", "phone": "021 555 0100", "email": "", "address": "", "tags": "", "preferred_language": "Nepali", "notes": "",
            "marketing_consent": "on",
            "consent_records-TOTAL_FORMS": "0", "consent_records-INITIAL_FORMS": "0",
        })
        assert response.status_code == 302, response.content.decode()[:2000]
        with schema_context("tenant_a"):
            maya = Customer.objects.get(name="Maya")
            assert maya.phone == "+64215550100" and maya.marketing_consent
            assert maya.consent_records.get().recorded_by.email == "sales@a.test"

    def test_duplicate_phone_shows_an_error(self, client_for, tenant_a):
        make_customer()
        client = verified_staff_client(client_for, tenant_a, "sales@a.test", "sales_manager")
        response = client.post("/admin/customers/customer/add/", {
            "name": "Copy", "phone": "0211234567", "consent_records-TOTAL_FORMS": "0", "consent_records-INITIAL_FORMS": "0",
        })
        assert response.status_code == 200 and "already belongs to Sita Sharma" in response.content.decode()

    def test_remove_personal_data_asks_first(self, client_for, tenant_a):
        customer = make_customer()
        client = verified_staff_client(client_for, tenant_a, "sales@a.test", "sales_manager")
        data = {"action": "anonymise", "_selected_action": [customer.pk]}
        page = client.post("/admin/customers/customer/", data)
        assert "cannot be undone" in page.content.decode()
        customer.refresh_from_db()
        assert not customer.is_anonymised
        client.post("/admin/customers/customer/", {**data, "confirm": "yes"})
        customer.refresh_from_db()
        assert customer.is_anonymised and customer.phone == ""

    def test_admin_history_forgets_the_name(self, client_for, tenant_a):
        from django.contrib.admin.models import LogEntry

        client = verified_staff_client(client_for, tenant_a, "sales@a.test", "sales_manager")
        client.post("/admin/customers/customer/add/", {"name": "Maya", "consent_records-TOTAL_FORMS": "0", "consent_records-INITIAL_FORMS": "0"})
        with schema_context("tenant_a"):
            maya = Customer.objects.get(name="Maya")
            assert LogEntry.objects.filter(object_repr="Maya").exists()
            services.anonymise(maya)
            assert not LogEntry.objects.filter(object_repr="Maya").exists()

    def test_view_only_staff_has_no_remove_action(self, client_for, tenant_a):
        make_customer()
        client = verified_staff_client(client_for, tenant_a, "agent@a.test", "support_agent")
        page = client.get("/admin/customers/customer/").content.decode()
        assert "Sita Sharma" in page and "anonymise" not in page
