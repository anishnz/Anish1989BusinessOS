"""
WhatsApp messages to customers about their orders (task 2.3, D-135 to D-139):
status messages, the Yes/No questions (please confirm, final price), normal
messages inside the 24-hour window and approved templates outside it, the
answers, the settings page and the order pages.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.catalog import stock
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.customers.services import anonymise
from apps.inbox.models import Conversation, Message
from apps.orders import notify, services, tasks
from apps.orders.models import CustomerMessageSettings, Order, OrderMessage
from tests.test_catalog import make_product, user_client
from tests.test_fulfilment import at, shop, tomorrow  # noqa: F401 (shop is a fixture)
from tests.test_inbox import WA_ID, connect_whatsapp, graph, incoming, post_webhook  # noqa: F401 (graph is a fixture)
from tests.test_orders import L
from tests.test_rbac import verified_staff_client

S = Order.Status
K = OrderMessage.Kind
D = Decimal
SHOP = "Tenant A Butchery"  # the business name in the messages


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def goods(tenant_a, shop):  # noqa: F811 (pickup and delivery times, so customers can confirm)
    goat = make_product(name="Goat curry cut", sku="GOAT", unit="kg", price=D("23.00"), min_quantity=D("0.5"), quantity_step=D("0.5"))
    samosa = make_product(name="Samosa 12 pack", sku="SAM", unit="pack", price=D("15.00"), search_terms="")
    with schema_context("tenant_a"):
        # The first WhatsApp message may have made the customer already (the `wa` fixture).
        customer, _ = Customer.objects.update_or_create(phone="+" + WA_ID, defaults={"name": "Sita Sharma"})
    return {"goat": goat, "samosa": samosa, "customer": customer}


@pytest.fixture
def send_now(monkeypatch, django_capture_on_commit_callbacks):
    """The worker sends queued messages at once (and every queued callback runs)."""
    monkeypatch.setattr(tasks.send_order_message, "delay", lambda schema, pk: tasks.send_order_message(schema, pk))

    def run(func, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return func(*args, **kwargs)
    return run


@pytest.fixture
def wa(tenant_a, client_for, graph):  # noqa: F811
    """WhatsApp connected; the customer wrote a minute ago (the 24-hour window is open)."""
    connect_whatsapp()
    client = client_for(tenant_a)
    post_webhook(client, incoming("Namaste, 1.5 kg goat please", msg_id="wamid.first"))
    return client


SLOTS = iter(range(10_000))


def new_order(goods, lines=None, **kw):
    """A pickup order in its own free pickup slot tomorrow (unless due_at is given)."""
    lines = lines or [L(goods["goat"].pk, D("1.5")), L(goods["samosa"].pk, D("2"))]
    if "due_at" not in kw:
        n = next(SLOTS) % 6
        kw["due_at"] = at(tomorrow(), 9 + n // 2, 30 * (n % 2))
    with schema_context("tenant_a"):
        return services.create_order(lines=lines, customer=kw.pop("customer", goods["customer"]), **kw)


def move(run, order, *statuses, **kw):
    def go():
        o = order
        for status in statuses:
            o = services.change_status(o, status, **kw)
        return o
    with schema_context("tenant_a"):
        return run(go)


def sent(graph, n=-1):  # noqa: F811
    return graph.calls[n]["json"]


def press(run, client, message: OrderMessage, answer: str, wa_id=WA_ID, msg_id=None, template=False):
    """The customer presses Yes or No on our message."""
    payload = f"order:{message.pk}:{message.token}:{answer}"
    if template:
        extra = {"button": {"payload": payload, "text": "Yes" if answer == "yes" else "No"}}
        body = incoming(wa_id=wa_id, msg_id=msg_id or f"wamid.press.{message.pk}.{answer}", kind="button", extra=extra)
    else:
        extra = {"interactive": {"type": "button_reply", "button_reply": {"id": payload, "title": "Yes" if answer == "yes" else "No"}}}
        body = incoming(wa_id=wa_id, msg_id=msg_id or f"wamid.press.{message.pk}.{answer}", kind="interactive", extra=extra)
    return run(post_webhook, client, body)


def type_answer(run, client, text, msg_id):
    return run(post_webhook, client, incoming(text, msg_id=msg_id))


def refreshed(order) -> Order:
    with schema_context("tenant_a"):
        return Order.objects.get(pk=order.pk)


def messages(order) -> list:
    with schema_context("tenant_a"):
        return list(OrderMessage.objects.filter(order=order).order_by("id"))


def question(order, kind=K.CONFIRM_REQUEST) -> OrderMessage:
    with schema_context("tenant_a"):
        return OrderMessage.objects.filter(order=order, kind=kind).order_by("-id").first()


def close_window():
    with schema_context("tenant_a"):
        Conversation.objects.update(last_inbound_at=timezone.now() - timedelta(hours=25))


def settings(**fields):
    with schema_context("tenant_a"):
        CustomerMessageSettings.objects.update_or_create(pk=1, defaults=fields)


# ---------------------------------------------------------------------------
# Please confirm
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPleaseConfirm:
    def test_summary_with_yes_and_no_buttons(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods, notes="Cut small"), S.AWAITING)
        body = sent(graph)
        assert body["to"] == WA_ID and body["type"] == "interactive"
        text = body["interactive"]["body"]["text"]
        assert f"please check your order #{order.number}" in text and "- 1.5 kg Goat curry cut" in text and "- 2 x Samosa 12 pack" in text
        assert "Estimated total: $64.50" in text and "weighed when packed" in text and text.endswith("Is this correct?")
        buttons = body["interactive"]["action"]["buttons"]
        q = question(order)
        assert [b["reply"]["title"] for b in buttons] == ["Yes, confirm", "No"]
        assert [b["reply"]["id"] for b in buttons] == [f"order:{q.pk}:{q.token}:yes", f"order:{q.pk}:{q.token}:no"]
        assert (q.status, q.via, q.is_open, q.asked_total) == ("sent", "message", True, D("64.50")) and len(q.token) == 16
        with schema_context("tenant_a"):
            assert q.inbox_message.direction == "out" and "[Yes, confirm] | [No]" in q.inbox_message.text

    def test_yes_confirms_with_the_customer_rules(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods, due_at=at(tomorrow(), 10)), S.AWAITING)
        assert press(send_now, wa, question(order), "yes").status_code == 200
        order = refreshed(order)
        assert order.status == S.CONFIRMED and order.confirmed_at
        with schema_context("tenant_a"):
            event = order.events.get(to_status=S.CONFIRMED)
            assert event.actor is None and event.note == "Customer said Yes on WhatsApp"
        q = question(order)
        assert (q.answer, q.is_open) == ("yes", False) and q.answered_at
        assert f"Your order #{order.number}" in sent(graph)["text"]["body"] and "is confirmed" in sent(graph)["text"]["body"]

    def test_yes_without_the_confirmed_message_gets_a_short_thank_you(self, wa, graph, goods, send_now):  # noqa: F811
        settings(on_confirmed=False)
        order = move(send_now, new_order(goods), S.AWAITING)
        press(send_now, wa, question(order), "yes")
        assert refreshed(order).status == S.CONFIRMED
        assert sent(graph)["text"]["body"] == f"Thank you, order #{order.number} is confirmed."

    def test_no_goes_back_to_draft_and_staff_see_it(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        press(send_now, wa, question(order), "no")
        order = refreshed(order)
        assert order.status == S.DRAFT
        assert sent(graph)["text"]["body"] == f"OK, order #{order.number} is not confirmed. We will contact you to change it."
        with schema_context("tenant_a"):
            assert services.warnings(order)[0] == "Customer said No on WhatsApp. Call the customer."
            order = services.update_order(order, notes="Changed by phone")
            assert services.warnings(order)[0] == "Customer said No on WhatsApp. Call the customer."  # until it moves on
        order = move(send_now, order, S.AWAITING)
        with schema_context("tenant_a"):
            assert not any("Customer said" in w for w in services.warnings(order))

    def test_yes_that_breaks_a_customer_rule(self, wa, graph, goods, send_now):  # noqa: F811
        with schema_context("tenant_a"):
            Product.objects.filter(pk=goods["goat"].pk).update(track_stock=True)
            stock.adjust(Product.objects.get(pk=goods["goat"].pk), reason="received", quantity="1")
        order = move(send_now, new_order(goods), S.AWAITING)
        press(send_now, wa, question(order), "yes")
        order = refreshed(order)
        assert order.status == S.DRAFT and not order.stock_taken
        reply = sent(graph)["text"]["body"]
        assert reply.startswith(f"Sorry, we could not confirm order #{order.number}: Only 1 kg of Goat curry cut in stock") and "contact you soon" in reply
        with schema_context("tenant_a"):
            assert services.warnings(order)[0].startswith("Customer said Yes on WhatsApp, but the order could not be confirmed: Only 1 kg")

    def test_typed_answers(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        type_answer(send_now, wa, "maybe later", "wamid.t1")
        assert refreshed(order).status == S.AWAITING
        type_answer(send_now, wa, "Ho!", "wamid.t2")  # Nepali "yes"
        assert refreshed(order).status == S.CONFIRMED
        other = move(send_now, new_order(goods), S.AWAITING)
        type_answer(send_now, wa, " NO. ", "wamid.t3")
        assert refreshed(other).status == S.DRAFT

    def test_typed_answer_is_not_used_when_two_questions_are_open(self, wa, graph, goods, send_now):  # noqa: F811
        first = move(send_now, new_order(goods), S.AWAITING)
        second = move(send_now, new_order(goods), S.AWAITING)
        type_answer(send_now, wa, "yes", "wamid.t4")
        assert (refreshed(first).status, refreshed(second).status) == (S.AWAITING, S.AWAITING)
        press(send_now, wa, question(second), "yes")  # the buttons still say which order
        assert (refreshed(first).status, refreshed(second).status) == (S.AWAITING, S.CONFIRMED)

    def test_old_buttons_do_nothing(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        old = question(order)
        order = move(send_now, order, S.DRAFT)  # staff changed something
        assert not question(order).is_open
        calls = len(graph.calls)
        press(send_now, wa, old, "yes")
        assert refreshed(order).status == S.DRAFT
        assert "already answered or has changed" in sent(graph)["text"]["body"] and len(graph.calls) == calls + 1
        order = move(send_now, order, S.AWAITING)
        new = question(order)
        assert new.pk != old.pk
        press(send_now, wa, old, "yes", msg_id="wamid.old.again")  # the old button cannot answer the new question
        assert refreshed(order).status == S.AWAITING
        press(send_now, wa, new, "yes")
        press(send_now, wa, new, "no", msg_id="wamid.second.press")  # pressed again: already answered
        assert refreshed(order).status == S.CONFIRMED

    def test_buttons_only_work_in_their_own_chat(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        press(send_now, wa, q, "yes", wa_id="64219999999")  # someone else
        assert refreshed(order).status == S.AWAITING
        fake = OrderMessage(pk=q.pk, token="0" * 16)
        press(send_now, wa, fake, "yes", msg_id="wamid.fake")  # a made-up button id
        assert refreshed(order).status == S.AWAITING and question(order).is_open

    def test_the_same_webhook_twice_answers_once(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        press(send_now, wa, q, "yes", msg_id="wamid.dup")
        calls = len(graph.calls)
        press(send_now, wa, q, "yes", msg_id="wamid.dup")  # Meta may send the same message again
        assert len(graph.calls) == calls

    def test_template_outside_the_24_hours(self, wa, graph, goods, send_now):  # noqa: F811
        close_window()
        order = move(send_now, new_order(goods), S.AWAITING)
        body = sent(graph)
        q = question(order)
        assert body["type"] == "template" and body["template"]["name"] == "order_confirm_request" and body["template"]["language"] == {"code": "en"}
        params = [p["text"] for p in body["template"]["components"][0]["parameters"]]
        assert params[:3] == ["Sita Sharma", str(order.number), SHOP] and params[3] == "1.5 kg Goat curry cut, 2 x Samosa 12 pack"
        assert params[4].startswith("Pickup") and params[5] == "64.50" and not any("\n" in p for p in params)
        assert body["template"]["components"][1:] == [
            {"type": "button", "sub_type": "quick_reply", "index": "0", "parameters": [{"type": "payload", "payload": f"order:{q.pk}:{q.token}:yes"}]},
            {"type": "button", "sub_type": "quick_reply", "index": "1", "parameters": [{"type": "payload", "payload": f"order:{q.pk}:{q.token}:no"}]},
        ]
        assert q.via == "template" and q.is_open
        press(send_now, wa, q, "yes", template=True)  # pressing the template's button opens the window again
        assert refreshed(order).status == S.CONFIRMED

    def test_no_template_name_means_not_sent(self, wa, graph, goods, send_now):  # noqa: F811
        settings(template_confirm_request="")
        close_window()
        calls = len(graph.calls)
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        assert len(graph.calls) == calls and q.status == "skipped" and not q.is_open
        assert "no template is set" in q.note and notify.status_text(q).startswith("Not sent: More than 24 hours")


# ---------------------------------------------------------------------------
# Final price
# ---------------------------------------------------------------------------
def weighed(run, goods, weight="1.62"):
    order = move(run, new_order(goods), S.CONFIRMED, S.PREPARING)
    with schema_context("tenant_a"):
        line = order.lines.get(product=goods["goat"])
        services.set_weights(order, {line.pk: weight})
        order.refresh_from_db()
    return order


@pytest.mark.django_db
class TestFinalPrice:
    def test_new_price_with_buttons_and_yes(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, weighed(send_now, goods), S.FINAL_SENT)
        body = sent(graph)
        text = body["interactive"]["body"]["text"]
        assert "The final price is $67.26 (estimate: $64.50)" in text and text.endswith("Do you accept the final price?")
        assert [b["reply"]["title"] for b in body["interactive"]["action"]["buttons"]] == ["Yes, accept", "No"]
        q = question(order, K.FINAL_PRICE)
        assert q.asked_total == D("67.26") and q.is_open
        press(send_now, wa, q, "yes")
        order = refreshed(order)
        assert order.status == S.FINAL_ACCEPTED
        with schema_context("tenant_a"):
            assert order.events.last().note == "Customer accepted the final price ($67.26) on WhatsApp"
        assert sent(graph)["text"]["body"] == f"Thank you. We will tell you when order #{order.number} is ready."

    def test_no_goes_back_to_staff(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, weighed(send_now, goods), S.FINAL_SENT)
        press(send_now, wa, question(order, K.FINAL_PRICE), "no")
        order = refreshed(order)
        assert order.status == S.PREPARING
        assert sent(graph)["text"]["body"] == f"OK. Our staff will contact you about order #{order.number}."
        with schema_context("tenant_a"):
            assert services.warnings(order)[0] == "Customer said No to the final price ($67.26) on WhatsApp. Call the customer."
            line = order.lines.get(product=goods["goat"])
            services.set_weights(order, {line.pk: "1.5"})  # weighed again: same as the estimate
            order.refresh_from_db()
        move(send_now, order, S.READY)
        assert "is ready for pickup" in sent(graph)["text"]["body"]

    def test_template_with_the_price(self, wa, graph, goods, send_now):  # noqa: F811
        order = weighed(send_now, goods)
        close_window()
        move(send_now, order, S.FINAL_SENT)
        params = [p["text"] for p in sent(graph)["template"]["components"][0]["parameters"]]
        assert sent(graph)["template"]["name"] == "order_final_price" and params == ["Sita Sharma", str(order.number), "67.26", "64.50"]

    def test_a_price_nobody_saw_is_never_accepted(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, weighed(send_now, goods), S.FINAL_SENT)
        with schema_context("tenant_a"):
            OrderMessage.objects.filter(order=order, kind=K.FINAL_PRICE).update(asked_total=D("60.00"))
        assert notify.apply_answer(question(order, K.FINAL_PRICE), "yes", pressed=True) == "closed"
        assert refreshed(order).status == S.FINAL_SENT


# ---------------------------------------------------------------------------
# Status messages and settings
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStatusMessages:
    def test_pickup_order_from_confirmed_to_completed(self, wa, graph, goods, send_now):  # noqa: F811
        order = new_order(goods, lines=[L(goods["samosa"].pk, D("2"))])
        start = len(graph.calls)
        order = move(send_now, order, S.CONFIRMED, S.PREPARING, S.READY, S.COMPLETED)
        bodies = [c["json"]["text"]["body"] for c in graph.calls[start:]]
        assert len(bodies) == 2  # confirmed and ready; nothing for preparing and completed
        assert "is confirmed" in bodies[0] and "Pickup" in bodies[0]
        assert bodies[1] == f"Hello Sita Sharma, your order #{order.number} from {SHOP} is ready for pickup.\nTotal: $30.00\nSee you soon!"
        assert [m.kind for m in messages(order)] == [K.CONFIRMED, K.READY]

    def test_delivery_order(self, wa, graph, goods, send_now):  # noqa: F811
        order = new_order(goods, lines=[L(goods["samosa"].pk, D("3"))], fulfilment="delivery", delivery_address="1 Queen Street",
                          delivery_postcode="1010", due_at=at(tomorrow(), 16))
        start = len(graph.calls)
        order = move(send_now, order, S.CONFIRMED, S.PREPARING, S.READY, S.OUT_FOR_DELIVERY)
        bodies = [c["json"]["text"]["body"] for c in graph.calls[start:]]
        assert len(bodies) == 3
        assert "Delivery to 1 Queen Street, " in bodies[0] and "is ready for delivery" in bodies[1]
        assert bodies[2] == f"Hello Sita Sharma, your order #{order.number} from {SHOP} is on the way.\nTotal: $53.00 (pay on delivery)\nThank you!"
        calls = len(graph.calls)
        order = move(send_now, order, S.READY, note="Nobody home")
        assert len(graph.calls) == calls  # no second "ready"
        move(send_now, order, S.OUT_FOR_DELIVERY)
        assert "is on the way" in sent(graph)["text"]["body"]

    def test_cancelled_by_the_shop_with_the_reason(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.CONFIRMED)
        move(send_now, order, S.CANCELLED_SHOP, note="No goat delivery today")
        assert sent(graph)["text"]["body"] == (f"Hello Sita Sharma, sorry, your order #{order.number} from {SHOP} was cancelled.\n"
                                               "Reason: No goat delivery today\nPlease contact us if you have questions.")
        other = move(send_now, new_order(goods), S.CONFIRMED)
        calls = len(graph.calls)
        move(send_now, other, S.CANCELLED_CUSTOMER, note="Changed mind")
        assert len(graph.calls) == calls  # the customer knows already

    def test_switched_off_messages_are_not_queued(self, wa, graph, goods, send_now):  # noqa: F811
        settings(ask_to_confirm=False, on_confirmed=False, on_ready=False)
        calls = len(graph.calls)
        order = move(send_now, new_order(goods, lines=[L(goods["samosa"].pk, D("1"))]), S.AWAITING, S.CONFIRMED, S.PREPARING, S.READY)
        assert len(graph.calls) == calls and messages(order) == []

    def test_whatsapp_not_connected(self, tenant_a, goods, send_now, graph):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        assert q.status == "skipped" and q.note == "WhatsApp is not connected. Call the customer."
        move(send_now, order, S.CONFIRMED, S.PREPARING)
        assert [m.kind for m in messages(order)] == [K.CONFIRM_REQUEST]  # only questions say why nothing was sent
        assert graph.calls == []

    def test_customer_without_phone_or_removed(self, wa, graph, goods, send_now):  # noqa: F811
        with schema_context("tenant_a"):
            nophone = Customer.objects.create(name="Ram Thapa")
        order = move(send_now, new_order(goods, customer=nophone), S.AWAITING)
        assert question(order).note == "The customer has no phone number. Call or tell them."
        walk_in = move(send_now, new_order(goods, customer=None), S.CONFIRMED)
        assert messages(walk_in) == []  # nobody to send to

    def test_the_order_moved_on_before_the_worker_sent(self, wa, graph, goods, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
        queued = []
        monkeypatch.setattr(tasks.send_order_message, "delay", lambda schema, pk: queued.append((schema, pk)))
        with django_capture_on_commit_callbacks(execute=True), schema_context("tenant_a"):
            order = services.change_status(new_order(goods), S.AWAITING)
            services.change_status(order, S.DRAFT)
        calls = len(graph.calls)
        for schema, pk in queued:
            tasks.send_order_message(schema, pk)
            tasks.send_order_message(schema, pk)  # twice: still sent at most once
        q = question(order)
        assert q.status == "skipped" and q.note == "The order moved on before the message was sent." and len(graph.calls) == calls

    def test_whatsapp_refuses_the_message(self, wa, graph, goods, send_now):  # noqa: F811
        graph.status, graph.body = 400, {"error": {"code": 131026, "message": "Message undeliverable"}}
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        assert q.status == "failed" and not q.is_open and "code 131026" in q.note
        assert "EAAG" not in q.note  # never the token

    def test_delivery_status_and_answer_on_the_order_page(self, wa, graph, goods, send_now):  # noqa: F811
        from tests.test_inbox import status_payload

        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        with schema_context("tenant_a"):
            provider_id = q.inbox_message.provider_message_id
        send_now(post_webhook, wa, status_payload(provider_id, "read"))
        assert notify.status_text(question(order)) == "Read · waiting for the answer"
        press(send_now, wa, q, "no")
        assert notify.status_text(question(order)) == "Read · answered No"

    def test_removing_the_customers_data(self, wa, graph, goods, send_now):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        q = question(order)
        with schema_context("tenant_a"):
            anonymise(goods["customer"])
            assert OrderMessage.objects.get(pk=q.pk).inbox_message is None
            assert not Message.objects.exists()
        assert notify.status_text(question(order)) == "Sent · waiting for the answer"


@pytest.mark.django_db
class TestPages:
    def test_api_lists_the_messages(self, wa, graph, goods, send_now, client_for, tenant_a):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        press(send_now, wa, question(order), "yes")
        staff = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        rows = staff.get(f"/api/orders/{order.pk}/").json()["messages"]
        assert [(r["kind"], r["label"], r["answer"]) for r in rows] == [
            ("confirm_request", "Please confirm", "yes"), ("confirmed", "Order confirmed", "")]
        assert rows[0]["result"] == "Sent · answered Yes" and rows[0]["via"] == "message"

    def test_order_admin_shows_the_messages(self, wa, graph, goods, send_now, client_for, tenant_a):  # noqa: F811
        order = move(send_now, new_order(goods), S.AWAITING)
        client = verified_staff_client(client_for, tenant_a, "ops@a.test", "operations_manager")
        page = client.get(f"/admin/orders/order/{order.pk}/change/").content.decode()
        assert "WhatsApp messages to the customer" in page and "Please confirm" in page and "waiting for the answer" in page

    def test_settings_page(self, client_for, tenant_a):
        manager = verified_staff_client(client_for, tenant_a, "ops@a.test", "operations_manager")  # Orders – Configure
        page = manager.get("/admin/orders/customermessagesettings/", follow=True).content.decode()
        assert "WhatsApp is not connected" in page and "order_final_price" in page and "Do you accept the final price?" in page
        url = "/admin/orders/customermessagesettings/1/change/"
        data = {"ask_to_confirm": "on", "on_final_price": "on", "template_language": "en_US", "template_confirm_request": "my_confirm",
                "template_confirmed": "", "template_final_price": "order_final_price", "template_ready": "order_ready",
                "template_out_for_delivery": "order_out_for_delivery", "template_cancelled": "order_cancelled"}
        assert manager.post(url, data).status_code == 302
        with schema_context("tenant_a"):
            s = CustomerMessageSettings.objects.get()
            assert (s.on_confirmed, s.template_language, s.template_confirm_request, s.template_confirmed) == (False, "en_US", "my_confirm", "")
        bad = manager.post(url, {**data, "template_ready": "Order Ready!", "template_language": "english"}).content.decode()
        assert "lower-case letters" in bad and "Use a language code such as en or en_US." in bad

    def test_settings_need_orders_configure(self, client_for, tenant_a):
        counter = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")  # Orders – View, no Configure
        with schema_context("tenant_a"):
            notify.current_settings()
        page = counter.get("/admin/orders/customermessagesettings/1/change/")
        assert page.status_code == 200 and 'name="template_ready"' not in page.content.decode()  # look only
        response = counter.post("/admin/orders/customermessagesettings/1/change/", {"template_language": "en"})
        assert response.status_code == 403
        with schema_context("tenant_a"):
            assert CustomerMessageSettings.objects.get().ask_to_confirm is True


@pytest.mark.django_db
class TestInbox:
    def test_template_parameters_have_no_new_lines(self, wa, graph):  # noqa: F811
        from apps.inbox import services as inbox

        with schema_context("tenant_a"):
            conversation = Conversation.objects.get()
            inbox.send_template(conversation, name="order_ready", params=["two\nlines   and\ttabs", ""])
        params = [p["text"] for p in sent(graph)["template"]["components"][0]["parameters"]]
        assert params == ["two lines and tabs", "-"]

    @pytest.mark.parametrize("buttons", [[], [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4")], [("a", "x" * 21)], [("", "Yes")]])
    def test_button_rules(self, wa, graph, buttons):  # noqa: F811
        from django.core.exceptions import ValidationError

        from apps.inbox import services as inbox

        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="1 to 3 buttons"):
                inbox.send_buttons(Conversation.objects.get(), "Hello", buttons)

    def test_buttons_need_the_24_hour_window(self, wa, graph):  # noqa: F811
        from django.core.exceptions import ValidationError

        from apps.inbox import services as inbox

        close_window()
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="24 hours"):
                inbox.send_buttons(Conversation.objects.get(), "Hello", [("a", "Yes")])

    def test_a_broken_listener_never_loses_the_message(self, wa, graph, monkeypatch):  # noqa: F811
        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(notify, "_answer", broken)
        assert post_webhook(wa, incoming("yes", msg_id="wamid.broken")).status_code == 200
        with schema_context("tenant_a"):
            assert Message.objects.filter(provider_message_id="wamid.broken").exists()


@pytest.mark.django_db
class TestCheckSystem:
    def test_stuck_failed_and_fine(self, wa, graph, goods, send_now, tenant_a):  # noqa: F811
        from apps.health import checks
        from apps.licensing.services import set_module_enabled

        with schema_context("tenant_a"):
            assert checks.check_order_messages()[0].message == "No messages in the last 24 hours."
        order = move(send_now, new_order(goods), S.AWAITING)
        with schema_context("tenant_a"):
            result = checks.check_order_messages()[0]
            assert (result.status, result.message) == ("ok", "1 message(s) sent in the last 24 hours.")
            OrderMessage.objects.create(order=order, kind=K.READY, status="skipped", note="no template")
            result = checks.check_order_messages()[0]
            assert result.status == "warning" and result.message.startswith("1 message(s) in the last 24 hours were not sent (1 sent)")
            late = OrderMessage.objects.create(order=order, kind=K.READY, status="queued")
            OrderMessage.objects.filter(pk=late.pk).update(created_at=timezone.now() - timedelta(minutes=11))
            result = checks.check_order_messages()[0]
            assert result.status == "failed" and "worker is running" in result.message
            assert "order_messages" in {r.code for r in checks.business_checks(tenant_a, live=False)}
        set_module_enabled(tenant_a, "orders", False)
        with schema_context("tenant_a"):
            assert checks.check_order_messages() == []
        set_module_enabled(tenant_a, "orders", True)


@pytest.mark.django_db
class TestEdges:
    def test_cancelled_before_the_worker_sent_the_ready_message(self, wa, graph, goods, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
        queued = []
        monkeypatch.setattr(tasks.send_order_message, "delay", lambda schema, pk: queued.append((schema, pk)))
        with django_capture_on_commit_callbacks(execute=True), schema_context("tenant_a"):
            order = new_order(goods, lines=[L(goods["samosa"].pk, D("2"))])
            for status in (S.CONFIRMED, S.PREPARING, S.READY):
                order = services.change_status(order, status)
            services.change_status(order, S.CANCELLED_CUSTOMER, note="Changed mind")
        calls = len(graph.calls)
        for schema, pk in queued:
            tasks.send_order_message(schema, pk)
        ready = question(order, K.READY)
        assert ready.status == "skipped" and ready.note == "The order was cancelled before the message was sent." and len(graph.calls) == calls

    def test_a_late_answer_reply_is_not_sent_after_24_hours(self, wa, graph, goods, send_now, monkeypatch):  # noqa: F811
        order = new_order(goods)
        queued = []
        monkeypatch.setattr(tasks.send_order_message, "delay", lambda schema, pk: queued.append(pk))
        with schema_context("tenant_a"):
            send_now(notify.queue_reply, order, "Thank you.")
        close_window()
        calls = len(graph.calls)
        with schema_context("tenant_a"):
            reply = notify.deliver(OrderMessage.objects.get(pk=queued[0]))
        assert reply.status == "skipped" and reply.note == "More than 24 hours since the customer's last message." and len(graph.calls) == calls

    def test_a_staff_note_never_looks_like_a_customer_answer(self, wa, graph, goods, send_now, client_for, tenant_a):  # noqa: F811
        from tests.conftest import make_user

        staff = make_user("tenant_a", "counter@a.test", staff=True)
        order = move(send_now, new_order(goods), S.AWAITING)
        with schema_context("tenant_a"):
            order = services.change_status(order, S.DRAFT, actor=staff, note="Customer said No on WhatsApp")
            assert not any("Call the customer" in w for w in services.warnings(order))


@pytest.mark.django_db
class TestMore:
    def test_deliver_twice_sends_once(self, wa, graph, goods, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
        queued = []
        monkeypatch.setattr(tasks.send_order_message, "delay", lambda schema, pk: queued.append(pk))
        with django_capture_on_commit_callbacks(execute=True), schema_context("tenant_a"):
            services.change_status(new_order(goods), S.AWAITING)
        calls = len(graph.calls)
        with schema_context("tenant_a"):
            message = OrderMessage.objects.get(pk=queued[0])
            notify.deliver(message)
            notify.deliver(message)  # the same object again, as a retried job would
        assert len(graph.calls) == calls + 1

    def test_meta_reports_it_could_not_deliver(self, wa, graph, goods, send_now):  # noqa: F811
        from tests.test_inbox import status_payload

        order = move(send_now, new_order(goods), S.AWAITING)
        with schema_context("tenant_a"):
            provider_id = question(order).inbox_message.provider_message_id
        send_now(post_webhook, wa, status_payload(provider_id, "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]))
        assert notify.status_text(question(order)) == "Not delivered: 131026 Message undeliverable · waiting for the answer"

    def test_template_button_answers_its_own_question(self, wa, graph, goods, send_now):  # noqa: F811
        close_window()
        first = move(send_now, new_order(goods), S.AWAITING)
        second = move(send_now, new_order(goods), S.AWAITING)
        press(send_now, wa, question(second), "yes", template=True)  # two open questions: only the button says which one
        assert (refreshed(first).status, refreshed(second).status) == (S.AWAITING, S.CONFIRMED)
