"""
The live order board (task 2.6, D-151 to D-154): which orders are on it, the
columns and their order, the one next step on each card (always one the
normal status rules accept), late orders, short names and no street address,
permissions and separate businesses.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.orders import board, services
from apps.orders.models import Order
from tests.test_catalog import user_client
from tests.test_fulfilment import at, shop  # noqa: F401 (shop is a fixture: pickup 9-12, delivery 16-18, area Central)
from tests.test_orders import L, goods, move, new_order  # noqa: F401 (goods is a fixture)

S = Order.Status
D = Decimal


def today():
    return timezone.localdate()


def samosas(goods, **kw):  # noqa: F811
    """An order with products sold each (no weighing)."""
    return new_order(goods, lines=[L(goods["samosa"].pk, D("2"), "in a box")], **kw)


def placed(order, *statuses, **kw):
    return move(order, S.CONFIRMED, *statuses, **kw)


def deliver(goods, **kw):  # noqa: F811
    details = {"fulfilment": "delivery", "delivery_address": "1 Queen Street", "delivery_suburb": "Mount Eden",
               "delivery_postcode": "1010", "due_at": at(today(), 16)}
    return samosas(goods, **(details | kw))


def run(**kw):
    with schema_context("tenant_a"):
        return board.board(**kw)


def columns(result) -> dict[str, list[int]]:
    return {c["key"]: [card["number"] for card in c["orders"]] for c in result["columns"]}


def cards(result) -> dict[int, dict]:
    return {card["number"]: card for c in result["columns"] for card in c["orders"]}


# ---------------------------------------------------------------------------
# What is on the board
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWhatIsOnTheBoard:
    def test_columns_days_and_order(self, goods, shop):  # noqa: F811
        day = today()
        nine = placed(samosas(goods, due_at=at(day, 9)))
        ten = placed(samosas(goods, due_at=at(day, 10)))
        earlier = placed(samosas(goods, due_at=at(day - timedelta(days=2), 7, 30)))  # not done 2 days ago: late
        no_time = placed(samosas(goods, due_at=at(day, 11)))
        with schema_context("tenant_a"):
            Order.objects.filter(pk=no_time.pk).update(due_at=None, due_until=None)  # older orders may have no time
        preparing = placed(samosas(goods, due_at=at(day, 9, 30)), S.PREPARING)
        ready = placed(samosas(goods, due_at=at(day, 10, 30)), S.PREPARING, S.READY)
        out = placed(deliver(goods), S.PREPARING, S.READY, S.OUT_FOR_DELIVERY)
        tomorrow = placed(samosas(goods, due_at=at(day + timedelta(days=1), 9)))
        later = placed(samosas(goods, due_at=at(day + timedelta(days=2), 9)))
        # Not on the board: not confirmed yet, finished, or cancelled
        samosas(goods, due_at=at(day, 9))
        move(samosas(goods, due_at=at(day, 9)), S.AWAITING)
        placed(samosas(goods, due_at=at(day, 9)), S.PREPARING, S.READY, S.COMPLETED)
        move(placed(samosas(goods, due_at=at(day, 9))), S.CANCELLED_SHOP, note="Closed early")

        now = at(day, 8)
        result = run(now=now)
        assert columns(result) == {
            "to_prepare": [earlier.number, nine.number, ten.number, no_time.number],  # late first, then by time, no time last
            "preparing": [preparing.number], "ready": [ready.number], "out": [out.number],
        }
        assert (result["count"], result["late"], result["today"], result["tomorrow"]) == (7, 1, day, False)
        with_tomorrow = columns(run(now=now, tomorrow=True))["to_prepare"]
        assert with_tomorrow == [earlier.number, nine.number, ten.number, tomorrow.number, no_time.number]
        assert later.number not in with_tomorrow

    def test_final_price_steps_are_in_being_prepared(self, goods, shop):  # noqa: F811
        order = placed(new_order(goods, due_at=at(today(), 9)), S.PREPARING)
        with schema_context("tenant_a"):
            line = order.lines.get(unit="kg")
            order = services.set_weights(order, {line.pk: D("1.62")})
        sent = move(order, S.FINAL_SENT)
        assert columns(run(now=at(today(), 8)))["preparing"] == [sent.number]
        accepted = move(sent, S.FINAL_ACCEPTED)
        card = cards(run(now=at(today(), 8)))[accepted.number]
        assert (card["status"], card["status_label"]) == (S.FINAL_ACCEPTED, "Final price accepted")

    def test_times_and_late(self, goods, shop):  # noqa: F811
        day = today()
        slot = placed(samosas(goods, due_at=at(day, 11, 30)))  # slot 11:30-12:00
        typed = placed(samosas(goods, due_at=at(day, 7, 45)))  # staff typed a time that is not a slot
        tomorrow = placed(samosas(goods, due_at=at(day + timedelta(days=1), 10)))
        earlier = placed(samosas(goods, due_at=at(day - timedelta(days=2), 7, 30)))
        found = cards(run(now=at(day, 11, 45), tomorrow=True))
        assert found[slot.number]["time_text"] == "11:30–12:00" and not found[slot.number]["late"]  # inside its slot
        assert found[typed.number]["time_text"] == "07:45" and found[typed.number]["late"]
        assert found[tomorrow.number]["time_text"] == "Tomorrow 10:00–10:30" and not found[tomorrow.number]["late"]
        two_days_ago = day - timedelta(days=2)
        assert found[earlier.number]["time_text"] == f"{two_days_ago:%a} {two_days_ago.day} {two_days_ago:%b} 07:30"
        assert found[earlier.number]["late"]
        assert cards(run(now=at(day, 12, 1)))[slot.number]["late"]  # the slot is over
        # Late orders come first, even before an earlier time that is not late yet (still inside its slot)
        typed_late = placed(samosas(goods, due_at=at(day, 11, 40)))
        order = columns(run(now=at(day, 11, 45), tomorrow=True))["to_prepare"]
        assert order == [earlier.number, typed.number, typed_late.number, slot.number, tomorrow.number]

    def test_card_shows_short_name_and_suburb_only(self, goods, shop):  # noqa: F811
        order = placed(deliver(goods, notes="Ring the bell"))
        card = cards(run(now=at(today(), 8)))[order.number]
        assert (card["customer"], card["fulfilment"], card["suburb"], card["notes"]) == ("Sita S.", "delivery", "Mount Eden", "Ring the bell")
        assert card["lines"] == [{"name": "Samosa 12 pack", "amount": "2", "unit": "pack", "note": "in a box", "weighed": False}]
        assert (card["is_paid"], card["total"]) == (False, "38.00")  # 2 x $15 + $8 delivery
        text = str(card)
        assert "Queen Street" not in text and "+64211234567" not in text and "Sharma" not in text

    def test_walk_in_and_removed_customers(self, goods, shop):  # noqa: F811
        walk_in = placed(samosas(goods, customer=None, due_at=at(today(), 9)))
        order = placed(samosas(goods, due_at=at(today(), 10)))
        customer = goods["customer"]
        with schema_context("tenant_a"):
            customer.name, customer.is_anonymised = "Removed customer", True  # as after a privacy request (test_customers)
            customer.save(update_fields=["name", "is_anonymised"])
        found = cards(run(now=at(today(), 8)))
        assert (found[walk_in.number]["customer"], found[order.number]["customer"]) == ("Walk-in", "Customer")
        with schema_context("tenant_a"):
            customer.name, customer.is_anonymised = "Asha", False  # one name only
            customer.save(update_fields=["name", "is_anonymised"])
        assert cards(run(now=at(today(), 8)))[order.number]["customer"] == "Asha"


# ---------------------------------------------------------------------------
# The next step on each card
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNextStep:
    def step(self, order):
        with schema_context("tenant_a"):
            return board.next_step(Order.objects.get(pk=order.pk))

    def test_every_step(self, goods, shop):  # noqa: F811
        pickup = placed(new_order(goods, due_at=at(today(), 9)))
        assert self.step(pickup) == {"to": S.PREPARING, "label": "Start preparing"}
        pickup = move(pickup, S.PREPARING)
        assert self.step(pickup) == {"note": "Enter the real weights on the order page"}
        with schema_context("tenant_a"):
            line = pickup.lines.get(unit="kg")
            pickup = services.set_weights(pickup, {line.pk: D("1.5")})  # the same as ordered: same price
        assert self.step(pickup) == {"to": S.READY, "label": "Ready for pickup"}
        with schema_context("tenant_a"):
            pickup = services.set_weights(pickup, {line.pk: D("1.62")})
        assert self.step(pickup) == {"to": S.FINAL_SENT, "label": "Send final price"}
        pickup = move(pickup, S.FINAL_SENT)
        assert self.step(pickup) == {"note": "Waiting for the customer to accept the price"}
        pickup = move(pickup, S.FINAL_ACCEPTED)
        assert self.step(pickup) == {"to": S.READY, "label": "Ready for pickup"}
        pickup = move(pickup, S.READY)
        assert self.step(pickup) == {"to": S.COMPLETED, "label": "Picked up"}

        delivery = placed(deliver(goods), S.PREPARING)
        assert self.step(delivery) == {"to": S.READY, "label": "Ready for delivery"}
        delivery = move(delivery, S.READY)
        assert self.step(delivery) == {"to": S.OUT_FOR_DELIVERY, "label": "Out for delivery"}
        delivery = move(delivery, S.OUT_FOR_DELIVERY)
        assert self.step(delivery) == {"to": S.COMPLETED, "label": "Delivered"}

    def test_the_rules_accept_every_step_the_board_offers(self, goods, shop):  # noqa: F811
        """Follow the board's button from Confirmed to the end, for pickup and delivery: every move must pass the normal rules."""
        for order in (placed(samosas(goods, due_at=at(today(), 9))), placed(deliver(goods))):
            seen = []
            while True:
                with schema_context("tenant_a"):
                    order = Order.objects.get(pk=order.pk)
                    step = board.next_step(order)
                    if "to" not in step:
                        break
                    seen.append(step["label"])
                    order = services.change_status(order, step["to"])
            assert order.status == S.COMPLETED, seen
        assert seen == ["Start preparing", "Ready for delivery", "Out for delivery", "Delivered"]


# ---------------------------------------------------------------------------
# API, permissions and separate businesses
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBoardApi:
    def test_staff_see_the_board_and_move_orders(self, client_for, tenant_a, goods, shop):  # noqa: F811
        order = placed(samosas(goods, due_at=at(today(), 9)))
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        data = counter.get("/api/orders/board/").json()
        assert [c["key"] for c in data["columns"]] == ["to_prepare", "preparing", "ready", "out"]
        card = data["columns"][0]["orders"][0]
        assert card["number"] == order.number and card["next"] == {"to": "preparing", "label": "Start preparing"}
        moved = counter.post(f"/api/orders/{order.pk}/status/", {"to": card["next"]["to"]}, content_type="application/json")
        assert moved.status_code == 200 and moved.json()["status"] == "preparing"
        assert counter.get("/api/orders/board/").json()["columns"][1]["orders"][0]["number"] == order.number
        tomorrow = placed(samosas(goods, due_at=at(today() + timedelta(days=1), 9)))
        assert counter.get("/api/orders/board/").json()["count"] == 1
        both = counter.get("/api/orders/board/?tomorrow=1").json()
        assert both["count"] == 2 and both["tomorrow"] is True and both["columns"][0]["orders"][0]["number"] == tomorrow.number

    def test_view_only_and_no_access(self, client_for, tenant_a, goods, shop):  # noqa: F811
        order = placed(samosas(goods, due_at=at(today(), 9)))
        support = user_client(client_for, tenant_a, "support@a.test", "support_agent")  # orders.view only
        assert support.get("/api/orders/board/").json()["count"] == 1
        refused = support.post(f"/api/orders/{order.pk}/status/", {"to": "preparing"}, content_type="application/json")
        assert refused.status_code == 403
        content = user_client(client_for, tenant_a, "web@a.test", "content_manager")  # no orders permission
        assert content.get("/api/orders/board/").status_code == 403
        assert client_for(tenant_a).get("/api/orders/board/").status_code in (401, 403)

    def test_each_business_sees_only_its_own_orders(self, client_for, tenant_a, tenant_b, goods, shop):  # noqa: F811
        placed(samosas(goods, due_at=at(today(), 9)))
        other = user_client(client_for, tenant_b, "counter@b.test", "shop_staff")
        assert other.get("/api/orders/board/").json()["count"] == 0
