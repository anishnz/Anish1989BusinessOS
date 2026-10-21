"""
Pickup and delivery (task 2.1): time slots from opening hours, closed days,
slot capacity, delivery areas and fees, the "Out for delivery" status, the
rules for customers and staff (D-120 to D-124), the API, the admin pages and
the new Orders – Configure permission.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.fulfilment import services as fulfilment
from apps.fulfilment.models import ClosedDay, DeliveryArea, FulfilmentSettings, OpeningHours
from apps.orders import services
from apps.orders.models import Order
from apps.rbac.models import Role, RolePermission
from tests.test_catalog import user_client
from tests.test_orders import L, goods, move, new_order  # noqa: F401 - fixture
from tests.test_rbac import verified_staff_client

S = Order.Status


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute)).replace(tzinfo=timezone.get_current_timezone())


def tomorrow() -> date:
    return timezone.localdate() + timedelta(days=1)


@pytest.fixture
def shop(tenant_a):
    """Pickup 9:00-12:00 in 30-minute slots (2 orders each), delivery 16:00-18:00 in 1-hour windows (1 each), every day."""
    with schema_context("tenant_a"):
        s = fulfilment.current_settings()
        s.pickup_capacity, s.delivery_enabled, s.delivery_capacity, s.lead_minutes = 2, True, 1, 60
        s.save()
        for weekday in range(7):
            OpeningHours.objects.create(settings=s, kind="pickup", weekday=weekday, opens=time(9), closes=time(12))
            OpeningHours.objects.create(settings=s, kind="delivery", weekday=weekday, opens=time(16), closes=time(18))
        central = DeliveryArea.objects.create(name="Central", postcodes="1010, 1011", suburbs="Mount Eden, CBD", fee=Decimal("8.00"),
                                              minimum_order=Decimal("30"), free_over=Decimal("100"))
        far = DeliveryArea.objects.create(name="Far away", postcodes="2010", fee=Decimal("15.00"), is_active=False)
    return {"settings": s, "central": central, "far": far}


def delivery(goods, **kw):
    details = {"fulfilment": "delivery", "delivery_address": "1 Queen Street", "delivery_postcode": "1010", "due_at": at(tomorrow(), 16)}
    details.update(kw)
    return new_order(goods, **details)


# ---------------------------------------------------------------------------
# Slots
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSlots:
    def test_slots_come_from_the_opening_hours(self, shop):
        with schema_context("tenant_a"):
            found = fulfilment.slots("pickup", tomorrow())
            assert [s.start for s in found] == [at(tomorrow(), h, m) for h in (9, 10, 11) for m in (0, 30)]
            assert found[0].end == at(tomorrow(), 9, 30) and found[0].capacity == 2 and not found[0].full
            assert found[0].label.endswith("09:00–09:30")
            assert len(fulfilment.slots("delivery", tomorrow())) == 2

    def test_two_periods_and_closed_days(self, shop):
        day = tomorrow()
        with schema_context("tenant_a"):
            OpeningHours.objects.create(settings=shop["settings"], kind="pickup", weekday=day.weekday(), opens=time(13), closes=time(14))
            assert len(fulfilment.slots("pickup", day)) == 8
            ClosedDay.objects.create(date=day, reason="Diwali")
            assert fulfilment.slots("pickup", day) == [] and len(fulfilment.slots("pickup", day, 2)) == 6
            assert any("Closed on" in p and "(Diwali)" in p for p in fulfilment.time_problems("pickup", at(day, 9)))

    def test_only_booked_orders_take_a_place(self, shop, goods):
        slot = at(tomorrow(), 9)
        new_order(goods, due_at=slot)  # a draft
        move(new_order(goods, due_at=slot), S.CONFIRMED)
        move(new_order(goods, due_at=at(tomorrow(), 9, 10)), S.CONFIRMED)  # inside the same slot
        cancelled = move(new_order(goods, due_at=slot), S.CONFIRMED)
        move(cancelled, S.CANCELLED_SHOP, note="Out of goat")
        move(delivery(goods, due_at=slot), S.CONFIRMED)  # a delivery does not use a pickup place
        with schema_context("tenant_a"):
            first = fulfilment.slots("pickup", tomorrow())[0]
            assert first.taken == 2 and first.full
            assert fulfilment.slots("pickup", tomorrow())[1].taken == 0

    def test_what_customers_can_choose(self, shop, goods):
        now = at(tomorrow(), 8, 50)  # 10 minutes before opening
        move(new_order(goods, due_at=at(tomorrow(), 10)), S.CONFIRMED)
        move(new_order(goods, due_at=at(tomorrow(), 10)), S.CONFIRMED)  # 10:00 is now full
        with schema_context("tenant_a"):
            starts = [s.start for s in fulfilment.bookable_slots("pickup", now=now)][:4]
            assert starts == [at(tomorrow(), 10, 30), at(tomorrow(), 11), at(tomorrow(), 11, 30), at(tomorrow() + timedelta(days=1), 9)]
            assert at(tomorrow(), 10) in [s.start for s in fulfilment.bookable_slots("pickup", now=now, include_full=True)]
            days = {timezone.localtime(s.start).date() for s in fulfilment.bookable_slots("pickup", now=now)}
            assert max(days) == tomorrow() + timedelta(days=6)  # 7 days ahead, counted from "today" (tomorrow here)
            shop["settings"].pickup_enabled = False
            shop["settings"].save()
            assert fulfilment.bookable_slots("pickup", now=now) == []

    def test_clocks_going_forward(self, shop):
        day = date(2026, 9, 27)  # New Zealand daylight saving started at 2:00 that Sunday
        with schema_context("tenant_a"):
            OpeningHours.objects.create(settings=shop["settings"], kind="delivery", weekday=day.weekday(), opens=time(1), closes=time(4))
            found = [s for s in fulfilment.slots("delivery", day) if s.start.hour < 12]
            assert [(s.start.hour, s.end.hour) for s in found] == [(3, 4)]  # 1-2 and 2-3 do not exist that night

    def test_no_limit(self, shop, goods):
        with schema_context("tenant_a"):
            FulfilmentSettings.objects.update(pickup_capacity=0)
        for _ in range(3):
            move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        with schema_context("tenant_a"):
            assert not fulfilment.slots("pickup", tomorrow())[0].full


@pytest.mark.django_db
class TestTimeRules:
    def problems(self, when, kind="pickup", **kw):
        with schema_context("tenant_a"):
            return " ".join(fulfilment.time_problems(kind, when, **kw))

    def test_good_time(self, shop):
        assert self.problems(at(tomorrow(), 9, 30)) == ""

    def test_outside_hours_past_too_soon_too_far(self, shop):
        assert "outside the pickup hours" in self.problems(at(tomorrow(), 13))
        assert "outside the delivery hours" in self.problems(at(tomorrow(), 9), kind="delivery")
        assert "in the past" in self.problems(at(tomorrow(), 9), now=at(tomorrow(), 10))
        assert "too soon" in self.problems(at(tomorrow(), 9), now=at(tomorrow(), 8, 30))
        today = timezone.localdate()
        assert "too far ahead" in self.problems(at(today + timedelta(days=7), 9))  # 7 days ahead = today to today + 6
        assert "too far ahead" not in self.problems(at(today + timedelta(days=6), 9))

    def test_exact_and_full(self, shop, goods):
        assert "Choose one of the pickup times (for example 09:00)" in self.problems(at(tomorrow(), 9, 10), exact=True)
        assert self.problems(at(tomorrow(), 9, 10)) == ""
        order = move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        assert "slot is full (2 of 2 orders)" in self.problems(at(tomorrow(), 9))
        assert self.problems(at(tomorrow(), 9), exclude_order_id=order.pk) == ""  # the order itself does not count


# ---------------------------------------------------------------------------
# Delivery areas
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAreas:
    def test_find_by_postcode_suburb_or_address(self, shop):
        with schema_context("tenant_a"):
            assert fulfilment.find_area(postcode="1011") == shop["central"]
            assert fulfilment.find_area(suburb="  mt   eden ") == shop["central"]
            assert fulfilment.find_area(address="Flat 2, 5 Queen St, Auckland 1010") == shop["central"]
            assert fulfilment.find_area(postcode="2010") is None  # area switched off
            assert fulfilment.find_area(postcode="9999", suburb="Nowhere") is None
            assert fulfilment.find_area(address="12345 Long Road") is None  # not a 4-digit postcode

    def test_fee_and_free_delivery(self, shop):
        area = shop["central"]
        assert fulfilment.delivery_fee(area, Decimal("99.99")) == Decimal("8.00")
        assert fulfilment.delivery_fee(area, Decimal("100")) == Decimal("0.00")

    @pytest.mark.parametrize("postcodes,suburbs,message", [
        ("101", "", "Postcodes have 4 digits"), ("1010", "", "1010 is already in the area “Central”"),
        ("", "Mt Eden", "Mount Eden is already in the area “Central”"), ("", "", "at least one postcode or suburb"),
    ])
    def test_area_checks(self, shop, postcodes, suburbs, message):
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError) as exc:
                DeliveryArea(name="New", postcodes=postcodes, suburbs=suburbs, fee=Decimal("5")).full_clean()
            assert message in " ".join(exc.value.messages)
            DeliveryArea(name="Old", postcodes="1010", fee=Decimal("5"), is_active=False).full_clean()  # switched off: no clash


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryOrders:
    def test_area_fee_and_gst_from_the_postcode(self, shop, goods):
        order = delivery(goods)
        with schema_context("tenant_a"):
            assert order.delivery_area == shop["central"] and order.delivery_fee == Decimal("8.00")
            assert order.estimated_total == order.total == Decimal("72.50")  # 64.50 products + 8.00
            assert order.gst_total == Decimal("9.45")  # 8.41 + 1.04 in the fee
            assert order.due_until == at(tomorrow(), 17) and services.due_text(order).endswith("16:00–17:00")
            assert "Delivery to Central (fee $8.00)" in order.events.get().note

    def test_no_gst_in_the_fee_when_switched_off(self, shop, goods):
        with schema_context("tenant_a"):
            FulfilmentSettings.objects.update(delivery_fee_gst=False)
        assert delivery(goods).gst_total == Decimal("8.41")

    def test_free_delivery_and_a_typed_time(self, shop, goods):
        order = delivery(goods, lines=[L(goods["samosa"].pk, Decimal("7"))], due_at=at(tomorrow(), 16, 20))
        assert order.delivery_fee == Decimal("0.00") and order.total == Decimal("105.00")
        assert order.due_until is None and services.due_text(order).endswith("16:20")

    def test_pickup_keeps_no_address(self, shop, goods):
        order = new_order(goods, fulfilment="pickup", delivery_address="1 Queen Street", delivery_postcode="1010", due_at=at(tomorrow(), 9))
        assert (order.delivery_address, order.delivery_postcode, order.delivery_area, order.delivery_fee) == ("", "", None, Decimal("0"))
        assert order.due_until == at(tomorrow(), 9, 30)

    def test_bad_postcode(self, shop, goods):
        with pytest.raises(ValidationError, match="4 digits"):
            delivery(goods, delivery_postcode="10A0")

    def test_a_delivery_needs_address_area_and_time(self, shop, goods):
        order = new_order(goods, fulfilment="delivery", delivery_postcode="9999")
        with pytest.raises(ValidationError) as exc:
            move(order, S.CONFIRMED)
        text = " ".join(exc.value.messages)
        assert "Add the delivery address" in text and "Choose the delivery area" in text and "Choose a delivery time" in text
        with pytest.raises(ValidationError):
            move(order, S.AWAITING)

    def test_staff_may_book_outside_the_rules_with_warnings(self, shop, goods):
        move(delivery(goods), S.CONFIRMED)  # 16:00 now full (1 per window)
        order = delivery(goods, lines=[L(goods["samosa"].pk, Decimal("1"))])  # $15: below the $30 minimum
        with schema_context("tenant_a"):
            text = " ".join(services.warnings(order))
            assert "slot is full (1 of 1 orders)" in text and "minimum order for delivery to “Central” is $30.00" in text
        order = move(order, S.CONFIRMED)
        assert order.status == S.CONFIRMED

    def test_exactly_the_minimum_is_enough(self, shop, goods):
        order = delivery(goods, lines=[L(goods["samosa"].pk, Decimal("2"))])  # $30.00 of products, the minimum
        with schema_context("tenant_a"):
            assert not any("minimum order" in w for w in services.warnings(order))
        assert move(order, S.CONFIRMED, strict=True).status == S.CONFIRMED

    def test_customers_must_follow_the_rules(self, shop, goods):
        move(delivery(goods), S.CONFIRMED)
        full = delivery(goods)
        with pytest.raises(ValidationError, match="is full"):
            move(full, S.CONFIRMED, strict=True)
        small = delivery(goods, lines=[L(goods["samosa"].pk, Decimal("1"))], due_at=at(tomorrow(), 17))
        with pytest.raises(ValidationError, match="minimum order"):
            move(small, S.CONFIRMED, strict=True)
        odd = new_order(goods, due_at=at(tomorrow(), 9, 10))
        with pytest.raises(ValidationError, match="Choose one of the pickup times"):
            move(odd, S.CONFIRMED, strict=True)
        no_time = new_order(goods)
        with pytest.raises(ValidationError, match="Choose a pickup time"):
            move(no_time, S.CONFIRMED, strict=True)
        with schema_context("tenant_a"):
            FulfilmentSettings.objects.update(pickup_enabled=False)
        with pytest.raises(ValidationError, match="Pickup is switched off"):
            move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED, strict=True)
        assert move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED).status == S.CONFIRMED  # staff still can

    def test_fee_stays_when_the_area_changes_later(self, shop, goods):
        order = move(delivery(goods), S.CONFIRMED, S.PREPARING)
        with schema_context("tenant_a"):
            DeliveryArea.objects.filter(pk=shop["central"].pk).update(fee=Decimal("20"))
            FulfilmentSettings.objects.update(delivery_fee_gst=False)
            line = order.lines.get(product=goods["goat"])
            order = services.set_weights(order, {line.pk: "1.6"})
        assert order.delivery_fee == Decimal("8.00") and order.total == Decimal("74.80")  # 36.80 + 30 + 8
        assert order.gst_total == Decimal("9.75")  # 4.80 + 3.91 + 1.04 (the fee kept its GST)


@pytest.mark.django_db
class TestChangingOrders:
    def test_switch_to_delivery_while_awaiting_goes_back_to_draft(self, shop, goods):
        order = move(new_order(goods, due_at=at(tomorrow(), 9)), S.AWAITING)
        with schema_context("tenant_a"):
            order = services.update_order(order, fulfilment="delivery", delivery_address="2 High St", delivery_suburb="CBD", due_at=at(tomorrow(), 17))
            assert order.status == S.DRAFT and order.delivery_area == shop["central"] and order.total == Decimal("72.50")
            assert order.events.filter(note__startswith="Changed to: Delivery to Central").exists()

    def test_changing_the_time_of_a_confirmed_order(self, shop, goods):
        order = move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        with schema_context("tenant_a"):
            order = services.update_order(order, due_at=at(tomorrow(), 11))
            assert order.status == S.CONFIRMED and order.due_until == at(tomorrow(), 11, 30)
            unchanged = order.events.count()
            services.update_order(order, due_at=at(tomorrow(), 11))  # same time: nothing new in the history
            assert order.events.count() == unchanged

    def test_a_confirmed_delivery_keeps_its_address(self, shop, goods):
        order = move(delivery(goods), S.CONFIRMED)
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="Choose the delivery area"):
                services.update_order(order, delivery_postcode="9999", delivery_suburb="", delivery_address="9 Far Road")
            order.refresh_from_db()
            assert order.delivery_postcode == "1010" and order.delivery_area == shop["central"]
            order = services.update_order(order, delivery_address="3 Queen Street", delivery_postcode="1011")
            assert order.delivery_area == shop["central"] and order.delivery_fee == Decimal("8.00")

    def test_a_paid_order_keeps_its_fee(self, shop, goods):
        order = move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        with schema_context("tenant_a"):
            order = services.set_paid(order, True, method="cash")
            with pytest.raises(ValidationError, match="This order is paid"):
                services.update_order(order, fulfilment="delivery", delivery_address="1 Queen St", delivery_postcode="1010", due_at=at(tomorrow(), 17))
            order.refresh_from_db()
            assert order.fulfilment == "pickup" and order.delivery_fee == 0
            services.update_order(order, due_at=at(tomorrow(), 10))  # the time can still change

    def test_free_delivery_area_on_a_paid_order_is_fine(self, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, Decimal("7"))]), S.CONFIRMED)
        with schema_context("tenant_a"):
            other = DeliveryArea.objects.create(name="North", postcodes="0600", fee=Decimal("12"), free_over=Decimal("50"))
            order = services.set_paid(order, True, method="card")
            order = services.update_order(order, delivery_area=other, delivery_address="4 North Rd")
            assert order.delivery_area == other and order.delivery_fee == Decimal("0.00")

    def test_out_for_delivery_cannot_change(self, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, Decimal("2"))]), S.CONFIRMED, S.PREPARING, S.READY, S.OUT_FOR_DELIVERY)
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="out for delivery"):
                services.update_order(order, due_at=at(tomorrow(), 17))
            services.update_order(order, notes="Leave at the door")  # other details still can


@pytest.mark.django_db
class TestDeliveryStatus:
    def test_pickup_is_completed_from_ready(self, shop, goods):
        order = move(new_order(goods, lines=[L(goods["samosa"].pk, Decimal("2"))]), S.CONFIRMED, S.PREPARING, S.READY)
        assert order.status_text == "Ready for pickup" and S.OUT_FOR_DELIVERY not in services.allowed_moves(order)
        with pytest.raises(ValidationError, match="cannot go from 'Ready for pickup' to 'Out for delivery'"):
            move(order, S.OUT_FOR_DELIVERY)
        assert move(order, S.COMPLETED).status == S.COMPLETED

    def test_delivery_goes_out_first(self, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, Decimal("2"))]), S.CONFIRMED, S.PREPARING, S.READY)
        assert order.status_text == "Ready for delivery" and S.COMPLETED not in services.allowed_moves(order)
        with pytest.raises(ValidationError, match="'Ready for delivery' to 'Completed'"):
            move(order, S.COMPLETED)
        order = move(order, S.OUT_FOR_DELIVERY)
        with pytest.raises(ValidationError, match="reason the delivery did not happen"):
            move(order, S.READY)
        order = move(order, S.READY, note="Nobody home")
        assert move(order, S.OUT_FOR_DELIVERY, S.COMPLETED).status == S.COMPLETED

    def test_final_price_message_names_the_right_ready(self, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, Decimal("2"))]), S.CONFIRMED, S.PREPARING)
        with pytest.raises(ValidationError, match="straight to 'Ready for delivery'"):
            move(order, S.FINAL_SENT)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestApi:
    def test_slots_for_staff(self, client_for, tenant_a, shop, goods):
        order = move(new_order(goods, due_at=at(tomorrow(), 9)), S.CONFIRMED)
        client = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = client.get(f"/api/orders/slots/?kind=pickup&date={tomorrow().isoformat()}").json()
        assert data["enabled"] and not data["closed"] and len(data["slots"]) == 6
        first = data["slots"][0]
        assert first["taken"] == 1 and first["capacity"] == 2 and not first["full"] and not first["past"]
        mine = client.get(f"/api/orders/slots/?kind=pickup&date={tomorrow().isoformat()}&order={order.pk}").json()
        assert mine["slots"][0]["taken"] == 0
        assert client.get("/api/orders/slots/?kind=boat").status_code == 400
        assert client.get("/api/orders/slots/?date=21-10-2026").status_code == 400
        past = client.get(f"/api/orders/slots/?kind=pickup&date={(timezone.localdate() - timedelta(days=1)).isoformat()}").json()
        assert all(s["past"] for s in past["slots"])

    def test_settings_and_areas(self, client_for, tenant_a, shop):
        client = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = client.get("/api/orders/fulfilment/").json()
        assert data["delivery_enabled"] and [a["name"] for a in data["areas"]] == ["Central"]
        assert data["areas"][0]["postcodes"] == ["1010", "1011"] and data["areas"][0]["free_over"] == "100.00"
        found = client.get("/api/orders/delivery-areas/find/", {"suburb": "CBD"}).json()
        assert found["area"]["name"] == "Central"
        assert client.get("/api/orders/delivery-areas/find/", {"postcode": "2010"}).json() == {"area": None}

    def test_create_and_change_a_delivery_order(self, client_for, tenant_a, shop, goods):
        client = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        response = client.post("/api/orders/", {
            "customer": goods["customer"].pk, "fulfilment": "delivery", "delivery_address": "1 Queen Street", "delivery_suburb": "CBD",
            "due_at": at(tomorrow(), 16).isoformat(), "delivery_fee": "0.01",  # a fee in the request is ignored
            "lines": [{"product": goods["samosa"].pk, "quantity": "1"}],
        }, content_type="application/json")
        assert response.status_code == 201, response.content
        data = response.json()
        assert data["delivery_area_name"] == "Central" and data["delivery_fee"] == "8.00" and data["total"] == "23.00"
        assert any("minimum order" in w for w in data["warnings"]) and data["due_text"].endswith("16:00–17:00")
        patched = client.patch(f"/api/orders/{data['id']}/", {"fulfilment": "pickup", "due_at": at(tomorrow(), 10).isoformat()},
                               content_type="application/json").json()
        assert patched["fulfilment"] == "pickup" and patched["delivery_fee"] == "0.00" and patched["delivery_address"] == "" and patched["warnings"] == []
        moved = client.post(f"/api/orders/{data['id']}/status/", {"to": "confirmed"}, content_type="application/json").json()
        assert moved["status"] == "confirmed" and moved["warnings"] == []

    def test_status_label_and_moves(self, client_for, tenant_a, shop, goods):
        order = move(delivery(goods, lines=[L(goods["samosa"].pk, Decimal("2"))]), S.CONFIRMED, S.PREPARING, S.READY)
        client = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = client.get(f"/api/orders/{order.pk}/").json()
        assert data["status_label"] == "Ready for delivery" and "out_for_delivery" in data["next_statuses"] and "completed" not in data["next_statuses"]
        back = client.post(f"/api/orders/{order.pk}/status/", {"to": "out_for_delivery"}, content_type="application/json").json()
        assert back["status_label"] == "Out for delivery"
        refused = client.post(f"/api/orders/{order.pk}/status/", {"to": "ready"}, content_type="application/json")
        assert refused.status_code == 400 and "reason" in refused.json()["detail"]

    def test_needs_orders_permission(self, client_for, tenant_a, shop):
        client = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        for path in ("/api/orders/fulfilment/", "/api/orders/slots/", "/api/orders/delivery-areas/find/?postcode=1010"):
            assert client.get(path).status_code == 403, path

    def test_other_business_cannot_see_the_areas(self, client_for, tenant_a, tenant_b, shop):
        client = user_client(client_for, tenant_b, "counter@b.test", "shop_staff")
        assert client.get("/api/orders/fulfilment/").json()["areas"] == []
        assert client.get("/api/orders/delivery-areas/find/?postcode=1010").json() == {"area": None}


# ---------------------------------------------------------------------------
# Admin and permission
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdmin:
    def test_settings_page(self, client_for, tenant_a, shop):
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        list_page = owner.get("/admin/fulfilment/fulfilmentsettings/")
        url = f"/admin/fulfilment/fulfilmentsettings/{shop['settings'].pk}/change/"
        assert list_page.status_code == 302 and list_page["Location"] == url
        page = owner.get(url).content.decode()
        assert "Times customers can choose now" in page and "Pickup</strong>: " in page and 'name="_save"' in page

    def test_shop_staff_can_look_but_not_change(self, client_for, tenant_a, shop):
        staff = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        url = f"/admin/fulfilment/fulfilmentsettings/{shop['settings'].pk}/change/"
        page = staff.get(url)
        assert page.status_code == 200 and 'name="_save"' not in page.content.decode()
        assert staff.post(url, {"pickup_capacity": "99"}).status_code == 403
        assert staff.get("/admin/fulfilment/deliveryarea/add/").status_code == 403
        assert staff.get(f"/admin/fulfilment/deliveryarea/{shop['central'].pk}/change/").status_code == 200

    def test_overlapping_hours_are_refused(self, client_for, tenant_a, shop):
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        with schema_context("tenant_a"):
            OpeningHours.objects.all().delete()
        data = {"pickup_enabled": "on", "pickup_slot_minutes": "30", "pickup_capacity": "5", "delivery_slot_minutes": "60",
                "delivery_capacity": "3", "lead_minutes": "60", "days_ahead": "7", "delivery_fee_gst": "on",
                "hours-TOTAL_FORMS": "2", "hours-INITIAL_FORMS": "0", "hours-MIN_NUM_FORMS": "0", "hours-MAX_NUM_FORMS": "1000",
                "hours-0-kind": "pickup", "hours-0-weekday": "0", "hours-0-opens": "09:00", "hours-0-closes": "12:00",
                "hours-1-kind": "pickup", "hours-1-weekday": "0", "hours-1-opens": "11:00", "hours-1-closes": "14:00"}
        url = f"/admin/fulfilment/fulfilmentsettings/{shop['settings'].pk}/change/"
        assert "two periods overlap" in owner.post(url, data).content.decode()
        data["hours-1-opens"] = "13:00"
        assert owner.post(url, data).status_code == 302
        with schema_context("tenant_a"):
            assert OpeningHours.objects.count() == 2

    def test_area_admin(self, client_for, tenant_a, shop, goods):
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        data = {"name": "Next door", "postcodes": "1010,1024", "suburbs": "", "fee": "5", "minimum_order": "0", "free_over": "", "is_active": "on", "sort_order": "0"}
        assert "1010 is already in the area" in owner.post("/admin/fulfilment/deliveryarea/add/", data).content.decode()
        data["postcodes"] = "1024 ,  1025"
        assert owner.post("/admin/fulfilment/deliveryarea/add/", data).status_code == 302
        with schema_context("tenant_a"):
            assert DeliveryArea.objects.get(name="Next door").postcodes == "1024, 1025"
        delivery(goods)
        assert owner.get(f"/admin/fulfilment/deliveryarea/{shop['central'].pk}/delete/").status_code == 403  # used by an order

    def test_order_admin_delivery_and_refused_change(self, client_for, tenant_a, shop, goods):
        from tests.test_orders import inline

        staff = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        due = timezone.localtime(at(tomorrow(), 16))
        data = {"customer": goods["customer"].pk, "channel": "phone", "fulfilment": "delivery", "delivery_address": "1 Queen Street",
                "delivery_suburb": "", "delivery_postcode": "1010", "delivery_area": "", "notes": "",
                "due_at_0": due.strftime("%Y-%m-%d"), "due_at_1": due.strftime("%H:%M:%S"),
                **inline("lines", [{"product": goods["goat"].pk, "quantity": "2", "note": ""}])}
        assert staff.post("/admin/orders/order/add/", data).status_code == 302
        with schema_context("tenant_a"):
            order = Order.objects.get()
            assert order.delivery_area == shop["central"] and order.total == Decimal("54.00") and order.due_until == at(tomorrow(), 17)
        move(order, S.CONFIRMED)
        with schema_context("tenant_a"):
            line = order.lines.get()
        change = {**data, "delivery_postcode": "9999", **inline("lines", [{"id": line.pk, "order": order.pk}], initial=1)}
        response = staff.post(f"/admin/orders/order/{order.pk}/change/", change, follow=True)
        assert "Not saved: Choose the delivery area" in response.content.decode()
        with schema_context("tenant_a"):
            order.refresh_from_db()
            assert order.delivery_postcode == "1010"
        page = staff.get(f"/admin/orders/order/{order.pk}/change/").content.decode()
        assert "Check before you go on" not in page
        move(delivery(goods), S.CONFIRMED)  # a second order in the same full window
        with schema_context("tenant_a"):
            second = Order.objects.order_by("-number").first()
        assert "slot is full" in staff.get(f"/admin/orders/order/{second.pk}/change/").content.decode()

    def test_order_admin_lists_pickup_and_delivery(self, client_for, tenant_a, shop, goods):
        delivery(goods)
        new_order(goods, due_at=at(tomorrow(), 9))
        staff = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        page = staff.get("/admin/orders/order/").content.decode()
        assert "Delivery to Central" in page and "Pickup" in page and "09:00–09:30" in page


@pytest.mark.django_db
class TestConfigurePermission:
    def test_default_roles(self, tenant_a):
        with schema_context("tenant_a"):
            assert "orders.configure" in Role.objects.get(slug="business_owner").permission_codes()
            assert "orders.configure" in Role.objects.get(slug="operations_manager").permission_codes()
            assert "orders.configure" not in Role.objects.get(slug="shop_staff").permission_codes()

    def test_existing_roles_with_every_orders_permission_get_it(self, tenant_a):
        migration = import_module("apps.orders.migrations.0003_pickup_and_delivery")
        with schema_context("tenant_a"):
            full = Role.objects.create(slug="kitchen_boss", name="Kitchen boss")
            for code in migration.OLD_ORDER_CODES:
                RolePermission.objects.create(role=full, code=code)
            part = Role.objects.create(slug="kitchen_helper", name="Kitchen helper")
            RolePermission.objects.create(role=part, code="orders.view")
            migration.add_configure(django_apps, None)
            migration.add_configure(django_apps, None)  # running twice changes nothing
            assert RolePermission.objects.filter(role=full, code="orders.configure").count() == 1
            assert not RolePermission.objects.filter(role=part, code="orders.configure").exists()


@pytest.mark.django_db
class TestCheckSystem:
    def test_warns_until_customers_can_choose_a_time(self, tenant_a):
        from apps.health import checks

        with schema_context("tenant_a"):
            result = checks.check_fulfilment()[0]
            assert result.status == "warning" and "no pickup hours" in result.message

    def test_ok_with_hours_and_areas(self, shop):
        from apps.health import checks

        with schema_context("tenant_a"):
            result = checks.check_fulfilment()[0]
            assert result.status == "ok" and " pickup times and " in result.message and "delivery times in the next 7 day(s)" in result.message
            DeliveryArea.objects.update(is_active=False)
            assert "no delivery areas" in checks.check_fulfilment()[0].message
            ClosedDay.objects.bulk_create([ClosedDay(date=timezone.localdate() + timedelta(days=n)) for n in range(7)])
            assert "no free pickup times in the next 7 days" in checks.check_fulfilment()[0].message
            FulfilmentSettings.objects.update(pickup_enabled=False, delivery_enabled=False)
            assert "both switched off" in checks.check_fulfilment()[0].message

    def test_only_with_the_orders_module(self, tenant_a):
        from apps.health import checks
        from apps.licensing.services import set_module_enabled

        set_module_enabled(tenant_a, "orders", False)
        with schema_context("tenant_a"):
            assert checks.check_fulfilment() == []
            assert "fulfilment" not in {r.code for r in checks.business_checks(tenant_a, live=False)}
        set_module_enabled(tenant_a, "orders", True)
        with schema_context("tenant_a"):
            assert "fulfilment" in {r.code for r in checks.business_checks(tenant_a, live=False)}
