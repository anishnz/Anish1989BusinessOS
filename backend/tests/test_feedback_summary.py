"""
Star feedback after an order and the daily owner summary (task 2.7, D-155 to
D-158): when customers are asked (and when not), the list and the template,
the answers (list, button, typed), low ratings (what went wrong, Needs staff,
the comment), the summary's numbers and text, when it is sent, WhatsApp and
email, closed days, settings, admin pages and the scheduled jobs.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.ai import agent
from apps.ai.models import AIChat
from apps.catalog.models import Product
from apps.customers.models import ConsentRecord, Customer
from apps.customers.services import anonymise, set_marketing_consent
from apps.fulfilment.models import ClosedDay
from apps.inbox.models import Conversation
from apps.orders import feedback, services, tasks as order_tasks
from apps.orders.models import CustomerMessageSettings, Order, OrderFeedback
from apps.reports import summary, tasks as report_tasks
from apps.reports.models import DailySummary, DailySummarySettings
from tests.conftest import make_user
from tests.test_catalog import user_client
from tests.test_fulfilment import shop  # noqa: F401 (fixture)
from tests.test_inbox import WA_ID, connect_whatsapp, graph, incoming, post_webhook  # noqa: F401 (graph is a fixture)
from tests.test_order_messages import goods, send_now, wa  # noqa: F401 (fixtures)
from tests.test_orders import L
from tests.test_rbac import give_role, verified_staff_client

S = Order.Status
F = OrderFeedback.Status
D = Decimal


def completed(goods, hours_ago=2, customer="default", total_samosas=2):  # noqa: F811
    """A completed pickup order (samosas, nothing to weigh), completed `hours_ago` hours ago."""
    with schema_context("tenant_a"):
        order = services.create_order(lines=[L(goods["samosa"].pk, D(total_samosas))],
                                      customer=goods["customer"] if customer == "default" else customer)
        for status in (S.CONFIRMED, S.PREPARING, S.READY, S.COMPLETED):
            order = services.change_status(order, status)
        when = timezone.now() - timedelta(hours=hours_ago)
        Order.objects.filter(pk=order.pk).update(completed_at=when, confirmed_at=when - timedelta(hours=1))
        order.refresh_from_db()
        return order


def ask_all():
    with schema_context("tenant_a"):
        return feedback.ask_due()


def row_of(order) -> OrderFeedback:
    with schema_context("tenant_a"):
        return OrderFeedback.objects.get(order=order)


def press(run, client, row, stars, *, template=False, msg_id=None, wa_id=WA_ID):  # noqa: F811
    payload = feedback.payload(row, stars)
    if template:
        extra = {"button": {"payload": payload, "text": f"{stars}"}}
        body = incoming(wa_id=wa_id, msg_id=msg_id or f"wamid.fb.{row.pk}.{stars}", kind="button", extra=extra)
    else:
        extra = {"interactive": {"type": "list_reply", "list_reply": {"id": payload, "title": f"{stars} stars"}}}
        body = incoming(wa_id=wa_id, msg_id=msg_id or f"wamid.fb.{row.pk}.{stars}", kind="interactive", extra=extra)
    return run(post_webhook, client, body)


def write(run, client, text, msg_id):
    return run(post_webhook, client, incoming(text, msg_id=msg_id))


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAsking:
    def test_only_between_one_and_24_hours_after_completed(self, wa, graph, goods):  # noqa: F811
        too_soon = completed(goods, hours_ago=0.5)
        too_old = completed(goods, hours_ago=25)
        due = completed(goods, hours_ago=2)
        with schema_context("tenant_a"):
            assert [o.pk for o in feedback.due_orders()] == [due.pk]
        assert ask_all()[F.ASKED] == 1
        with schema_context("tenant_a"):
            assert not OrderFeedback.objects.filter(order__in=[too_soon, too_old]).exists()
            assert list(feedback.due_orders()) == []  # never asked twice
        assert ask_all()[F.ASKED] == 0

    def test_a_list_with_five_choices_inside_24_hours(self, wa, graph, goods):  # noqa: F811
        order = completed(goods)
        ask_all()
        row = row_of(order)
        assert (row.status, row.via, row.note) == (F.ASKED, "message", "")
        body = graph.calls[-1]["json"]
        assert body["to"] == WA_ID and body["interactive"]["type"] == "list"
        assert f"order #{order.number} from Tenant A Butchery" in body["interactive"]["body"]["text"]
        rows = body["interactive"]["action"]["sections"][0]["rows"]
        assert [r["id"] for r in rows] == [feedback.payload(row, n) for n in (5, 4, 3, 2, 1)]
        assert rows[0]["title"] == "5 ★★★★★ Excellent" and all(len(r["title"]) <= 24 for r in rows)

    def test_a_template_with_five_buttons_after_24_hours(self, wa, graph, goods):  # noqa: F811
        order = completed(goods)
        with schema_context("tenant_a"):
            Conversation.objects.update(last_inbound_at=timezone.now() - timedelta(hours=30))
        ask_all()
        row = row_of(order)
        assert (row.status, row.via) == (F.ASKED, "template")
        template = graph.calls[-1]["json"]["template"]
        assert template["name"] == "order_feedback"
        assert template["components"][0]["parameters"] == [{"type": "text", "text": str(order.number)}, {"type": "text", "text": "Tenant A Butchery"}]
        payloads = [c["parameters"][0]["payload"] for c in template["components"][1:]]
        assert payloads == [feedback.payload(row, n) for n in (5, 4, 3, 2, 1)]

    def test_no_template_name_means_not_asked_after_24_hours(self, wa, graph, goods):  # noqa: F811
        order = completed(goods)
        with schema_context("tenant_a"):
            Conversation.objects.update(last_inbound_at=timezone.now() - timedelta(hours=30))
            CustomerMessageSettings.objects.update_or_create(pk=1, defaults={"template_feedback": ""})
        calls = len(graph.calls)
        ask_all()
        assert row_of(order).status == F.SKIPPED and "no template" in row_of(order).note and len(graph.calls) == calls

    def test_who_is_not_asked(self, wa, graph, goods):  # noqa: F811
        walk_in = completed(goods, customer=None)
        with schema_context("tenant_a"):
            quiet = Customer.objects.create(name="Never Wrote", phone="+64211112222")
            stopped = Customer.objects.create(name="Said Stop", phone="+64211113333")
            Conversation.objects.create(external_id="64211113333", customer=stopped)
            set_marketing_consent(stopped, False, source=ConsentRecord.Source.STOP, channel="whatsapp", note="STOP")
        never_wrote = completed(goods, customer=quiet)
        stop = completed(goods, customer=stopped)
        with schema_context("tenant_a"):  # the STOP customer wrote once (STOP itself)
            from apps.inbox.models import Message

            Message.objects.create(conversation=Conversation.objects.get(external_id="64211113333"), direction="in", text="STOP", status="received")
        first = completed(goods)
        second = completed(goods)
        ask_all()
        assert row_of(walk_in).note == "No customer with a phone number."
        assert row_of(never_wrote).note == "The customer has never written to the business on WhatsApp."
        assert row_of(stop).note == "The customer sent STOP."
        statuses = sorted([row_of(first).status, row_of(second).status])
        assert statuses == [F.ASKED, F.SKIPPED]  # one question per customer per week
        skipped = first if row_of(first).status == F.SKIPPED else second
        assert row_of(skipped).note == "This customer was asked in the last 7 days."
        with schema_context("tenant_a"):
            OrderFeedback.objects.filter(status=F.ASKED).update(asked_at=timezone.now() - timedelta(days=3))
        still = completed(goods)
        ask_all()
        assert row_of(still).status == F.SKIPPED  # 3 days ago is still "this week"
        with schema_context("tenant_a"):
            OrderFeedback.objects.filter(status=F.ASKED).update(asked_at=timezone.now() - timedelta(days=8))
        third = completed(goods)
        ask_all()
        assert row_of(third).status == F.ASKED  # a week later: asked again

    def test_whatsapp_not_connected_and_switched_off(self, tenant_a, goods):  # noqa: F811
        order = completed(goods)
        ask_all()
        assert (row_of(order).status, row_of(order).note) == (F.SKIPPED, "WhatsApp is not connected.")
        other = completed(goods)
        with schema_context("tenant_a"):
            CustomerMessageSettings.objects.update_or_create(pk=1, defaults={"ask_feedback": False})
        assert ask_all() == {F.ASKED: 0, F.SKIPPED: 0, F.FAILED: 0}
        with schema_context("tenant_a"):
            assert not OrderFeedback.objects.filter(order=other).exists()

    def test_whatsapp_refuses(self, wa, graph, goods):  # noqa: F811
        order = completed(goods)
        graph.status, graph.body = 400, {"error": {"code": 131026, "message": "Message undeliverable"}}
        ask_all()
        row = row_of(order)
        assert row.status == F.FAILED and row.note.startswith("WhatsApp refused the message")


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAnswers:
    def test_five_stars_from_the_list(self, wa, graph, goods, send_now):  # noqa: F811
        order = completed(goods)
        ask_all()
        row = row_of(order)
        press(send_now, wa, row, 5)
        row = row_of(order)
        assert (row.status, row.stars, row.stars_text) == (F.ANSWERED, 5, "★★★★★")
        assert graph.calls[-1]["json"]["text"]["body"] == feedback.THANKS
        with schema_context("tenant_a"):
            assert not AIChat.objects.filter(handed_over_at__isnull=False).exists()
        press(send_now, wa, row, 1, msg_id="wamid.again")  # only the first answer counts
        assert row_of(order).stars == 5

    def test_button_of_the_template(self, wa, graph, goods, send_now):  # noqa: F811
        order = completed(goods)
        ask_all()
        press(send_now, wa, row_of(order), 4, template=True)
        assert row_of(order).stars == 4

    def test_low_rating_asks_why_and_needs_staff(self, tenant_a, wa, graph, goods, send_now, monkeypatch):  # noqa: F811
        from apps.ai import tasks as ai_tasks

        monkeypatch.setattr(ai_tasks.handover_email_task, "delay", lambda schema, pk: ai_tasks.handover_email_task(schema, pk))
        owner(tenant_a)  # Customers – Assign: gets the hand-over email
        order = completed(goods)
        ask_all()
        press(send_now, wa, row_of(order), 2)
        assert graph.calls[-1]["json"]["text"]["body"] == feedback.SORRY.format(n=order.number)
        with schema_context("tenant_a"):
            chat = AIChat.objects.get()
            assert chat.handover_reason == f"Low rating: 2 stars for order #{order.number}"
            assert [c.pk for c in agent.waiting_chats()] == [chat.pk]
        write(send_now, wa, "The meat was not fresh", "wamid.why")
        write(send_now, wa, "Also it was late", "wamid.more")  # only the first message is the comment
        assert row_of(order).comment == "The meat was not fresh"
        assert len(mail.outbox) == 1 and "Low rating" in mail.outbox[0].body  # managers are told (D-149)

    def test_typed_stars(self, wa, graph, goods, send_now):  # noqa: F811
        order = completed(goods)
        ask_all()
        write(send_now, wa, "4 stars", "wamid.typed")
        assert row_of(order).stars == 4

    def test_typed_stars_are_ignored_with_two_questions_or_a_long_text(self, wa, graph, goods, send_now):  # noqa: F811
        first, second = completed(goods), completed(goods)
        ask_all()
        with schema_context("tenant_a"):
            other = OrderFeedback.objects.get(status=F.SKIPPED)
            OrderFeedback.objects.filter(pk=other.pk).update(status=F.ASKED, asked_at=timezone.now(),
                                                             inbox_message=OrderFeedback.objects.get(status=F.ASKED).inbox_message)
        write(send_now, wa, "5", "wamid.five")
        with schema_context("tenant_a"):
            assert not OrderFeedback.objects.filter(stars__isnull=False).exists()  # which order? staff answer in the inbox
            OrderFeedback.objects.filter(pk=other.pk).update(status=F.SKIPPED)
        write(send_now, wa, "5 kg goat please", "wamid.order")
        assert row_of(first).stars is None and row_of(second).stars is None

    def test_buttons_only_work_in_their_own_chat(self, wa, graph, goods, send_now):  # noqa: F811
        order = completed(goods)
        ask_all()
        row = row_of(order)
        press(send_now, wa, row, 1, wa_id="64219998888", msg_id="wamid.stranger")
        assert row_of(order).stars is None
        row.token = "0" * 16
        press(send_now, wa, row, 1, msg_id="wamid.badtoken")
        assert row_of(order).stars is None

    def test_removing_the_customer_removes_the_comment(self, wa, graph, goods, send_now):  # noqa: F811
        order = completed(goods)
        ask_all()
        press(send_now, wa, row_of(order), 1)
        write(send_now, wa, "Bad", "wamid.bad")
        with schema_context("tenant_a"):
            anonymise(Customer.objects.get(pk=goods["customer"].pk))
        row = row_of(order)
        assert (row.stars, row.comment) == (1, "")  # the stars stay for the averages

    def test_numbers_order_page_and_dashboard(self, client_for, tenant_a, wa, graph, goods, send_now):  # noqa: F811
        orders = [completed(goods) for _ in range(3)]
        for n, (order, stars) in enumerate(zip(orders, (5, 4, 1))):
            with schema_context("tenant_a"):
                OrderFeedback.objects.create(order=order, customer=goods["customer"], status=F.ANSWERED, stars=stars,
                                             answered_at=timezone.now(), comment="Late" if stars == 1 else "")
        with schema_context("tenant_a"):
            day = timezone.localdate()
            start = timezone.make_aware(datetime.combine(day, time.min))
            stats = feedback.stats(start, start + timedelta(days=1))
        assert (stats["count"], stats["average"], stats["low"]) == (3, 3.3, 1)
        assert stats["low_orders"] == [{"order": orders[2].number, "order_id": orders[2].pk, "stars": 1, "comment": "Late"}]
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        detail = owner.get(f"/api/orders/{orders[2].pk}/").json()["feedback"]
        assert (detail["stars"], detail["comment"], detail["status"]) == (1, "Late", "answered")
        assert owner.get(f"/api/orders/{completed(goods).pk}/").json()["feedback"] is None
        assert owner.get("/api/reports/dashboard/").json()["feedback"]["count"] == 3


# ---------------------------------------------------------------------------
# The daily summary
# ---------------------------------------------------------------------------
def settings_(**changes) -> DailySummarySettings:
    with schema_context("tenant_a"):
        s = summary.current_settings()
        for key, value in changes.items():
            setattr(s, key, value)
        s.full_clean()
        s.save()
        return s


def owner(tenant):
    user = make_user(tenant.schema_name, "owner@a.test", staff=True)
    give_role(tenant.schema_name, user, "business_owner")
    return user


@pytest.mark.django_db
class TestSummaryNumbers:
    def test_figures_and_text(self, wa, graph, goods):  # noqa: F811
        done = [completed(goods, hours_ago=1, total_samosas=n) for n in (1, 2)]
        completed(goods, hours_ago=7 * 24 + 1, total_samosas=1)  # same weekday last week (and too old to ask for feedback)
        with schema_context("tenant_a"):
            Order.objects.filter(pk=done[0].pk).update(is_paid=True)
            open_order = services.change_status(services.create_order(lines=[L(goods["samosa"].pk, D("1"))], customer=goods["customer"],
                                                                       due_at=timezone.now() + timedelta(days=1)), S.CONFIRMED)
            Product.objects.filter(pk=goods["samosa"].pk).update(track_stock=True, stock_quantity=D("1"), low_stock_level=D("5"))
            OrderFeedback.objects.create(order=done[0], customer=goods["customer"], status=F.ANSWERED, stars=2, answered_at=timezone.now())
            now = timezone.now()
            f = summary.figures(timezone.localdate(now), now)
            body = summary.text(f, "Tenant A Butchery")
        assert (f["sales"], f["completed"], f["unpaid"], f["confirmed"]) == (D("45.00"), 2, D("30.00"), 3)
        assert f["top"] == [{"name": "Samosa 12 pack", "sales": D("45.00")}]
        assert (f["open"], f["open_tomorrow"], f["low_stock"]) == (1, 1, ["Samosa 12 pack (low)"])
        assert f["sales_before"] == D("15.00")  # the order completed on the same weekday last week
        assert f["feedback"]["low"] == 1 and open_order.status == S.CONFIRMED
        assert "Sales: $45.00 from 2 completed orders (not paid yet: $30.00)" in body
        assert "Top products: Samosa 12 pack $45.00" in body and "Still open: 1 order" in body
        assert f"Feedback: 1 answer, average 2.0 stars, 1 low (#{done[0].number} 2 stars)" in body
        params = summary.template_params(f, "Tenant A Butchery")
        assert len(params) == 11 and params[2] == "45.00" and all("\n" not in p for p in params)

    def test_quiet_day(self, tenant_a):
        with schema_context("tenant_a"):
            body = summary.text(summary.figures(timezone.localdate()), "Shop")
        assert "Sales: $0.00 from 0 completed orders" in body and "Top products: none" in body and "Feedback: none today" in body


@pytest.mark.django_db
class TestSummarySending:
    def test_sent_once_after_the_time_by_whatsapp_and_email(self, tenant_a, wa, graph, goods):  # noqa: F811
        owner(tenant_a)
        settings_(send_at=time(20, 0), whatsapp_numbers="021 555 0101, +64 21 555 0102")
        completed(goods, hours_ago=1)
        day = timezone.localdate()
        before = timezone.make_aware(datetime.combine(day, time(19, 59)))
        after = timezone.make_aware(datetime.combine(day, time(20, 1)))
        with schema_context("tenant_a"):
            assert summary.send_if_due(before) == "not due"
            calls = len(graph.calls)
            assert summary.send_if_due(after) == DailySummary.Status.SENT
            row = DailySummary.objects.get()
            assert summary.send_if_due(after + timedelta(minutes=5)) == "not due"  # once a day
        sent = graph.calls[calls:]
        assert [c["json"]["to"] for c in sent] == ["64215550101", "64215550102"]
        template = sent[0]["json"]["template"]
        assert template["name"] == "daily_summary" and len(template["components"][0]["parameters"]) == 11
        assert row.whatsapp_result == "Sent to 2 numbers." and row.email_result == "Emailed 1 person."
        assert mail.outbox[-1].to == ["owner@a.test"] and mail.outbox[-1].subject.startswith("Daily summary: $30.00 sales")
        assert mail.outbox[-1].body.startswith("Daily summary for Tenant A Butchery")

    def test_closed_day_without_orders_is_not_sent(self, tenant_a, shop):  # noqa: F811
        owner(tenant_a)
        day = timezone.localdate()
        with schema_context("tenant_a"):
            ClosedDay.objects.create(date=day, reason="Holiday")
            row = summary.make(day)
        assert (row.status, row.note) == (DailySummary.Status.SKIPPED, "Closed today and no orders, so nothing was sent.")
        assert mail.outbox == []

    def test_open_day_without_orders_is_sent(self, tenant_a, shop):  # noqa: F811
        owner(tenant_a)
        with schema_context("tenant_a"):
            row = summary.make(timezone.localdate())
        assert row.status == DailySummary.Status.SENT and len(mail.outbox) == 1  # the owner knows nothing happened

    def test_closed_day_with_an_order_is_sent(self, tenant_a, goods):  # noqa: F811
        owner(tenant_a)
        completed(goods, hours_ago=0)
        with schema_context("tenant_a"):
            ClosedDay.objects.get_or_create(date=timezone.localdate())
            assert summary.closed_day(timezone.localdate())
            assert summary.make(timezone.localdate()).status == DailySummary.Status.SENT

    def test_whatsapp_not_connected_is_partly_sent(self, tenant_a, shop):  # noqa: F811
        owner(tenant_a)
        settings_(whatsapp_numbers="021 555 0101")
        with schema_context("tenant_a"):
            row = summary.make(timezone.localdate())
        assert (row.status, row.whatsapp_result) == (DailySummary.Status.PARTLY, "WhatsApp is not connected.")

    def test_nobody_to_send_to(self, tenant_a, shop):  # noqa: F811
        with schema_context("tenant_a"):
            row = summary.make(timezone.localdate())
        assert (row.status, row.whatsapp_result, row.email_result) == (DailySummary.Status.SKIPPED, "No numbers set.", "No one to email.")

    def test_email_list_and_switches(self, tenant_a, shop):  # noqa: F811
        owner(tenant_a)
        settings_(email_to="boss@example.com, accounts@example.com", by_whatsapp=False)
        with schema_context("tenant_a"):
            row = summary.make(timezone.localdate())
        assert mail.outbox[-1].to == ["boss@example.com", "accounts@example.com"] and row.whatsapp_result == "Switched off."
        late = timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=1), time(23, 0)))
        with schema_context("tenant_a"):
            assert summary.due(late)
        settings_(enabled=False)
        with schema_context("tenant_a"):
            assert not summary.due(late)

    def test_default_email_goes_only_to_owners(self, client_for, tenant_a, shop):  # noqa: F811
        owner(tenant_a)
        for email, role in (("counter@a.test", "shop_staff"), ("acc@a.test", "accountant"), ("ops@a.test", "operations_manager")):
            give_role("tenant_a", make_user("tenant_a", email, staff=True), role)
        with schema_context("tenant_a"):
            assert summary.email_recipients(summary.current_settings()) == ["ops@a.test", "owner@a.test"]

    def test_settings_are_checked(self, tenant_a):
        s = settings_(whatsapp_numbers=" 021 555 0101 , 0215550101,", email_to=" a@b.nz ,a@b.nz")
        assert (s.whatsapp_numbers, s.email_to) == ("+64215550101", "a@b.nz")
        from django.core.exceptions import ValidationError

        for bad in ({"whatsapp_numbers": "12"}, {"email_to": "not-an-email"}, {"template_name": "Daily Summary"}, {"template_language": "english"}):
            with pytest.raises(ValidationError):
                settings_(**bad)


# ---------------------------------------------------------------------------
# Pages and scheduled jobs
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPagesAndJobs:
    def test_settings_page_and_test_send(self, client_for, tenant_a, shop):  # noqa: F811
        manager = verified_staff_client(client_for, tenant_a, "ops@a.test", "operations_manager")  # Orders – Configure
        page = manager.get("/admin/reports/dailysummarysettings/", follow=True).content.decode()
        assert "Daily summary for" in page and "daily_summary" in page and "Who gets the email now" in page and "ops@a.test" in page
        assert "Send a test now" in page
        assert "Daily summary for" in manager.get("/admin/reports/dailysummarysettings/send-test/").content.decode()
        response = manager.post("/admin/reports/dailysummarysettings/send-test/", follow=True)
        assert "Test sent." in response.content.decode() and mail.outbox[-1].subject.startswith("TEST Daily summary")
        assert mail.outbox[-1].body.startswith("TEST\nDaily summary for")
        with schema_context("tenant_a"):
            assert not DailySummary.objects.exists()  # a test does not count as today's summary

    def test_staff_without_configure(self, client_for, tenant_a):
        counter = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")  # Orders – View, no Reports
        with schema_context("tenant_a"):
            summary.current_settings()
        page = counter.get("/admin/reports/dailysummarysettings/1/change/")
        assert page.status_code == 200 and 'name="whatsapp_numbers"' not in page.content.decode() and "Send a test now" not in page.content.decode()
        assert counter.get("/admin/reports/dailysummarysettings/send-test/").status_code == 403
        assert counter.post("/admin/reports/dailysummarysettings/send-test/").status_code == 403
        assert counter.get("/admin/reports/dailysummary/").status_code == 403  # sales figures need Reports – View
        assert counter.get("/admin/orders/orderfeedback/").status_code == 200

    def test_sent_summaries_page(self, client_for, tenant_a):
        with schema_context("tenant_a"):
            DailySummary.objects.create(day=timezone.localdate(), status="sent", text="Daily summary for Shop\nSales: $1.00")
        manager = verified_staff_client(client_for, tenant_a, "ops@a.test", "operations_manager")
        assert manager.get("/admin/reports/dailysummary/").status_code == 200
        with schema_context("tenant_a"):
            pk = DailySummary.objects.get().pk
        assert "Sales: $1.00" in manager.get(f"/admin/reports/dailysummary/{pk}/change/").content.decode()

    def test_scheduled_jobs_run_in_every_business(self, tenant_a, tenant_b, goods, monkeypatch):  # noqa: F811
        late = timezone.localtime().replace(hour=23, minute=59)
        monkeypatch.setattr(summary.timezone, "now", lambda: late)
        result = report_tasks.daily_summaries()
        assert result["tenant_a"] in ("sent", "skipped") and result["tenant_b"] in ("sent", "skipped")
        for schema in ("tenant_a", "tenant_b"):
            with schema_context(schema):
                assert DailySummary.objects.filter(day=late.date()).count() == 1
        assert report_tasks.daily_summaries()["tenant_a"] == "not due"
        assert order_tasks.ask_feedback()["tenant_a"] == {F.ASKED: 0, F.SKIPPED: 0, F.FAILED: 0}

    def test_suspended_business_is_skipped(self, tenant_a, monkeypatch):
        import apps.licensing.services as licensing
        from apps.core import scheduled

        original = licensing.is_access_allowed
        monkeypatch.setattr(licensing, "is_access_allowed", lambda t: t.schema_name != "tenant_a" and original(t))
        assert scheduled.for_each_business(lambda: "ran")["tenant_a"] == "not run"

    def test_summary_needs_orders_and_reports(self, tenant_a, monkeypatch):
        from apps.licensing.services import set_module_enabled

        late = timezone.localtime().replace(hour=23, minute=59)
        monkeypatch.setattr(summary.timezone, "now", lambda: late)
        set_module_enabled(tenant_a, "reports", False)
        try:
            assert report_tasks.daily_summaries()["tenant_a"] == "not run"
            assert order_tasks.ask_feedback()["tenant_a"] != "not run"  # feedback needs only Orders
        finally:
            set_module_enabled(tenant_a, "reports", True)
