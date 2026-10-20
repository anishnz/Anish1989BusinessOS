"""Simple dashboard (task 1.9)."""
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.licensing.services import set_module_enabled
from apps.orders import services
from apps.orders.models import Order
from apps.reports import dashboard
from tests.test_catalog import make_product, user_client
from tests.test_rbac import verified_staff_client

S = Order.Status
L = services.LineInput
TZ = timezone.get_default_timezone()


def local(day, hour=12):
    return timezone.make_aware(datetime.combine(day, time(hour)), TZ)


@pytest.fixture
def goods(tenant_a):
    return {
        "goat": make_product(name="Goat curry cut", sku="G", unit="kg", price=Decimal("23.00"), min_quantity=Decimal("0.5"), quantity_step=Decimal("0.5"), search_terms=""),
        "samosa": make_product(name="Samosa", sku="S", unit="pack", price=Decimal("15.00"), search_terms=""),
    }


def completed(goods, *, when, lines=None, paid=True, weight=None):
    """Create an order and take it to Completed, with completed_at = when."""
    lines = lines or [L(goods["samosa"].pk, Decimal("2"))]
    with schema_context("tenant_a"):
        order = services.create_order(lines=lines)
        services.change_status(order, S.CONFIRMED)
        services.change_status(order, S.PREPARING)
        kg = {l.pk: (weight or l.quantity) for l in order.lines.all() if l.unit == "kg"}
        if kg:
            order = services.set_weights(order, kg)
        if order.total != order.estimated_total:
            services.change_status(order, S.FINAL_SENT)
            services.change_status(order, S.FINAL_ACCEPTED)
        services.change_status(order, S.READY)
        if paid:
            services.set_paid(order, True, method="cash")
        services.change_status(order, S.COMPLETED)
        Order.objects.filter(pk=order.pk).update(completed_at=when, confirmed_at=when)
        order.refresh_from_db()
        return order


def summary(day=None):
    with schema_context("tenant_a"):
        return dashboard.summary(day, include_inbox=True)


@pytest.mark.django_db
class TestNumbers:
    def test_sales_today_and_comparison_with_last_week(self, goods):
        today = timezone.localdate()
        completed(goods, when=local(today, 9))  # 30.00
        completed(goods, when=local(today, 15), lines=[L(goods["goat"].pk, Decimal("1"))], weight=Decimal("1.08"), paid=False)  # 24.84
        completed(goods, when=local(today - timedelta(days=7)))  # 30.00 last week
        completed(goods, when=local(today - timedelta(days=1)))  # yesterday: not today
        data = summary()
        assert data["sales"]["total"] == Decimal("54.84")
        assert data["sales"]["count"] == 2 and data["sales"]["average"] == Decimal("27.42")
        assert data["sales"]["unpaid"] == Decimal("24.84")
        assert data["sales"]["gst"] == Decimal("3.91") + Decimal("3.24")
        assert data["sales"]["change"] == {"before": Decimal("30.00"), "difference": Decimal("24.84"), "percent": 83}
        assert data["orders"]["count"] == 2

    def test_cancelled_and_open_orders_are_not_sales(self, goods):
        with schema_context("tenant_a"):
            open_order = services.create_order(lines=[L(goods["samosa"].pk, Decimal("1"))])
            services.change_status(open_order, S.CONFIRMED)
            cancelled = services.create_order(lines=[L(goods["samosa"].pk, Decimal("1"))])
            services.change_status(cancelled, S.CONFIRMED)
            services.change_status(cancelled, S.CANCELLED_SHOP, note="no stock")
        data = summary()
        assert data["sales"]["total"] == Decimal("0.00") and data["sales"]["average"] == Decimal("0.00")
        assert data["orders"]["count"] == 1  # confirmed and not cancelled
        assert {a["status"]: a["count"] for a in data["attention"]}[S.CONFIRMED] == 1

    def test_days_follow_new_zealand_time(self, goods):
        today = timezone.localdate()
        # 11:30pm NZ time yesterday is still "yesterday", even though it is the same UTC day as this morning.
        completed(goods, when=local(today - timedelta(days=1), 23) + timedelta(minutes=30))
        completed(goods, when=local(today, 0) + timedelta(minutes=30))
        data = summary()
        assert data["sales"]["count"] == 1
        week = {w["date"]: w["total"] for w in data["week"]}
        assert week[(today - timedelta(days=1)).isoformat()] == Decimal("30.00")
        assert week[today.isoformat()] == Decimal("30.00")

    def test_seven_days_and_top_products(self, goods):
        today = timezone.localdate()
        completed(goods, when=local(today - timedelta(days=6)), lines=[L(goods["goat"].pk, Decimal("2"))])  # 46.00
        completed(goods, when=local(today - timedelta(days=3)))  # samosa 30.00
        completed(goods, when=local(today - timedelta(days=8)), lines=[L(goods["goat"].pk, Decimal("10"))])  # too old
        data = summary()
        assert [w["date"] for w in data["week"]] == [(today - timedelta(days=d)).isoformat() for d in range(6, -1, -1)]
        assert data["week"][-1]["is_today"] and data["week_total"] == Decimal("76.00")
        top = data["top_products"]
        assert [(t["name"], t["sales"], t["quantity"], t["orders"]) for t in top] == [
            ("Goat curry cut", Decimal("46.00"), "2", 1), ("Samosa", Decimal("30.00"), "2", 1),
        ]

    def test_large_quantities_show_as_plain_numbers(self, goods):
        today = timezone.localdate()
        completed(goods, when=local(today), lines=[L(goods["samosa"].pk, Decimal("20"))])
        assert summary()["top_products"][0]["quantity"] == "20"

    def test_pickups_due_and_unread_chats(self, goods):
        from apps.inbox.models import Conversation

        with schema_context("tenant_a"):
            order = services.create_order(lines=[L(goods["samosa"].pk, Decimal("1"))], pickup_at=local(timezone.localdate(), 17))
            services.change_status(order, S.CONFIRMED)
            Conversation.objects.create(external_id="64211234567", unread_count=3)
            Conversation.objects.create(external_id="64211234568", unread_count=0)
        data = summary()
        assert data["pickups_due_today"] == 1 and data["unread_conversations"] == 1

    def test_another_day(self, goods):
        day = timezone.localdate() - timedelta(days=2)
        completed(goods, when=local(day))
        assert summary(day)["sales"]["total"] == Decimal("30.00")
        assert summary()["sales"]["total"] == Decimal("0.00")


@pytest.mark.django_db
class TestAccess:
    def test_api_needs_reports_permission(self, client_for, tenant_a, goods):
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        body = owner.get("/api/reports/dashboard/").json()
        assert body["sales"]["total"] == "0.00" and "unread_conversations" in body
        assert owner.get("/api/reports/dashboard/?date=bad").status_code == 400
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")  # no reports.view
        assert counter.get("/api/reports/dashboard/").status_code == 403
        ops = user_client(client_for, tenant_a, "ops@a.test", "operations_manager")  # reports.view, crm.view
        assert ops.get("/api/reports/dashboard/").status_code == 200

    def test_reports_module_switched_off(self, client_for, tenant_a, goods):
        owner = user_client(client_for, tenant_a, "owner@a.test", "business_owner")
        set_module_enabled(tenant_a, "reports", False)
        assert owner.get("/api/reports/dashboard/").status_code == 403
        set_module_enabled(tenant_a, "reports", True)

    def test_isolation(self, client_for, tenant_a, tenant_b, goods):
        completed(goods, when=local(timezone.localdate()))
        other = user_client(client_for, tenant_b, "owner@b.test", "business_owner")
        assert other.get("/api/reports/dashboard/").json()["sales"]["total"] == "0.00"

    def test_page(self, client_for, tenant_a, goods):
        completed(goods, when=local(timezone.localdate()))
        client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert "Dashboard" in client.get("/admin/").content.decode()
        page = client.get("/dashboard/").content.decode()
        assert "$30.00" in page and "Sales, last 7 days" in page and "Samosa" in page and "Show as a table" in page
        assert client.get("/dashboard/?date=2020-01-01").status_code == 200
        staff = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        assert staff.get("/dashboard/").status_code == 403

    def test_not_on_the_platform_site(self, verified_admin_client, public_tenant):
        client = verified_admin_client(public_tenant)
        assert client.get("/dashboard/").status_code == 404
        assert client.get("/api/reports/dashboard/").status_code == 404
