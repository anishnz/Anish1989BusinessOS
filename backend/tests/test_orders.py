"""Basic orders (task 1.7)."""
import csv
import io
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.customers.services import anonymise
from apps.licensing.services import set_module_enabled
from apps.orders import services
from apps.orders.models import Order, OrderEvent
from tests.conftest import pass_delete_check
from tests.test_catalog import make_product, user_client
from tests.test_rbac import verified_staff_client

S = Order.Status
L = services.LineInput


@pytest.fixture
def goods(tenant_a):
    """A product sold by weight and one sold each, plus a customer."""
    goat = make_product(name="Goat curry cut", sku="GOAT", unit="kg", price=Decimal("23.00"), min_quantity=Decimal("0.5"), quantity_step=Decimal("0.5"))
    samosa = make_product(name="Samosa 12 pack", sku="SAM", unit="pack", price=Decimal("15.00"), search_terms="")
    with schema_context("tenant_a"):
        customer = Customer.objects.create(name="Sita Sharma", phone="+64211234567")
    return {"goat": goat, "samosa": samosa, "customer": customer}


@pytest.fixture
def counter(client_for, tenant_a):
    return user_client(client_for, tenant_a, "counter@a.test", "shop_staff")


def new_order(goods, lines=None, **kw):
    lines = lines or [L(goods["goat"].pk, Decimal("1.5")), L(goods["samosa"].pk, Decimal("2"))]
    with schema_context("tenant_a"):
        return services.create_order(lines=lines, customer=kw.pop("customer", goods["customer"]), **kw)


def move(order, *statuses, **kw):
    with schema_context("tenant_a"):
        for status in statuses:
            order = services.change_status(order, status, **kw)
        return order


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreating:
    def test_prices_come_from_products_and_are_copied(self, goods):
        order = new_order(goods)
        assert order.number == 1001 and order.status == S.DRAFT
        assert order.estimated_total == order.total == Decimal("64.50")  # 1.5 x 23 + 2 x 15
        assert order.gst_total == Decimal("8.41")  # 4.50 + 3.91
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["goat"].pk).update(price=Decimal("99.00"), name="Renamed")
            line = order.lines.get(product=goods["goat"])
            assert (line.unit_price, line.product_name, line.unit) == (Decimal("23.00"), "Goat curry cut", "kg")
            assert order.events.get().to_status == S.DRAFT

    def test_numbers_go_up_per_business(self, goods, tenant_b):
        assert [new_order(goods).number for _ in range(3)] == [1001, 1002, 1003]
        other = make_product("tenant_b", sku="B1", unit="each", min_quantity=Decimal("1"), quantity_step=Decimal("1"))
        with schema_context("tenant_b"):
            assert services.create_order(lines=[L(other.pk, Decimal("1"))]).number == 1001

    @pytest.mark.parametrize(
        "quantity,message",
        [("0.25", "smallest amount"), ("1.2", "steps of 0.5"), ("0", "more than 0"), ("-1", "more than 0"), ("1.0001", "3 decimal"), ("20000", "at most")],
    )
    def test_amount_rules(self, goods, quantity, message):
        with pytest.raises(ValidationError, match=message):
            new_order(goods, [L(goods["goat"].pk, Decimal(quantity))])

    def test_pack_products_need_whole_numbers(self, goods):
        with pytest.raises(ValidationError, match="steps of 1"):
            new_order(goods, [L(goods["samosa"].pk, Decimal("1.5"))])

    @pytest.mark.parametrize("change", [{"is_available": False}, {"is_archived": True}])
    def test_unavailable_products_cannot_be_ordered(self, goods, change):
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["goat"].pk).update(**change)
        with pytest.raises(ValidationError):
            new_order(goods)

    def test_removed_customer_cannot_be_used(self, goods):
        with schema_context("tenant_a"):
            anonymise(goods["customer"])
        with pytest.raises(ValidationError, match="removed"):
            new_order(goods)

    def test_walk_in_order_without_customer(self, goods):
        order = new_order(goods, customer=None)
        assert order.customer is None
        with pytest.raises(ValidationError, match="customer"):
            move(order, S.AWAITING)
        assert move(order, S.CONFIRMED).status == S.CONFIRMED


@pytest.mark.django_db
class TestStatusFlow:
    def test_counter_order_without_weight_change(self, goods):
        order = new_order(goods, [L(goods["samosa"].pk, Decimal("1"))])
        order = move(order, S.CONFIRMED, S.PREPARING, S.READY, S.COMPLETED)
        assert order.status == S.COMPLETED and order.confirmed_at and order.completed_at
        with schema_context("tenant_a"):
            assert list(order.events.values_list("to_status", flat=True)) == [S.DRAFT, S.CONFIRMED, S.PREPARING, S.READY, S.COMPLETED]

    def test_weight_changes_need_the_customer_to_accept(self, goods):
        order = move(new_order(goods), S.AWAITING, S.CONFIRMED, S.PREPARING)
        with schema_context("tenant_a"):
            line = order.lines.get(product=goods["goat"])
        with pytest.raises(ValidationError, match="real weight"):
            move(order, S.READY)
        with schema_context("tenant_a"):
            order = services.set_weights(order, {line.pk: "1.58"})
        assert order.total == Decimal("66.34")  # 1.58 x 23 = 36.34 + 30
        assert order.estimated_total == Decimal("64.50")
        with pytest.raises(ValidationError, match="Send the final price"):
            move(order, S.READY)
        order = move(order, S.FINAL_SENT, S.FINAL_ACCEPTED, S.READY, S.COMPLETED)
        assert order.status == S.COMPLETED

    def test_same_weight_goes_straight_to_ready(self, goods):
        order = move(new_order(goods), S.CONFIRMED, S.PREPARING)
        with schema_context("tenant_a"):
            services.set_weights(order, {order.lines.get(product=goods["goat"]).pk: "1.5"})
        with pytest.raises(ValidationError, match="same as the estimate"):
            move(order, S.FINAL_SENT)
        assert move(order, S.READY).status == S.READY

    @pytest.mark.parametrize("bad", [(S.DRAFT, S.COMPLETED), (S.DRAFT, S.READY), (S.CONFIRMED, S.DRAFT)])
    def test_skipping_steps_is_refused(self, goods, bad):
        order = new_order(goods)
        if bad[0] == S.CONFIRMED:
            order = move(order, S.CONFIRMED)
        with pytest.raises(ValidationError, match="cannot go from"):
            move(order, bad[1])

    def test_cancel_needs_a_reason_and_closes_the_order(self, goods):
        order = move(new_order(goods), S.CONFIRMED)
        with pytest.raises(ValidationError, match="reason"):
            move(order, S.CANCELLED_SHOP)
        order = move(order, S.CANCELLED_SHOP, note="Sold out of goat")
        assert order.cancelled_at and services.allowed_moves(order) == []
        with pytest.raises(ValidationError):
            move(order, S.CONFIRMED)
        with pytest.raises(ValidationError, match="cannot be changed"), schema_context("tenant_a"):
            services.update_order(order, notes="x")

    def test_paid_order_cannot_be_cancelled_until_refunded(self, goods):
        order = move(new_order(goods), S.CONFIRMED)
        with schema_context("tenant_a"):
            order = services.set_paid(order, True, method="cash")
        with pytest.raises(ValidationError, match="refund"):
            move(order, S.CANCELLED_CUSTOMER, note="Changed mind")
        with schema_context("tenant_a"):
            order = services.set_paid(order, False)
        assert move(order, S.CANCELLED_CUSTOMER, note="Changed mind").status == S.CANCELLED_CUSTOMER

    def test_drafts_cannot_be_marked_paid(self, goods):
        with pytest.raises(ValidationError, match="confirmed"), schema_context("tenant_a"):
            services.set_paid(new_order(goods), True, method="cash")

    def test_lines_only_change_before_confirmation(self, goods):
        order = move(new_order(goods), S.AWAITING)
        with schema_context("tenant_a"):
            order = services.update_order(order, lines=[L(goods["samosa"].pk, Decimal("3"))])
            assert order.status == S.DRAFT  # customer must confirm again
            assert order.total == Decimal("45.00")
        order = move(order, S.CONFIRMED)
        with pytest.raises(ValidationError, match="draft or awaiting"), schema_context("tenant_a"):
            services.update_order(order, lines=[L(goods["samosa"].pk, Decimal("1"))])

    def test_weights_only_for_kg_lines_while_preparing(self, goods):
        order = move(new_order(goods), S.CONFIRMED)
        with schema_context("tenant_a"):
            samosa_line = order.lines.get(product=goods["samosa"])
        with pytest.raises(ValidationError, match="being prepared"), schema_context("tenant_a"):
            services.set_weights(order, {samosa_line.pk: "1"})
        order = move(order, S.PREPARING)
        with pytest.raises(ValidationError, match="not sold by weight"), schema_context("tenant_a"):
            services.set_weights(order, {samosa_line.pk: "1"})

    def test_only_drafts_can_be_deleted(self, goods):
        order = move(new_order(goods), S.CONFIRMED)
        with pytest.raises(ValidationError, match="Only draft"), schema_context("tenant_a"):
            services.delete_draft(order)

    def test_unconfirmed_orders_expire(self, goods, tenant_a):
        old = move(new_order(goods), S.AWAITING)
        fresh = move(new_order(goods), S.AWAITING)
        with schema_context("tenant_a"):
            Order.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timezone.timedelta(minutes=90))
        call_command("expire_orders", "--minutes", "60")
        with schema_context("tenant_a"):
            old.refresh_from_db()
            fresh.refresh_from_db()
        assert old.status == S.EXPIRED and fresh.status == S.AWAITING


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOrdersApi:
    def test_counter_staff_take_an_order_from_start_to_finish(self, counter, goods):
        response = counter.post(
            "/api/orders/",
            {"customer": goods["customer"].pk, "channel": "phone", "notes": "Small pieces", "lines": [
                {"product": goods["goat"].pk, "quantity": "1", "note": "", "unit_price": "0.01"},
                {"product": goods["samosa"].pk, "quantity": "1"},
            ]},
            content_type="application/json",
        )
        assert response.status_code == 201, response.content
        order = response.json()
        assert order["total"] == "38.00"  # the price in the request is ignored
        assert order["customer_name"] == "Sita Sharma" and order["status"] == "draft"
        assert set(order["next_statuses"]) == {"awaiting_confirmation", "confirmed", "cancelled_by_customer", "cancelled_by_shop"}
        oid = order["id"]
        for to in ("confirmed", "preparing"):
            assert counter.post(f"/api/orders/{oid}/status/", {"to": to}, content_type="application/json").status_code == 200
        goat_line = next(l for l in order["lines"] if l["unit"] == "kg")
        body = counter.post(f"/api/orders/{oid}/weights/", {"weights": {str(goat_line["id"]): "1.08"}}, content_type="application/json").json()
        assert body["total"] == "39.84"  # 1.08 x 23 = 24.84 + 15
        for to in ("final_price_sent", "final_price_accepted", "ready"):
            assert counter.post(f"/api/orders/{oid}/status/", {"to": to}, content_type="application/json").status_code == 200
        assert counter.post(f"/api/orders/{oid}/payment/", {"paid": True, "method": "card"}, content_type="application/json").json()["is_paid"]
        done = counter.post(f"/api/orders/{oid}/status/", {"to": "completed"}, content_type="application/json").json()
        assert done["status"] == "completed" and len(done["events"]) == 8 and done["events"][-1]["actor_email"] == "counter@a.test"

    def test_rule_errors_are_clear(self, counter, goods):
        response = counter.post("/api/orders/", {"lines": [{"product": goods["goat"].pk, "quantity": "0.3"}]}, content_type="application/json")
        assert response.status_code == 400 and "smallest amount is 0.5kg" in response.json()["detail"]
        assert counter.post("/api/orders/", {"lines": []}, content_type="application/json").status_code == 400
        oid = new_order(goods).pk
        response = counter.post(f"/api/orders/{oid}/status/", {"to": "completed"}, content_type="application/json")
        assert response.status_code == 400 and "cannot go from" in response.json()["detail"]
        assert counter.post(f"/api/orders/{oid}/weights/", {"weights": {"x": "1"}}, content_type="application/json").status_code == 400

    def test_filters(self, counter, goods):
        first = new_order(goods)
        move(new_order(goods), S.CONFIRMED, S.CANCELLED_SHOP, note="no stock")
        today = timezone.localdate().isoformat()
        assert counter.get("/api/orders/?open=true").json()["count"] == 1
        assert counter.get("/api/orders/?status=cancelled_by_shop").json()["count"] == 1
        assert counter.get(f"/api/orders/?q=%23{first.number}").json()["results"][0]["id"] == first.pk
        assert counter.get("/api/orders/?q=sita").json()["count"] == 2
        assert counter.get(f"/api/orders/?date={today}").json()["count"] == 2
        assert counter.get("/api/orders/?date=2020-01-01").json()["count"] == 0
        assert counter.get("/api/orders/?date=nonsense").json()["count"] == 0

    def test_permissions(self, client_for, tenant_a, goods):
        order = new_order(goods)
        viewer = user_client(client_for, tenant_a, "fin@a.test", "finance_manager")  # orders.view only
        assert viewer.get("/api/orders/").status_code == 200
        assert viewer.post(f"/api/orders/{order.pk}/status/", {"to": "confirmed"}, content_type="application/json").status_code == 403
        assert viewer.post("/api/orders/", {"lines": []}, content_type="application/json").status_code == 403
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        assert counter.delete(f"/api/orders/{order.pk}/").status_code == 403  # no orders.delete
        assert counter.get("/api/orders/export/").status_code == 403
        hr = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        assert hr.get("/api/orders/").status_code == 403

    def test_switched_off_module_is_blocked(self, counter, tenant_a, goods):
        set_module_enabled(tenant_a, "orders", False)
        assert counter.get("/api/orders/").status_code == 403
        set_module_enabled(tenant_a, "orders", True)

    def test_isolation(self, client_for, tenant_a, tenant_b, goods):
        order = new_order(goods)
        other = user_client(client_for, tenant_b, "counter@b.test", "shop_staff")
        assert other.get("/api/orders/").json()["count"] == 0
        assert other.get(f"/api/orders/{order.pk}/").status_code == 404
        assert other.post(f"/api/orders/{order.pk}/status/", {"to": "confirmed"}, content_type="application/json").status_code == 404
        # Business B cannot order business A's products or use its customers.
        response = other.post("/api/orders/", {"customer": goods["customer"].pk, "lines": [{"product": goods["goat"].pk, "quantity": "1"}]}, content_type="application/json")
        assert response.status_code == 400

    def test_audit_and_privacy(self, counter, goods):
        oid = counter.post("/api/orders/", {"notes": "Ring Sita on 021 999 8888", "lines": [{"product": goods["samosa"].pk, "quantity": "1"}]}, content_type="application/json").json()["id"]
        counter.post(f"/api/orders/{oid}/status/", {"to": "confirmed"}, content_type="application/json")
        with schema_context("tenant_a"):
            actions = set(AuditEvent.objects.values_list("action", flat=True))
            assert {"orders.create", "orders.status"} <= actions
            text = " ".join(str(e.changes) + str(e.metadata) + e.target_repr for e in AuditEvent.objects.all())
            assert "999 8888" not in text and "Sita" not in text

    def test_export(self, client_for, tenant_a, goods):
        order = move(new_order(goods), S.CONFIRMED)
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        rows = list(csv.reader(io.StringIO(owner.get("/api/orders/export/").content.decode("utf-8-sig"))))
        assert rows[0][0] == "order" and len(rows) == 3
        row = dict(zip(rows[0], rows[1]))
        assert row["order"] == str(order.number) and row["product"] == "Goat curry cut" and row["order_total"] == "64.50"
        assert row["fulfilment"] == "pickup" and row["delivery_fee"] == "0.00" and row["delivery_area"] == ""
        assert owner.get("/api/orders/export/?date_from=bad").status_code == 400


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
def inline(prefix, rows, initial=0):
    data = {f"{prefix}-TOTAL_FORMS": str(len(rows)), f"{prefix}-INITIAL_FORMS": str(initial), f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"}
    for i, row in enumerate(rows):
        for key, value in row.items():
            data[f"{prefix}-{i}-{key}"] = value
    return data


@pytest.mark.django_db
class TestOrdersAdmin:
    def test_add_order_with_lines(self, client_for, tenant_a, goods):
        client = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = {"customer": goods["customer"].pk, "channel": "counter", "fulfilment": "pickup", "notes": "",
                **inline("lines", [{"product": goods["goat"].pk, "quantity": "2", "note": ""}, {"product": goods["samosa"].pk, "quantity": "1", "note": ""}])}
        response = client.post("/admin/orders/order/add/", data)
        assert response.status_code == 302, response.content.decode()[:3000]
        with schema_context("tenant_a"):
            order = Order.objects.get()
            assert order.total == Decimal("61.00") and order.lines.count() == 2 and order.created_by.email == "counter@a.test"
            assert OrderEvent.objects.filter(order=order, to_status=S.DRAFT).exists()

    def test_bad_amount_shows_an_error(self, client_for, tenant_a, goods):
        client = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = {"channel": "counter", "fulfilment": "pickup", **inline("lines", [{"product": goods["goat"].pk, "quantity": "0.3", "note": ""}])}
        response = client.post("/admin/orders/order/add/", data)
        assert response.status_code == 200 and "smallest amount" in response.content.decode()
        with schema_context("tenant_a"):
            assert not Order.objects.exists()

    def test_status_page_and_weights(self, client_for, tenant_a, goods):
        order = move(new_order(goods), S.CONFIRMED, S.PREPARING)
        client = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        page = client.get(f"/admin/orders/order/{order.pk}/change/").content.decode()
        assert "real weight" in page and "Status and payment" in page
        with schema_context("tenant_a"):
            lines = list(order.lines.order_by("position"))
        data = {"customer": goods["customer"].pk, "channel": "counter", "fulfilment": "pickup", "notes": "", **inline("lines", [
            {"id": lines[0].pk, "order": order.pk, "final_quantity": "1.62"},
            {"id": lines[1].pk, "order": order.pk, "final_quantity": ""},
        ], initial=2)}
        response = client.post(f"/admin/orders/order/{order.pk}/change/", data)
        assert response.status_code == 302, response.content.decode()[:3000]
        with schema_context("tenant_a"):
            order.refresh_from_db()
        assert order.total == Decimal("67.26")  # 1.62 x 23 = 37.26 + 30
        response = client.post(f"/admin/orders/order/{order.pk}/status/", {"to": "final_price_sent", "note": "", "move": "1"})
        assert response.status_code == 302
        with schema_context("tenant_a"):
            order.refresh_from_db()
        assert order.status == S.FINAL_SENT
        page = client.post(f"/admin/orders/order/{order.pk}/status/", {"to": "cancelled_by_shop", "note": "", "move": "1"}).content.decode()
        assert "reason" in page

    def test_only_drafts_can_be_deleted_in_admin(self, client_for, tenant_a, goods):
        confirmed = move(new_order(goods), S.CONFIRMED)
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert client.get(f"/admin/orders/order/{confirmed.pk}/delete/").status_code == 403
        draft = new_order(goods)
        url = f"/admin/orders/order/{draft.pk}/delete/"
        assert client.post(url, {"post": "yes"}).status_code == 302  # no safety check: nothing deleted
        with schema_context("tenant_a"):
            assert Order.objects.filter(pk=draft.pk).exists()
        assert client.post(url, {"post": "yes", **pass_delete_check(client, client.get(url))}).status_code == 302
        with schema_context("tenant_a"):
            assert not Order.objects.filter(pk=draft.pk).exists()
            assert AuditEvent.objects.filter(action="orders.delete_draft").exists()

    def test_bulk_actions_report_problems(self, client_for, tenant_a, goods):
        draft = new_order(goods)
        client = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        response = client.post("/admin/orders/order/", {"action": "complete", "_selected_action": [draft.pk]}, follow=True)
        assert "cannot go from" in response.content.decode()
        client.post("/admin/orders/order/", {"action": "confirm", "_selected_action": [draft.pk]})
        with schema_context("tenant_a"):
            draft.refresh_from_db()
        assert draft.status == S.CONFIRMED
