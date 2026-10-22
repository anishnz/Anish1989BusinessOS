"""
Quick reorder and hand-over to staff (task 2.5, D-147 to D-150): "Order again"
for staff and the AI (today's prices, left-out products), the chats waiting
for staff, the email to managers, "I will answer" assigning the chat, the
dashboard card.
"""
from decimal import Decimal

import pytest
from django.core import mail
from django_tenants.utils import schema_context

from apps.ai import agent
from apps.ai.models import AIChat, AISettings
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.customers.services import anonymise
from apps.inbox.models import Conversation
from apps.orders import services
from apps.orders.models import Order
from tests.conftest import make_user
from tests.test_ai import Script, calls, client, goods, runs, shop_ai, text  # noqa: F401 (fixtures)
from tests.test_catalog import user_client
from tests.test_fulfilment import at, shop, tomorrow  # noqa: F401 (shop is a fixture)
from tests.test_inbox import WA_ID, graph  # noqa: F401 (graph is a fixture)

S = Order.Status
D = Decimal
L = services.LineInput


def placed(goods, customer, lines=None, **kw):
    """A confirmed order (one the customer really placed)."""
    lines = lines or [L(goods["goat"].pk, D("1.5"), "cut small"), L(goods["samosa"].pk, D("2"))]
    with schema_context("tenant_a"):
        order = services.create_order(lines=lines, customer=customer, channel="phone", notes="Ring the bell", **kw)
        return services.change_status(order, S.CONFIRMED)


@pytest.fixture
def sita(tenant_a):
    with schema_context("tenant_a"):
        return Customer.objects.create(name="Sita Sharma", phone="+" + WA_ID)


# ---------------------------------------------------------------------------
# Order again
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReorder:
    def test_same_products_at_todays_prices(self, goods, sita):
        source = placed(goods, sita, fulfilment="delivery", delivery_address="1 Queen Street", delivery_postcode="1010", due_at=at(tomorrow(), 16))
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["goat"].pk).update(price=D("25.00"))
            copy, left_out = services.reorder(source)
            lines = [(line.product_name, line.quantity, line.unit_price, line.note) for line in copy.lines.all()]
            assert lines == [("Goat curry cut", D("1.500"), D("25.00"), "cut small"), ("Samosa 12 pack", D("2.000"), D("15.00"), "")]
            assert (copy.status, copy.customer_id, copy.channel, copy.notes, copy.due_at) == (S.DRAFT, sita.pk, "phone", "Ring the bell", None)
            assert (copy.fulfilment, copy.delivery_address, copy.delivery_postcode, copy.delivery_area.name) == ("delivery", "1 Queen Street", "1010", "Central")
            assert left_out == [] and copy.events.last().note == f"Copied from order #{source.number}"
            assert copy.number != source.number

    def test_products_that_cannot_be_ordered_are_left_out(self, goods, sita):
        source = placed(goods, sita)
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["samosa"].pk).update(is_available=False)
            Product.objects.filter(pk=goods["goat"].pk).update(min_quantity=D("2"))
            with pytest.raises(Exception, match="None of the products"):
                services.reorder(source)
            Product.objects.filter(pk=goods["goat"].pk).update(min_quantity=D("0.5"))
            copy, left_out = services.reorder(source, channel="whatsapp")
            assert [line.product_name for line in copy.lines.all()] == ["Goat curry cut"] and copy.channel == "whatsapp"
            assert left_out[0].startswith("Samosa 12 pack (") and "left out: Samosa 12 pack" in copy.events.last().note

    def test_only_placed_orders_of_kept_customers(self, goods, sita):
        with schema_context("tenant_a"):
            draft = services.create_order(lines=[L(goods["samosa"].pk, D("1"))], customer=sita)
            with pytest.raises(Exception, match="not finished yet"):
                services.reorder(draft)
        source = placed(goods, sita)
        with schema_context("tenant_a"):
            anonymise(sita)
            source.refresh_from_db()
            with pytest.raises(Exception, match="personal data was removed"):
                services.reorder(source)

    def test_staff_button(self, goods, sita, client_for, tenant_a):
        source = placed(goods, sita)
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        response = counter.post(f"/api/orders/{source.pk}/reorder/")
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "draft" and body["left_out"] == [] and len(body["lines"]) == 2
        with schema_context("tenant_a"):
            assert Order.objects.get(pk=body["id"]).created_by.email == "counter@a.test"
        viewer = user_client(client_for, tenant_a, "money@a.test", "finance_manager")  # Orders – View only
        assert viewer.post(f"/api/orders/{source.pk}/reorder/").status_code == 403
        draft = counter.post(f"/api/orders/{body['id']}/reorder/")
        assert draft.status_code == 400 and "not finished yet" in draft.json()["detail"]

    def test_last_order_in_the_customer_list(self, goods, sita, client_for, tenant_a):
        first = placed(goods, sita)
        second = placed(goods, sita)
        with schema_context("tenant_a"):
            services.create_order(lines=[L(goods["samosa"].pk, D("1"))], customer=sita)  # a draft does not count
            Customer.objects.create(name="Ram Thapa", phone="+64219999999")
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        rows = {c["name"]: c["last_order"] for c in counter.get("/api/customers/").json()["results"]}
        assert rows == {"Sita Sharma": {"id": second.pk, "number": second.number}, "Ram Thapa": None}
        assert first.pk != second.pk


# ---------------------------------------------------------------------------
# "Same as last time" with the AI
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAIReorder:
    def test_past_orders_then_reorder(self, shop_ai, client, goods, monkeypatch, sita):  # noqa: F811
        old = placed(goods, sita)
        with schema_context("tenant_a"):
            other = Customer.objects.create(name="Someone else", phone="+64218888888")
        theirs = placed(goods, other)
        ai = Script(monkeypatch, [
            calls(("past_orders", {})),
            text(f"Your last order was #{old.number}: 1.5 kg Goat curry cut and 2 Samosa packs. Same again?"),
            calls(("reorder", {"order_number": theirs.number}), ("reorder", {"order_number": old.number}), ("reorder", {"order_number": old.number})),
            text("Done! What time would you like it?"),
        ])
        shop_ai(client, "same as last time please", 1)
        assert runs()[0].steps[0]["result"]["orders"][0]["order_number"] == old.number
        assert len(runs()[0].steps[0]["result"]["orders"]) == 1  # only this customer's orders
        shop_ai(client, "yes same", 2)
        results = [s["result"] for s in runs()[1].steps]
        assert "is not one of this customer's past orders" in results[0]["error"]
        assert results[1]["order"]["lines"][0]["product"] == "Goat curry cut" and "today's prices" in results[1]["note"]
        assert "already being made" in results[2]["error"]
        with schema_context("tenant_a"):
            order = AIChat.objects.get().order
            assert (order.status, order.channel, order.customer_id) == (S.DRAFT, "whatsapp", sita.pk)
        assert "past_orders" in ai.asked[0]["tools"] and "pahile jastai" in ai.asked[0]["system"]

    def test_reorder_needs_a_number(self, goods, sita):
        from apps.ai import tools

        with schema_context("tenant_a"):
            conversation = Conversation.objects.create(external_id=WA_ID, customer=sita)
            ctx = tools.Context(chat=AIChat.objects.create(conversation=conversation), customer=sita)
            assert tools.run(ctx, "reorder", {"order_number": "abc"}) == {"error": "order_number must be a number."}
            assert tools.run(ctx, "past_orders", {}) == {"orders": [], "note": "This customer has no past orders yet."}


# ---------------------------------------------------------------------------
# Hand-over: waiting list, email, "I will answer", dashboard
# ---------------------------------------------------------------------------
def hand_over_chat(shop_ai, client, monkeypatch, n=1, reason="Complaint about yesterday's order"):  # noqa: F811
    Script(monkeypatch, [calls(("hand_over", {"reason": reason})), text("Sorry! A staff member will call you.")])
    shop_ai(client, "the meat was bad", n)
    with schema_context("tenant_a"):
        return Conversation.objects.get()


@pytest.mark.django_db
class TestHandover:
    def test_waiting_until_someone_picks_it_up(self, shop_ai, client, monkeypatch, client_for, tenant_a):
        conversation = hand_over_chat(shop_ai, client, monkeypatch)
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        waiting = counter.get("/api/ai/waiting/").json()
        assert waiting["count"] == 1 and waiting["results"][0]["reason"] == "Complaint about yesterday's order"
        assert waiting["results"][0]["conversation"] == conversation.pk and waiting["results"][0]["customer_name"]
        counter.post(f"/api/inbox/conversations/{conversation.pk}/reply/", {"text": "Hi, sorry about that"}, content_type="application/json")
        assert counter.get("/api/ai/waiting/").json()["count"] == 0  # a staff reply picks it up

    def test_assigned_or_closed_chats_are_not_waiting(self, shop_ai, client, monkeypatch, tenant_a):
        conversation = hand_over_chat(shop_ai, client, monkeypatch)
        staff = make_user("tenant_a", "gita@a.test", staff=True)
        with schema_context("tenant_a"):
            assert agent.waiting_chats().count() == 1
            Conversation.objects.filter(pk=conversation.pk).update(assigned_to=staff)
            assert agent.waiting_chats().count() == 0
            Conversation.objects.filter(pk=conversation.pk).update(assigned_to=None, status="closed")
            assert agent.waiting_chats().count() == 0

    def test_i_will_answer_assigns_the_chat(self, shop_ai, client, monkeypatch, client_for, tenant_a, django_capture_on_commit_callbacks):
        from apps.ai import tasks

        Script(monkeypatch, [text("Hi!")])
        shop_ai(client, "hello", 1)
        with schema_context("tenant_a"):
            conversation = Conversation.objects.get()
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        emails = []
        monkeypatch.setattr(tasks.handover_email_task, "delay", lambda schema, pk: emails.append(pk))
        with django_capture_on_commit_callbacks(execute=True):
            counter.post(f"/api/ai/chats/{conversation.pk}/", {"answer": False}, content_type="application/json")
        assert emails == []
        with schema_context("tenant_a"):
            assert Conversation.objects.get().assigned_to.email == "counter@a.test"
            assert agent.waiting_chats().count() == 0
        # staff took it over themselves: no email (checked above)

    def test_email_to_managers(self, shop_ai, client, monkeypatch, django_capture_on_commit_callbacks):
        from apps.ai import tasks

        make_user("tenant_a", "owner@a.test", staff=True)
        make_user("tenant_a", "counter@a.test", staff=True)
        make_user("tenant_a", "gone@a.test", staff=True, is_active=False)
        with schema_context("tenant_a"):
            from apps.accounts.models import User
            from apps.rbac.models import Role, UserRole

            UserRole.objects.create(user=User.objects.get(email="owner@a.test"), role=Role.objects.get(slug="business_owner"))
            UserRole.objects.create(user=User.objects.get(email="counter@a.test"), role=Role.objects.get(slug="shop_staff"))
            UserRole.objects.create(user=User.objects.get(email="gone@a.test"), role=Role.objects.get(slug="business_owner"))
        monkeypatch.setattr(tasks.handover_email_task, "delay", lambda schema, pk: tasks.handover_email_task(schema, pk))
        mail.outbox.clear()
        conversation = hand_over_chat(shop_ai, client, monkeypatch)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == ["owner@a.test"]  # Customers – Assign, active; not Shop Staff
        assert email.subject.startswith("Chat needs staff: ") and "Tenant A Butchery" in email.subject
        assert "Reason: Complaint about yesterday's order" in email.body and f"/app/inbox/{conversation.pk}" in email.body
        assert "the meat was bad" not in email.body  # never the messages

    def test_email_can_be_switched_off(self, shop_ai, client, monkeypatch):
        from apps.ai import tasks

        sent = []
        monkeypatch.setattr(tasks.handover_email_task, "delay", lambda schema, pk: sent.append(pk))
        with schema_context("tenant_a"):
            AISettings.objects.update_or_create(pk=1, defaults={"email_on_handover": False})
        hand_over_chat(shop_ai, client, monkeypatch)
        assert sent == []

    def test_dashboard_card(self, shop_ai, client, monkeypatch, client_for, tenant_a):
        hand_over_chat(shop_ai, client, monkeypatch)
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        body = owner.get("/api/reports/dashboard/").json()
        assert body["waiting_chats"]["count"] == 1 and body["waiting_chats"]["oldest"][0]["reason"] == "Complaint about yesterday's order"
        hr = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        assert hr.get("/api/ai/waiting/").status_code == 403
