"""
Stock (task 2.2, D-130 to D-134): counted products, changes by hand, orders
taking and giving back stock, customers stopped when stock is short, staff
warned, the history that cannot be changed, the API, the classic admin page,
CSV columns and the dashboard.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.catalog import services as catalog_services
from apps.catalog import stock
from apps.catalog.models import Product, StockMovement
from apps.customers.models import Customer
from apps.orders import services
from apps.orders.models import Order
from apps.reports import dashboard
from tests.test_catalog import csv_file, make_product, user_client
from tests.test_fulfilment import at, delivery, shop, tomorrow  # noqa: F401 (shop is a fixture)
from tests.test_orders import L, move, new_order
from tests.test_rbac import verified_staff_client

S = Order.Status
D = Decimal


def counted(product, amount=None, **fields):
    """Switch on "Count stock" (and receive `amount`)."""
    with schema_context("tenant_a"):
        Product.objects.filter(pk=product.pk).update(track_stock=True, **fields)
        product.refresh_from_db()
        if amount is not None:
            stock.adjust(product, reason="received", quantity=amount, note="first delivery")
        product.refresh_from_db()
    return product


def level(product) -> Decimal:
    with schema_context("tenant_a"):
        return Product.objects.get(pk=product.pk).stock_quantity


def reasons(product) -> list:
    with schema_context("tenant_a"):
        return list(StockMovement.objects.filter(product=product).order_by("id").values_list("reason", "change"))


@pytest.fixture
def goods(tenant_a):
    """Like the order tests' goods, but both products are counted: 10 kg goat and 20 samosa packs."""
    goat = make_product(name="Goat curry cut", sku="GOAT", unit="kg", price=D("23.00"), min_quantity=D("0.5"), quantity_step=D("0.5"))
    samosa = make_product(name="Samosa 12 pack", sku="SAM", unit="pack", price=D("15.00"), search_terms="")
    with schema_context("tenant_a"):
        customer = Customer.objects.create(name="Sita Sharma", phone="+64211234567")
    return {"goat": counted(goat, "10"), "samosa": counted(samosa, "20"), "customer": customer}


# ---------------------------------------------------------------------------
# Changes by hand
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdjust:
    def test_each_reason(self, tenant_a):
        goat = counted(make_product(min_quantity=D("0.5")))
        with schema_context("tenant_a"):
            m = stock.adjust(goat, reason="received", quantity="12.5", note=" truck ")
            assert (m.change, m.quantity_after, m.note) == (D("12.5"), D("12.5"), "truck")
            assert stock.adjust(goat, reason="waste", quantity="0.5", note="Dropped").change == D("-0.5")
            assert stock.adjust(goat, reason="counted", quantity="11").change == D("-1")
            assert stock.adjust(goat, reason="correction", quantity="-1.25", note="Counted wrong").quantity_after == D("9.75")
            assert stock.adjust(goat, reason="correction", quantity="0.25", note="Found a bag").quantity_after == D("10")
            assert Product.objects.get(pk=goat.pk).stock_quantity == D("10")
            event = AuditEvent.objects.filter(action="products.stock_adjusted").order_by("id").last()
            assert event.metadata == {"reason": "correction", "change": "0.25", "after": "10"}

    @pytest.mark.parametrize("reason,quantity,note,message", [
        ("received", "0", "", "more than 0"),
        ("received", "-2", "", "more than 0"),
        ("waste", "1", " ", "short note"),
        ("correction", "1", "", "short note"),
        ("correction", "0", "x", "cannot be 0"),
        ("counted", "-1", "", "below zero"),
        ("counted", "5", "", "already 5 kg"),
        ("received", "abc", "", "not a number"),
        ("received", "1.0001", "", "3 decimal"),
        ("received", "1000001", "", "3 decimal"),
        ("received", "NaN", "", "3 decimal"),
        ("received", "Infinity", "", "3 decimal"),
        ("received", "-inf", "", "3 decimal"),
        ("order", "1", "", "Choose received"),
        ("", "1", "", "Choose received"),
    ])
    def test_rules(self, tenant_a, reason, quantity, note, message):
        goat = counted(make_product(), "5")
        with schema_context("tenant_a"), pytest.raises(ValidationError, match=message):
            stock.adjust(goat, reason=reason, quantity=quantity, note=note)
        assert level(goat) == D("5")

    def test_only_counted_products(self, tenant_a):
        goat = make_product()
        with schema_context("tenant_a"), pytest.raises(ValidationError, match="Switch on “Count stock” first"):
            stock.adjust(goat, reason="received", quantity="1")

    def test_waste_can_go_below_zero_but_shows_it(self, tenant_a):
        goat = counted(make_product(min_quantity=D("0.5")), "1")
        with schema_context("tenant_a"):
            stock.adjust(goat, reason="waste", quantity="2", note="Freezer broke")
            goat.refresh_from_db()
            assert goat.stock_quantity == D("-1") and stock.state(goat) == "below_zero"

    def test_the_history_cannot_be_changed(self, tenant_a):
        goat = counted(make_product(), "3")
        with schema_context("tenant_a"):
            movement = StockMovement.objects.get(product=goat)
            movement.note = "changed"
            with pytest.raises(PermissionError):
                movement.save()
            with pytest.raises(PermissionError):
                movement.delete()
            with pytest.raises(PermissionError):
                StockMovement.objects.filter(pk=movement.pk).update(note="x")
            with pytest.raises(PermissionError):
                StockMovement.objects.filter(pk=movement.pk).delete()
            with pytest.raises(ProtectedError):
                Product.objects.filter(pk=goat.pk).delete()  # archive it instead
            assert StockMovement.objects.get(pk=movement.pk).note == "first delivery"


@pytest.mark.django_db
class TestState:
    def test_states_and_texts(self, tenant_a):
        p = make_product(min_quantity=D("0.5"))
        with schema_context("tenant_a"):
            assert stock.state(p) == "not_counted"
            p.track_stock = True
            for amount, warn, expected in [("-0.5", None, "below_zero"), ("0", None, "out"), ("0.4", None, "out"),
                                           ("0.5", None, "ok"), ("3", D("3"), "low"), ("3.001", D("3"), "ok"), ("0.5", D("3"), "low")]:
                p.stock_quantity, p.low_stock_level = D(amount), warn
                assert stock.state(p) == expected, (amount, warn)
        assert stock.STATE_TEXT["out"] == "Out of stock"

    def test_amount_text(self, tenant_a):
        goat, pack, each = make_product(), make_product(sku="P", unit="pack"), make_product(sku="E", unit="each")
        assert stock.amount_text(D("40.000"), goat) == "40 kg"
        assert stock.amount_text(D("2.500"), goat) == "2.5 kg"
        assert stock.amount_text(D("1.000"), pack) == "1 pack" and stock.amount_text(D("3"), pack) == "3 packs"
        assert stock.amount_text(D("10.000"), each) == "10"

    def test_low_stock_list(self, tenant_a):
        counted(make_product(name="Fine", sku="A"), "50", low_stock_level=D("5"))
        counted(make_product(name="Low", sku="B"), "5", low_stock_level=D("5"))
        counted(make_product(name="Out", sku="C", min_quantity=D("1")), "0.5")
        gone = counted(make_product(name="Archived", sku="D"), None, is_archived=True)
        make_product(name="Not counted", sku="E")
        below = counted(make_product(name="Below", sku="F"), "1")
        with schema_context("tenant_a"):
            stock.adjust(below, reason="waste", quantity="2", note="x")
            rows = stock.low_stock()
            assert [(r["name"], r["state"]) for r in rows] == [("Below", "below_zero"), ("Out", "out"), ("Low", "low")]
            assert rows[0]["stock"] == "-1" and rows[2] == {
                "product_id": rows[2]["product_id"], "name": "Low", "unit": "kg", "state": "low", "state_text": "Low", "stock": "5", "warn_at": "5"}
            assert rows[1]["warn_at"] is None and len(stock.low_stock(limit=2)) == 2
            assert gone.pk not in [r["product_id"] for r in rows]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOrders:
    def test_drafts_and_waiting_orders_hold_no_stock(self, goods):
        order = move(new_order(goods), S.AWAITING)
        assert (level(goods["goat"]), level(goods["samosa"])) == (D("10"), D("20"))
        assert not order.stock_taken

    def test_confirming_takes_the_ordered_amounts(self, goods):
        order = move(new_order(goods), S.CONFIRMED)  # 1.5 kg goat, 2 samosa packs
        assert (level(goods["goat"]), level(goods["samosa"])) == (D("8.5"), D("18"))
        assert order.stock_taken
        with schema_context("tenant_a"):
            m = StockMovement.objects.get(product=goods["goat"], reason="order")
            assert (m.change, m.quantity_after, m.order_number, m.order_id) == (D("-1.5"), D("8.5"), order.number, order.pk)
            assert m.note == f"Order #{order.number} confirmed"

    def test_two_lines_of_one_product_are_added_up(self, goods):
        move(new_order(goods, [L(goods["samosa"].pk, D("2")), L(goods["samosa"].pk, D("3"))]), S.CONFIRMED)
        assert level(goods["samosa"]) == D("15")
        assert reasons(goods["samosa"])[-1] == ("order", D("-5"))

    def test_products_not_counted_are_left_alone(self, goods):
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["samosa"].pk).update(track_stock=False)
        move(new_order(goods), S.CONFIRMED)
        assert level(goods["samosa"]) == D("20") and len(reasons(goods["samosa"])) == 1

    def test_real_weight_changes_the_difference(self, goods):
        order = move(new_order(goods), S.CONFIRMED, S.PREPARING)
        with schema_context("tenant_a"):
            line = order.lines.get(product=goods["goat"])
            services.set_weights(order, {line.pk: "1.62"})
            assert Product.objects.get(pk=goods["goat"].pk).stock_quantity == D("8.38")
            services.set_weights(Order.objects.get(pk=order.pk), {line.pk: "1.40"})  # weighed again
            assert Product.objects.get(pk=goods["goat"].pk).stock_quantity == D("8.6")
            services.set_weights(Order.objects.get(pk=order.pk), {line.pk: "1.40"})  # the same: no new movement
        assert reasons(goods["goat"])[-2:] == [("weight", D("-0.12")), ("weight", D("0.22"))]

    def test_cancelling_gives_back_what_was_taken(self, goods):
        order = move(new_order(goods), S.CONFIRMED, S.PREPARING)
        with schema_context("tenant_a"):
            line = order.lines.get(product=goods["goat"])
            order = services.set_weights(order, {line.pk: "1.6"})
        order = move(order, S.CANCELLED_SHOP, note="No driver")
        assert (level(goods["goat"]), level(goods["samosa"])) == (D("10"), D("20"))
        assert reasons(goods["goat"])[-1] == ("cancelled", D("1.6")) and not order.stock_taken

    def test_cancelling_an_order_that_held_no_stock(self, goods):
        move(new_order(goods), S.AWAITING, S.CANCELLED_CUSTOMER, note="Changed mind")
        assert level(goods["goat"]) == D("10") and len(reasons(goods["goat"])) == 1

    def test_orders_confirmed_before_stock_counting_give_nothing_back(self, goods):
        order = move(new_order(goods), S.CONFIRMED)
        with schema_context("tenant_a"):
            Order.objects.filter(pk=order.pk).update(stock_taken=False)  # like an order from before task 2.2
            order.refresh_from_db()
            order = services.set_weights(services.change_status(order, S.PREPARING),
                                         {order.lines.get(product=goods["goat"]).pk: "2"})
        move(order, S.CANCELLED_SHOP, note="Closed")
        assert level(goods["goat"]) == D("8.5")  # only the confirmation; no weight change, nothing back

    def test_an_order_that_already_holds_stock_is_not_charged_again(self, goods):
        order = new_order(goods)
        with schema_context("tenant_a"):
            Order.objects.filter(pk=order.pk).update(stock_taken=True)  # cannot happen today; guards a future "back to draft"
            order.refresh_from_db()
        move(order, S.CONFIRMED)
        assert level(goods["goat"]) == D("10") and len(reasons(goods["goat"])) == 1

    def test_customers_cannot_confirm_more_than_the_stock(self, shop, goods):
        order = move(new_order(goods, [L(goods["goat"].pk, D("10.5")), L(goods["samosa"].pk, D("2"))], due_at=at(tomorrow(), 10)), S.AWAITING)
        with pytest.raises(ValidationError, match=r"Only 10 kg of Goat curry cut in stock \(this order needs 10.5 kg\)"):
            move(order, S.CONFIRMED, strict=True)
        assert level(goods["goat"]) == D("10")
        exact = move(new_order(goods, [L(goods["goat"].pk, D("10"))], due_at=at(tomorrow(), 10)), S.AWAITING)
        assert move(exact, S.CONFIRMED, strict=True).status == S.CONFIRMED and level(goods["goat"]) == D("0")

    def test_staff_may_confirm_anyway_and_see_a_warning(self, goods):
        order = new_order(goods, [L(goods["goat"].pk, D("12"))])
        with schema_context("tenant_a"):
            assert services.warnings(order) == ["Only 10 kg of Goat curry cut in stock (this order needs 12 kg)."]
        order = move(order, S.CONFIRMED)
        assert level(goods["goat"]) == D("-2")
        with schema_context("tenant_a"):
            assert services.warnings(order) == []  # taken already; the product page says "Below zero: count again"
            assert stock.state(Product.objects.get(pk=goods["goat"].pk)) == "below_zero"

    def test_a_confirmed_order_can_change_its_time_with_little_stock_left(self, shop, goods):
        order = move(new_order(goods, [L(goods["goat"].pk, D("10"))], due_at=at(tomorrow(), 10)), S.AWAITING)
        order = move(order, S.CONFIRMED, strict=True)
        assert level(goods["goat"]) == D("0")
        with schema_context("tenant_a"):
            assert services.booking_problems(order, strict=True) == []  # its own 10 kg are not counted twice
            services.update_order(order, due_at=at(tomorrow(), 11), strict=True)


@pytest.mark.django_db
class TestDeliveryBack:
    def test_back_to_ready_and_out_again_takes_nothing_more(self, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, D("3"))]), S.CONFIRMED, S.PREPARING, S.READY, S.OUT_FOR_DELIVERY)
        order = move(order, S.READY, note="Nobody home")
        move(order, S.OUT_FOR_DELIVERY, S.COMPLETED)
        assert reasons(goods["samosa"]) == [("received", D("20")), ("order", D("-3"))] and level(goods["samosa"]) == D("17")


# ---------------------------------------------------------------------------
# API (the staff app)
# ---------------------------------------------------------------------------
@pytest.fixture
def manager(client_for, tenant_a):
    return user_client(client_for, tenant_a, "stock@a.test", "inventory_manager")  # Products - Edit


@pytest.fixture
def rep(client_for, tenant_a):
    return user_client(client_for, tenant_a, "rep@a.test", "sales_rep")  # Products - View only


@pytest.mark.django_db
class TestApi:
    def test_product_shows_its_stock(self, manager, tenant_a):
        goat = counted(make_product(), "4", low_stock_level=D("5"))
        body = manager.get(f"/api/products/{goat.pk}/").json()
        assert (body["track_stock"], body["stock_quantity"], body["low_stock_level"], body["stock_state"], body["stock_text"]) == (
            True, "4.000", "5.000", "low", "Low")

    def test_stock_cannot_be_typed_into_the_product(self, manager, tenant_a):
        goat = counted(make_product(), "4")
        response = manager.patch(f"/api/products/{goat.pk}/", {"stock_quantity": "99", "low_stock_level": "2"}, content_type="application/json")
        assert response.status_code == 200 and response.json()["low_stock_level"] == "2.000"
        assert level(goat) == D("4")

    def test_adjust_and_history(self, manager, tenant_a):
        goat = counted(make_product(), "4")
        response = manager.post(f"/api/products/{goat.pk}/stock/", {"reason": "waste", "quantity": "1", "note": "Out of date"},
                                content_type="application/json")
        assert response.status_code == 200 and response.json()["stock_quantity"] == "3.000"
        history = manager.get(f"/api/products/{goat.pk}/stock/").json()
        assert [(h["reason"], h["reason_label"], h["change"], h["quantity_after"]) for h in history] == [
            ("waste", "Waste", "-1.000", "3.000"), ("received", "Received", "4.000", "4.000")]
        assert history[0]["actor_email"] == "stock@a.test" and history[0]["note"] == "Out of date"

    def test_mistakes_come_back_in_words(self, manager, tenant_a):
        goat = counted(make_product(), "4")
        response = manager.post(f"/api/products/{goat.pk}/stock/", {"reason": "waste", "quantity": "1"}, content_type="application/json")
        assert response.status_code == 400 and "short note" in response.json()["detail"]
        assert manager.post("/api/products/99999/stock/", {"reason": "received", "quantity": "1"}, content_type="application/json").status_code == 404

    def test_view_permission_sees_but_cannot_change(self, rep, tenant_a):
        goat = counted(make_product(), "4")
        assert rep.get(f"/api/products/{goat.pk}/stock/").status_code == 200
        assert rep.post(f"/api/products/{goat.pk}/stock/", {"reason": "received", "quantity": "1"}, content_type="application/json").status_code == 403
        assert level(goat) == D("4")

    def test_no_products_permission_sees_nothing(self, client_for, tenant_a):
        goat = counted(make_product(), "4")
        hr = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        assert hr.get(f"/api/products/{goat.pk}/stock/").status_code == 403

    def test_low_filter(self, manager, tenant_a):
        counted(make_product(name="Fine", sku="A"), "50", low_stock_level=D("5"))
        counted(make_product(name="Low", sku="B"), "5", low_stock_level=D("5"))
        counted(make_product(name="Out", sku="C", min_quantity=D("1")), "0.5")
        make_product(name="Not counted", sku="D")
        names = [p["name"] for p in manager.get("/api/products/?stock=low").json()["results"]]
        assert sorted(names) == ["Low", "Out"]
        assert len(manager.get("/api/products/").json()["results"]) == 4

    def test_other_businesses_cannot_be_reached(self, client_for, tenant_a, tenant_b):
        other = counted(make_product(), "4")
        outsider = user_client(client_for, tenant_b, "stock@b.test", "inventory_manager")
        assert outsider.post(f"/api/products/{other.pk}/stock/", {"reason": "received", "quantity": "1"},
                             content_type="application/json").status_code == 404
        assert level(other) == D("4")


# ---------------------------------------------------------------------------
# Classic admin page
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminPage:
    def test_manager_adjusts_stock(self, client_for, tenant_a):
        goat = counted(make_product(), "40")
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        assert "Adjust stock" in client.get(f"/admin/catalog/product/{goat.pk}/change/").content.decode()
        page = client.get(f"/admin/catalog/product/{goat.pk}/stock/").content.decode()
        assert "In stock: <strong>40 kg</strong> (In stock)" in page and "+40" in page and "4E+1" not in page
        response = client.post(f"/admin/catalog/product/{goat.pk}/stock/", {"reason": "counted", "quantity": "37.5", "note": ""})
        assert response.status_code == 302
        page = client.get(response["Location"]).content.decode()
        assert "Saved. Goat curry cut: 37.5 kg in stock." in page and "-2.5" in page and "37.5" in page
        bad = client.post(f"/admin/catalog/product/{goat.pk}/stock/", {"reason": "waste", "quantity": "1", "note": ""}).content.decode()
        assert "short note" in bad and level(goat) == D("37.5")

    def test_list_column_and_filter(self, client_for, tenant_a):
        counted(make_product(name="Lamb chops", sku="L"), "2", low_stock_level=D("3"))
        make_product(name="Pork belly", sku="P")
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        page = client.get("/admin/catalog/product/").content.decode()
        assert "2 kg (Low)" in page
        low = client.get("/admin/catalog/product/?stock=low").content.decode()
        assert "Lamb chops" in low and "Pork belly" not in low

    def test_view_only_staff_see_the_history_without_the_form(self, client_for, tenant_a):
        goat = counted(make_product(), "4")
        client = verified_staff_client(client_for, tenant_a, "ops@a.test", "operations_manager")  # Products - View
        page = client.get(f"/admin/catalog/product/{goat.pk}/stock/").content.decode()
        assert "Stock history" in page and 'name="quantity"' not in page
        assert client.post(f"/admin/catalog/product/{goat.pk}/stock/", {"reason": "received", "quantity": "1"}).status_code == 403
        assert level(goat) == D("4")

    def test_not_counted_product(self, client_for, tenant_a):
        goat = make_product()
        client = verified_staff_client(client_for, tenant_a, "stock@a.test", "inventory_manager")
        page = client.get(f"/admin/catalog/product/{goat.pk}/stock/").content.decode()
        assert "Stock is not counted" in page and 'name="quantity"' not in page

    def test_other_products_permissions_are_not_enough(self, client_for, tenant_a):
        from apps.rbac.models import Role

        goat = counted(make_product(), "4")
        with schema_context("tenant_a"):
            Role.objects.create(slug="exporter", name="Exporter").set_permissions({"products.export"})
        client = verified_staff_client(client_for, tenant_a, "exp@a.test", "exporter")
        assert client.get(f"/admin/catalog/product/{goat.pk}/stock/").status_code == 403
        with schema_context("tenant_a"):
            assert AuditEvent.objects.filter(action="permission.denied", metadata__permission="products.view").exists()

    def test_staff_without_products_permission(self, client_for, tenant_a):
        goat = make_product()
        client = verified_staff_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        assert client.get(f"/admin/catalog/product/{goat.pk}/stock/").status_code == 403


# ---------------------------------------------------------------------------
# CSV and dashboard
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCsv:
    def test_import_sets_counting_and_stock(self, tenant_a):
        rows = [["sku", "name", "price", "unit", "count_stock", "warn_at", "stock"],
                ["G1", "Goat", "23", "kg", "yes", "5", "12.5"], ["S1", "Samosa", "15", "pack", "no", "", ""]]
        with schema_context("tenant_a"):
            result = catalog_services.import_products(csv_file(rows))
            assert result.ok and result.created == 2
            goat = Product.objects.get(sku="G1")
            assert (goat.track_stock, goat.low_stock_level, goat.stock_quantity) == (True, D("5"), D("12.5"))
            assert StockMovement.objects.get(product=goat).reason == "counted"
            assert not Product.objects.get(sku="S1").track_stock
            again = catalog_services.import_products(csv_file(rows))  # same stock: no new movement
            assert again.ok and StockMovement.objects.filter(product=goat).count() == 1

    @pytest.mark.parametrize("row,message", [
        (["G1", "Goat", "23", "kg", "no", "", "4"], "stock needs count_stock = yes"),
        (["G1", "Goat", "23", "kg", "yes", "-1", ""], "warn_at cannot be below 0"),
        (["G1", "Goat", "23", "kg", "yes", "", "-2"], "stock must be 0 or more"),
        (["G1", "Goat", "23", "kg", "yes", "", "1.0001"], "stock must be 0 or more"),
    ])
    def test_import_mistakes(self, tenant_a, row, message):
        with schema_context("tenant_a"):
            result = catalog_services.import_products(csv_file([["sku", "name", "price", "unit", "count_stock", "warn_at", "stock"], row]))
            assert not result.ok and message in result.errors[0]["error"]
            assert not Product.objects.exists() and not StockMovement.objects.exists()

    def test_export_columns(self, tenant_a):
        counted(make_product(sku="G1"), "40", low_stock_level=D("8"))
        make_product(sku="S1", name="Samosa", unit="pack")
        with schema_context("tenant_a"):
            rows = {r[0]: r[-3:] for r in catalog_services.export_rows(Product.objects.all(), include_cost=True)}
        assert rows == {"G1": ["yes", "8", "40"], "S1": ["no", "", ""]}
        assert catalog_services.CSV_COLUMNS[-3:] == ["count_stock", "warn_at", "stock"]


@pytest.mark.django_db
class TestDashboard:
    def test_low_stock_card(self, client_for, tenant_a):
        counted(make_product(name="Lamb chops", sku="L"), "2", low_stock_level=D("3"))
        counted(make_product(name="Goat", sku="G"), "20", low_stock_level=D("3"))
        with schema_context("tenant_a"):
            assert [r["name"] for r in dashboard.summary()["low_stock"]] == ["Lamb chops"]
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        body = owner.get("/api/reports/dashboard/").json()
        assert body["low_stock"][0]["state_text"] == "Low" and body["low_stock"][0]["stock"] == "2"
