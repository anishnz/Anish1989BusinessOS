"""
Test data (task 1.18, D-126 to D-128): "Install test data" makes test
businesses with made-up Nepali data and a user for every role; "Remove test
data" deletes only test businesses, after the delete safety check. Only the
Super Admin can open the page.
"""
import pytest
from django.core.exceptions import ValidationError
from django_tenants.utils import schema_context

from apps.demo import data, services
from apps.rbac.defaults import TENANT_ROLES
from apps.tenants.models import Tenant
from tests.conftest import pass_delete_check
from tests.test_mfa_admin import platform_staff

PASSWORD = "test-only-shared-password-1"


@pytest.fixture
def demo_password(settings):
    settings.DEMO_PASSWORD = PASSWORD


@pytest.fixture
def super_admin(verified_admin_client, public_tenant):
    return verified_admin_client(public_tenant, "boss@platform.test")


@pytest.fixture
def butchery(db, demo_password):
    """One test business (making all six takes too long for a test)."""
    report = services.install(actor_email="boss@platform.test", only=["test_butchery"])
    assert report[0] == "Kathmandu Khasi Pasal: made"
    return Tenant.objects.get(schema_name="test_butchery")


@pytest.mark.django_db
class TestInstall:
    def test_the_business_and_its_licence(self, butchery):
        assert butchery.is_test and butchery.status == Tenant.Status.ACTIVE
        assert butchery.domains.get(is_primary=True).domain == "test-butchery.localhost"
        assert butchery.licence.plan_name == "Test (made-up data)" and butchery.licence.state() == "active"
        assert butchery.modules.filter(entitled=True, enabled=True).count() == butchery.modules.count()

    def test_a_user_for_every_role(self, butchery):
        from apps.accounts.models import User
        from apps.rbac.models import UserRole

        with schema_context("test_butchery"):
            users = {u.email: u for u in User.objects.all()}
            assert set(users) == {data.role_email(slug) for slug in TENANT_ROLES}
            shop = users["roleasshopstaff@anish1989.com.np"]
            assert shop.check_password(PASSWORD) and shop.mfa_exempt and shop.is_staff and shop.first_name and shop.last_name
            assert UserRole.objects.get(user=shop).role.slug == "shop_staff"
            assert not users["roleascustomer@anish1989.com.np"].is_staff  # no back-office permissions
            assert not any(u.is_superuser for u in users.values())

    def test_data_in_every_part(self, butchery):
        from apps.catalog.models import Product
        from apps.customers.models import Customer
        from apps.fulfilment.models import DeliveryArea
        from apps.inbox.models import Conversation, Message
        from apps.orders.models import Order
        from apps.setup.models import BusinessProfile, SetupProgress
        from apps.tickets.models import Ticket

        with schema_context("test_butchery"):
            profile = BusinessProfile.objects.get()
            assert (profile.address, profile.suburb, profile.city, profile.postcode) == ("2 White Street", "Auckland City", "Auckland", "1010")
            assert SetupProgress.objects.get().completed_at is not None
            assert Product.objects.count() == 10 and Product.objects.filter(is_available=False).count() == 1
            assert all(p.cost_price and p.search_terms and p.description and p.category_id for p in Product.objects.all())
            customers = list(Customer.objects.all())
            assert len(customers) == 16 and all(c.email.endswith("@example.com") and "1010" in c.address for c in customers)
            statuses = set(Order.objects.values_list("status", flat=True))
            assert {"draft", "awaiting_confirmation", "confirmed", "preparing", "ready", "out_for_delivery", "completed",
                    "cancelled_by_customer", "expired"} <= statuses
            assert Order.objects.filter(fulfilment="delivery", delivery_area__name="Auckland City").exists()
            assert Order.objects.filter(status="completed", is_paid=True).count() == 12
            assert DeliveryArea.objects.filter(is_active=True).count() == 2
            # 3 written chats (7 messages), plus the made-up order messages of task 2.3 in each customer's chat
            assert Message.objects.filter(conversation__last_message_preview__contains="(made-up test messages)").exists()
            from apps.ai.models import AIRun

            scripted = (Message.objects.exclude(text__contains="made-up test message").exclude(kind="interactive")
                        .exclude(pk__in=AIRun.objects.values("message")))  # the AI chats of task 2.4
            assert scripted.count() == 7 and scripted.values("conversation").distinct().count() == 3
            assert Ticket.objects.count() == 3

    def test_platform_test_accounts_keep_two_step_verification(self, butchery):
        from apps.accounts.models import User

        accounts = User.objects.filter(email__startswith="roleas")
        assert accounts.count() == 3 and not accounts.filter(mfa_exempt=True).exists()
        assert not accounts.filter(email="roleassuperadmin@anish1989.com.np").exists()  # never a test Super Admin

    def test_stock(self, butchery):
        """Task 2.2: counted products, a delivery before the orders, then waste, one low and one out of stock."""
        from apps.catalog import stock
        from apps.catalog.models import Product, StockMovement
        from apps.orders.models import Order

        with schema_context("test_butchery"):
            assert Product.objects.filter(track_stock=True).count() == 9
            assert [(r["name"], r["state"]) for r in stock.low_stock()] == [("Sukuti (dried meat) 250 g", "out"), ("Lamb chops", "low")]
            assert {"received", "order", "weight", "cancelled", "waste", "counted"} <= set(StockMovement.objects.values_list("reason", flat=True))
            took = set(Order.objects.filter(stock_taken=True).values_list("status", flat=True))
            assert took == {"confirmed", "preparing", "ready", "out_for_delivery", "completed"}
            assert not Order.objects.filter(status__in=["draft", "awaiting_confirmation", "expired", "cancelled_by_customer"], stock_taken=True).exists()

    def test_whatsapp_messages_are_made_up_and_never_sent(self, butchery):
        """Task 2.3: messages about the orders look sent (some read, some answered Yes), but WhatsApp is never connected."""
        from apps.inbox.models import Message
        from apps.orders.models import Order, OrderMessage
        from apps.vault.models import Connection

        with schema_context("test_butchery"):
            assert not Connection.objects.filter(provider="whatsapp_cloud").exists()
            rows = OrderMessage.objects.all()
            assert rows.exists() and not rows.exclude(status="sent").exists()
            assert {"confirm_request", "confirmed", "final_price", "ready", "out_for_delivery"} <= set(rows.values_list("kind", flat=True))
            assert rows.filter(kind="final_price", answer="yes").count() >= 1
            waiting = Order.objects.get(status="awaiting_confirmation")
            assert rows.get(order=waiting, kind="confirm_request").is_open
            assert all("(made-up test message, never sent)" in m.inbox_message.text for m in rows.select_related("inbox_message"))
            assert not Message.objects.exclude(provider_message_id=None).exists()  # nothing went to Meta

    def test_ai_assistant_is_set_up_but_never_answers(self, butchery):
        """Task 2.4: settings and two made-up AI chats; no AI key, so the AI never answers in a test business."""
        from apps.ai import agent
        from apps.ai.models import AIChat, AIRun
        from apps.vault.models import Connection

        with schema_context("test_butchery"):
            s = agent.current_settings()
            assert s.enabled and "halal" in s.instructions and not agent.is_on()
            assert not Connection.objects.filter(category="ai").exists()
            assert set(AIRun.objects.values_list("result", flat=True)) == {"answered", "handed_over"}
            reorder = AIRun.objects.get(tools="past_orders, reorder")  # task 2.5
            assert reorder.order.status == "draft" and reorder.order.channel == "whatsapp"
            assert [c.handover_reason for c in agent.waiting_chats()] == ["Customer complaint about a late order"]
            assert AIChat.objects.filter(order__status="awaiting_confirmation").exists()
            assert AIChat.objects.get(handed_over_at__isnull=False).handover_reason == "Customer complaint about a late order"
            assert all("made-up test message, never sent" in r.reply.text for r in AIRun.objects.select_related("reply"))

    def test_order_board_has_work_today(self, butchery):
        """Task 2.6: four open orders are moved to today, two of them late; the confirmed delivery stays tomorrow."""
        from apps.orders import board

        with schema_context("test_butchery"):
            both = board.board(tomorrow=True)
            assert {c["key"]: len(c["orders"]) for c in both["columns"]} == {"to_prepare": 2, "preparing": 1, "ready": 1, "out": 1}
            assert both["late"] == 2 and board.board()["count"] >= 2  # late orders are always on the board

    def test_feedback_and_summary_are_made_up_and_never_sent(self, butchery):
        """Task 2.7: star feedback (one low, with a comment), yesterday's summary; the summary email is off and no WhatsApp numbers."""
        from apps.orders.models import OrderFeedback
        from apps.reports import summary
        from apps.reports.models import DailySummary

        with schema_context("test_butchery"):
            stars = sorted(OrderFeedback.objects.exclude(stars=None).values_list("stars", flat=True))
            assert stars == [2, 4, 5, 5, 5] and OrderFeedback.objects.filter(status="skipped").count() == 1
            assert "made-up" in OrderFeedback.objects.get(stars=2).comment
            s = summary.current_settings()
            assert s.enabled and not s.by_email and s.whatsapp_numbers == ""
            row = DailySummary.objects.get()
            assert row.text.startswith("Daily summary for Kathmandu Khasi Pasal") and "never sent" in row.whatsapp_result

    def test_own_domain_is_made_up_and_never_live(self, butchery):
        """Task 2.8: a .example domain waiting for DNS (.example names never exist on the internet)."""
        from apps.tenants.models import CustomDomain

        row = CustomDomain.objects.get(tenant__schema_name="test_butchery")
        assert (row.name, row.status, row.domain) == ("test-butchery.example", "pending", None)

    def test_website_is_published_with_a_draft_change(self, butchery):
        """Task 2.9: version 1 is live; the draft has one change that is not published."""
        from apps.website import content

        with schema_context("test_butchery"):
            assert content.live().number == 1 and "Kathmandu Khasi Pasal" in content.live_content()["hero_heading"]
            assert content.unpublished_changes() and "not published" in content.draft_content()["tagline"]

    def test_running_again_changes_nothing(self, butchery):
        assert services.install(only=["test_butchery"]) == ["Kathmandu Khasi Pasal: already there (not changed)"]

    def test_needs_a_password(self, db, settings):
        settings.DEMO_PASSWORD = ""
        with pytest.raises(ValidationError, match="Set DEMO_PASSWORD"):
            services.install(only=["test_butchery"])
        settings.DEMO_PASSWORD = "short"
        with pytest.raises(ValidationError, match="at least 8"):
            services.install(only=["test_butchery"])

    def test_one_at_a_time(self, db, demo_password):
        from django.core.cache import cache

        cache.add(services.LOCK_KEY, 1, 60)
        with pytest.raises(ValidationError, match="right now"):
            services.install(only=["test_butchery"])
        with pytest.raises(ValidationError, match="right now"):
            services.remove()


@pytest.mark.django_db
class TestPage:
    def test_super_admin_only(self, client_for, public_tenant, super_admin):
        support = platform_staff(client_for, public_tenant, "support@platform.test", "platform_support_admin")
        assert support.get("/platform/test-data/").status_code == 403
        assert support.post("/platform/test-data/", {"action": "install"}).status_code == 403
        assert "Test data</a>" not in support.get("/admin/").content.decode()
        assert 'href="/platform/test-data/">Test data</a>' in super_admin.get("/admin/").content.decode()

    def test_install_button_needs_the_password(self, super_admin, settings):
        settings.DEMO_PASSWORD = ""
        page = super_admin.get("/platform/test-data/").content.decode()
        assert "DEMO_PASSWORD is not set" in page and 'value="Install test data" disabled' in page
        assert "Set DEMO_PASSWORD" in super_admin.post("/platform/test-data/", {"action": "install"}, follow=True).content.decode()

    def test_install_starts_in_the_background(self, super_admin, demo_password, monkeypatch, django_capture_on_commit_callbacks):
        from apps.demo import tasks

        started = []
        monkeypatch.setattr(tasks.install_test_data, "delay", lambda email: started.append(email))
        with django_capture_on_commit_callbacks(execute=True):
            response = super_admin.post("/platform/test-data/", {"action": "install"}, follow=True)
        assert started == ["boss@platform.test"] and "Installing test data" in response.content.decode()
        assert 'http-equiv="refresh"' in super_admin.get("/platform/test-data/").content.decode()

    def test_logins_are_listed_with_log_in_as(self, super_admin, butchery):
        page = super_admin.get("/platform/test-data/").content.decode()
        assert "roleasshopstaff@anish1989.com.np" in page and "Bishal Koirala" in page
        assert "/platform/login-as/test_butchery/" in page and "Platform test accounts" in page
        assert PASSWORD not in page

    def test_remove_needs_the_safety_check_and_keeps_real_businesses(self, super_admin, butchery, tenant_a, monkeypatch,
                                                                    django_capture_on_commit_callbacks):
        from apps.demo import tasks

        monkeypatch.setattr(tasks.remove_test_data, "delay", lambda email: services.remove(actor_email=email))
        confirm = super_admin.post("/platform/test-data/", {"action": "remove"})
        assert confirm.status_code == 200 and "Kathmandu Khasi Pasal" in confirm.content.decode()
        assert Tenant.objects.filter(schema_name="test_butchery").exists()
        with django_capture_on_commit_callbacks(execute=True):
            super_admin.post("/platform/test-data/", {"action": "remove", **pass_delete_check(super_admin, confirm)})
        assert not Tenant.objects.filter(schema_name="test_butchery").exists()
        assert Tenant.objects.filter(schema_name="tenant_a").exists()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'test_butchery'")
            assert cursor.fetchone() is None
        from apps.accounts.models import User

        assert not User.objects.filter(email__startswith="roleas").exists()

    def test_remove_never_touches_a_real_business(self, db, demo_password, tenant_a):
        assert services.remove() == []
        assert Tenant.objects.filter(schema_name="tenant_a").exists()
