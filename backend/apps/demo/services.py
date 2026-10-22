"""
Install and remove test data (task 1.18, D-126 to D-128).

install() creates the six test businesses in apps/demo/data.py, each with:
users for every role (roleas<role>@anish1989.com.np, password DEMO_PASSWORD,
two-step verification switched off as test accounts), business details,
pickup and delivery settings, products, customers, orders in every step,
WhatsApp conversations and tickets, stock for the products that are
counted (task 2.2), and made-up WhatsApp messages about the orders (task
2.3; never sent: test businesses never connect WhatsApp), and AI assistant
settings with two made-up AI chats (task 2.4; no AI key is saved). It also adds test accounts for the
platform roles except Super Admin; those keep two-step verification, because
platform accounts can see every business.

remove() deletes only businesses marked as test businesses (and their
schemas), and the platform test accounts.

Only the platform's Super Admin may do either (see views.py). Nothing here
sends email or WhatsApp messages.
"""
from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit, platform_actor
from apps.tenants.models import Tenant

from . import data

PROGRESS_KEY = "demo:progress"
LOCK_KEY = "demo:lock"
MFA_REASON = "Test account (made-up data, task 1.18)"
MFA_BY = "Install test data"


def password() -> str:
    value = getattr(settings, "DEMO_PASSWORD", "") or ""
    if len(value) < 8:
        raise ValidationError("Set DEMO_PASSWORD (at least 8 characters) in the server's .env file first, then restart.")
    return value


def test_businesses():
    return Tenant.objects.filter(is_test=True).order_by("schema_name")


def progress() -> dict | None:
    return cache.get(PROGRESS_KEY)


def _progress(state: str, message: str, done: int = 0, total: int = 0) -> None:
    cache.set(PROGRESS_KEY, {"state": state, "message": message, "done": done, "total": total, "at": timezone.now().isoformat()}, 3600)


def accounts(schema: str) -> list[dict]:
    """The test logins of one test business, in role order, for the Super Admin's list."""
    from apps.accounts.models import User
    from apps.rbac.defaults import TENANT_ROLES
    from apps.rbac.models import UserRole

    tenant = test_businesses().filter(schema_name=schema).first()
    if tenant is None:
        return []
    order = {data.role_email(slug): n for n, slug in enumerate(TENANT_ROLES)}
    rows = []
    with schema_context(tenant.schema_name):
        roles = {}
        for ur in UserRole.objects.select_related("role"):
            roles.setdefault(ur.user_id, []).append(ur.role.name)
        for user in User.objects.filter(email__endswith="@" + data.EMAIL_DOMAIN):
            rows.append({"tenant": tenant, "user_id": user.pk, "email": user.email, "name": user.get_full_name(),
                         "roles": ", ".join(sorted(roles.get(user.pk, []))), "staff": user.is_staff})
    return sorted(rows, key=lambda r: (order.get(r["email"], 999), r["email"]))


def platform_accounts() -> list[dict]:
    """The platform test accounts (they log in normally, with two-step verification)."""
    from apps.accounts.models import User
    from apps.rbac.models import UserRole

    with schema_context(get_public_schema_name()):
        users = list(User.objects.filter(email__startswith="roleas", email__endswith="@" + data.EMAIL_DOMAIN).order_by("email"))
        roles = {}
        for ur in UserRole.objects.filter(user__in=users).select_related("role"):
            roles.setdefault(ur.user_id, []).append(ur.role.name)
    return [{"email": u.email, "name": u.get_full_name(), "roles": ", ".join(sorted(roles.get(u.pk, [])))} for u in users]


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
def install(*, actor_email: str = "", only: list[str] | None = None) -> list[str]:
    """Create the test businesses that do not exist yet. Returns one line per business."""
    pw = password()
    specs = [s for s in data.BUSINESSES if not only or s["slug"] in only]
    if not cache.add(LOCK_KEY, 1, 3600):
        raise ValidationError("Test data is being installed or removed right now. Wait until it has finished.")
    report = []
    try:
        for n, spec in enumerate(specs):
            _progress("running", f"Making {spec['name']} ({n + 1} of {len(specs)})", n, len(specs))
            if Tenant.objects.filter(schema_name=spec["slug"]).exists():
                report.append(f"{spec['name']}: already there (not changed)")
                continue
            tenant = _create_business(spec)
            with schema_context(spec["slug"]), platform_actor(actor_email or MFA_BY):
                _fill_business(spec, data.BUSINESSES.index(spec), pw)
            report.append(f"{spec['name']}: made")
        made = _platform_accounts(pw)
        if made:
            report.append(f"Platform test accounts: {made} made")
        audit("test_data.installed", actor=None, metadata={"by": actor_email, "result": report})
        _progress("done", "Test data is ready.", len(specs), len(specs))
        return report
    except Exception as exc:
        _progress("failed", f"Stopped: {exc}")
        raise
    finally:
        cache.delete(LOCK_KEY)


def _create_business(spec: dict) -> Tenant:
    from apps.licensing.models import Licence
    from apps.licensing.services import clear_cache, set_entitlements
    from apps.licensing.templates_catalogue import OPTIONAL_MODULES
    from apps.tenants.services import create_tenant

    tenant = create_tenant(spec["name"], spec["slug"], spec["industry"])
    Tenant.objects.filter(pk=tenant.pk).update(is_test=True, status=Tenant.Status.ACTIVE)
    tenant.refresh_from_db()
    Licence.objects.filter(tenant=tenant).update(plan_name="Test (made-up data)", trial_ends_at=None, ends_at=None, max_users=60,
                                                 max_websites=3, notes="Made by Install test data. Remove it with Remove test data.")
    set_entitlements(tenant, set(OPTIONAL_MODULES))  # every module, so every page can be tried
    clear_cache(tenant)
    return tenant


def _platform_accounts(pw: str) -> int:
    from apps.accounts.models import User
    from apps.rbac.models import Role, UserRole

    made = 0
    with schema_context(get_public_schema_name()):
        for n, role in enumerate(Role.objects.filter(full_access=False).order_by("slug")):
            email = data.role_email(role.slug)
            if User.objects.filter(email=email).exists():
                continue
            first, last = data.PEOPLE[(n + 20) % len(data.PEOPLE)]
            user = User.objects.create_user(email=email, password=pw, first_name=first, last_name=last, is_staff=True)
            UserRole.objects.create(user=user, role=role)
            made += 1
    return made


def _local(day, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute)).replace(tzinfo=timezone.get_current_timezone())


@transaction.atomic
def _fill_business(spec: dict, index: int, pw: str) -> None:
    users = _users(index, pw)
    owner = users.get("business_owner")
    _profile(spec, owner)
    _fulfilment()
    products = _products(spec, owner)
    _stock_received(spec, products, owner)
    customers = _customers(index)
    _orders(spec, products, customers, users)
    _stock_counted(spec, products, owner)
    _conversations(customers, users)
    _order_messages()
    _ai_chats(spec, customers)
    _board_today()
    _tickets(users)


def _users(index: int, pw: str) -> dict:
    from apps.accounts.models import User
    from apps.rbac.models import Role, UserRole
    from apps.rbac.defaults import TENANT_ROLES

    people = data.PEOPLE[index * 5:] + data.PEOPLE[:index * 5]
    now = timezone.now()
    users = {}
    for n, slug in enumerate(TENANT_ROLES):
        role = Role.objects.filter(slug=slug).first()
        if role is None:
            continue
        first, last = people[n % len(people)]
        back_office = role.full_access or role.permissions.exists()
        user = User.objects.create_user(
            email=data.role_email(slug), password=pw, first_name=first, last_name=last, phone=f"+64220{index}{n:05d}",
            is_staff=back_office, mfa_exempt=True, mfa_exempt_reason=MFA_REASON, mfa_exempt_by=MFA_BY, mfa_exempt_at=now,
        )
        UserRole.objects.create(user=user, role=role)
        users[slug] = user
    return users


def _profile(spec: dict, owner) -> None:
    from apps.setup.models import BusinessProfile, SetupProgress

    label = spec["slug"].replace("_", "-")
    BusinessProfile.objects.update_or_create(pk=1, defaults={
        "trading_name": spec["name"], "phone": "+64 9 000 1010", "email": f"hello@{label}.example.com",
        "address": data.ADDRESS["address"], "suburb": data.ADDRESS["suburb"], "city": data.ADDRESS["city"],
        "postcode": data.ADDRESS["postcode"], "gst_number": "123-456-789", "website": f"https://{label}.example.com",
        "updated_by_email": owner.email if owner else "",
    })
    now = timezone.now()
    SetupProgress.objects.update_or_create(pk=1, defaults={
        "started_at": now, "business_done_at": now, "backups_skipped_at": now, "keys_seen_at": now, "completed_at": now,
        "completed_by_email": owner.email if owner else "",
    })


def _fulfilment() -> None:
    from apps.fulfilment import services as fulfilment
    from apps.fulfilment.models import ClosedDay, DeliveryArea, OpeningHours

    s = fulfilment.current_settings()
    s.pickup_capacity, s.delivery_enabled, s.delivery_capacity, s.lead_minutes, s.days_ahead = 4, True, 3, 60, 7
    s.save()
    for weekday in range(6):
        OpeningHours.objects.create(settings=s, kind="pickup", weekday=weekday, opens=time(9), closes=time(12))
        OpeningHours.objects.create(settings=s, kind="pickup", weekday=weekday, opens=time(13), closes=time(17, 30))
        OpeningHours.objects.create(settings=s, kind="delivery", weekday=weekday, opens=time(16), closes=time(19))
    OpeningHours.objects.create(settings=s, kind="pickup", weekday=6, opens=time(10), closes=time(14))
    DeliveryArea.objects.create(name="Auckland City", postcodes="1010, 1011, 1021, 1023, 1024",
                                suburbs="Auckland City, Auckland CBD, Grafton, Newton, Mount Eden, Kingsland",
                                fee=Decimal("6.00"), minimum_order=Decimal("30"), free_over=Decimal("120"), sort_order=1)
    DeliveryArea.objects.create(name="Mount Roskill and Three Kings", postcodes="1041, 1042", suburbs="Mount Roskill, Three Kings, Hillsborough",
                                fee=Decimal("9.00"), minimum_order=Decimal("40"), sort_order=2)
    DeliveryArea.objects.create(name="North Shore (paused)", postcodes="0620, 0622", suburbs="Takapuna, Milford",
                                fee=Decimal("14.00"), minimum_order=Decimal("60"), is_active=False, sort_order=3)
    year = timezone.localdate().year
    for day, reason in ((datetime(year, 12, 25).date(), "Christmas Day"), (datetime(year, 12, 26).date(), "Boxing Day"),
                        (datetime(year + 1, 1, 1).date(), "New Year's Day")):
        ClosedDay.objects.get_or_create(date=day, defaults={"reason": reason})


def _products(spec: dict, owner) -> list:
    from apps.catalog.models import Category, Product

    categories = [Category.objects.create(name=name, sort_order=n * 10) for n, name in enumerate(spec["categories"])]
    products = []
    for n, (name, cat, unit, price, cost, minimum, step, terms, description) in enumerate(spec["products"]):
        products.append(Product.objects.create(
            sku=f"{spec['slug'][5:8].upper()}-{n + 1:03d}", name=name, category=categories[cat], unit=unit, price=price, cost_price=cost,
            min_quantity=minimum, quantity_step=step, search_terms=terms, description=description or f"{name}. Made-up test product.",
            gst_applies=True, is_available=n != len(spec["products"]) - 1 or len(spec["products"]) < 5, created_by=owner,
        ))
    return products


def _stock_received(spec: dict, products: list, owner) -> None:
    """Count stock for the products in spec["stock"] and record a delivery, before the orders take some (task 2.2)."""
    from apps.catalog import stock
    from apps.catalog.models import Product

    for n, (received, warn_at) in spec.get("stock", {}).items():
        product = products[n]
        Product.objects.filter(pk=product.pk).update(track_stock=True, low_stock_level=warn_at)
        stock.adjust(product, reason="received", quantity=received, note="Delivery from the supplier (made-up)", actor=owner)


def _stock_counted(spec: dict, products: list, owner) -> None:
    """After the orders: a stock count, some waste, one product low and one out of stock."""
    from apps.catalog import stock

    counted = list(spec.get("stock", {}))
    if not counted:
        return
    first = products[counted[0]]
    stock.adjust(first, reason="waste", quantity=first.min_quantity, note="Out of date (made-up)", actor=owner)
    if "stock_low" in spec:
        stock.adjust(products[spec["stock_low"]], reason="counted", quantity=spec["stock"][spec["stock_low"]][1],
                     note="Weekly stock count", actor=owner)
    if "stock_out" in spec:
        stock.adjust(products[spec["stock_out"]], reason="counted", quantity=0, note="Sold out", actor=owner)


def _customers(index: int) -> list:
    from apps.customers.models import ConsentRecord, Customer

    found = []
    now = timezone.now()
    for n, (first, last) in enumerate(data.CUSTOMERS):
        consent = n % 3 != 2
        customer = Customer.objects.create(
            name=f"{first} {last}", phone=f"+64210{index}{n:05d}", email=f"{first.split()[0].lower()}.{last.split()[-1].lower()}@example.com",
            address=f"Unit {n + 1}, {data.FULL_ADDRESS}", notes=data.CUSTOMER_NOTES[n % len(data.CUSTOMER_NOTES)],
            tags=data.CUSTOMER_TAGS[n % len(data.CUSTOMER_TAGS)], preferred_language="Nepali" if n % 2 == 0 else "English",
            source=[Customer.Source.WHATSAPP, Customer.Source.WALK_IN, Customer.Source.MANUAL, Customer.Source.WEBSITE][n % 4],
            marketing_consent=consent, marketing_consent_at=now if consent else None,
        )
        ConsentRecord.objects.create(customer=customer, channel="all", given=consent,
                                     source=ConsentRecord.Source.WHATSAPP if consent else ConsentRecord.Source.STAFF,
                                     note="Said yes on WhatsApp" if consent else "Did not want offers")
        found.append(customer)
    return found


def _orders(spec: dict, products: list, customers: list, users: dict) -> None:
    """Orders in every step: completed in the last days (for the dashboard), open today and tomorrow, cancelled."""
    from apps.orders import services as orders
    from apps.orders.models import Order, OrderEvent

    S = Order.Status
    staff = users.get("shop_staff") or users.get("business_owner")
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    by_kg = [p for p in products if p.unit == "kg" and p.is_available]
    others = [p for p in products if p.unit != "kg" and p.is_available]

    def lines(n: int):
        chosen = (by_kg[n % len(by_kg):] + by_kg)[:1] if by_kg else []
        chosen += (others[n % len(others):] + others)[:2 if by_kg else 3] if others else []
        return [orders.LineInput(p.pk, p.min_quantity * (1 + (n % 3)) if p.unit == "kg" else p.min_quantity + (n % 2) * p.quantity_step,
                                 "Cut small please" if p.unit == "kg" and n % 2 else "") for p in chosen]

    def delivery_details(n: int) -> dict:
        return {"fulfilment": "delivery", "delivery_address": f"Unit {n + 1}, 2 White Street", "delivery_suburb": "Auckland City",
                "delivery_postcode": "1010"}

    def weigh_and_ready(order):
        if by_kg:
            weights = {line.pk: line.quantity + Decimal("0.040") for line in order.lines.all() if line.unit == "kg"}
            if weights:
                order = orders.set_weights(order, weights, actor=staff)
        if order.total != order.estimated_total:
            order = orders.change_status(order, S.FINAL_SENT, actor=staff, note="Real weight 40 g more")
            order = orders.change_status(order, S.FINAL_ACCEPTED, actor=staff, note="Customer pressed Yes on WhatsApp (made-up)")
        return orders.change_status(order, S.READY, actor=staff)

    # Completed orders over the last 6 days (sales chart and top products on the dashboard)
    for n in range(12):
        delivery = n % 3 == 0
        day = today - timedelta(days=n % 6)
        details = delivery_details(n) if delivery else {"fulfilment": "pickup"}
        order = orders.create_order(lines=lines(n), customer=customers[n % len(customers)], channel=["whatsapp", "counter", "phone"][n % 3],
                                    notes="Made-up test order", actor=staff, due_at=_local(tomorrow, 16 if delivery else 10), **details)
        order = orders.change_status(order, S.CONFIRMED, actor=staff)
        order = orders.change_status(order, S.PREPARING, actor=staff)
        order = weigh_and_ready(order)
        if delivery:
            order = orders.change_status(order, S.OUT_FOR_DELIVERY, actor=staff)
        order = orders.set_paid(order, True, method=["cash", "card", "bank_transfer"][n % 3], actor=staff)
        order = orders.change_status(order, S.COMPLETED, actor=staff)
        when = _local(day, 10 + n % 7, 15)
        Order.objects.filter(pk=order.pk).update(created_at=when - timedelta(hours=3), confirmed_at=when - timedelta(hours=2),
                                                 completed_at=when, paid_at=when, due_at=when, due_until=None)
        OrderEvent.objects.filter(order=order).update(at=when - timedelta(hours=1))

    # Open orders for today and tomorrow, one in each step
    plan = [
        ("draft", {"fulfilment": "pickup", "due_at": _local(tomorrow, 11)}),
        ("awaiting_confirmation", {"fulfilment": "pickup", "due_at": _local(tomorrow, 9, 30)}),
        ("confirmed", delivery_details(20) | {"due_at": _local(tomorrow, 17)}),
        ("confirmed", {"fulfilment": "pickup", "due_at": _local(tomorrow, 10)}),
        ("preparing", {"fulfilment": "pickup", "due_at": _local(tomorrow, 13)}),
        ("ready", {"fulfilment": "pickup", "due_at": _local(tomorrow, 14)}),
        ("out_for_delivery", delivery_details(21) | {"due_at": _local(tomorrow, 16)}),
        ("cancelled_by_customer", {"fulfilment": "pickup", "due_at": _local(tomorrow, 15)}),
        ("expired", {"fulfilment": "pickup", "due_at": _local(tomorrow, 15, 30)}),
    ]
    for n, (target, details) in enumerate(plan):
        order = orders.create_order(lines=lines(n + 3), customer=customers[(n + 5) % len(customers)], channel=["whatsapp", "phone"][n % 2],
                                    notes=["", "Please add extra achar", "Call when ready"][n % 3], actor=staff, **details)
        if target == "draft":
            continue
        if target in ("awaiting_confirmation", "expired"):
            order = orders.change_status(order, S.AWAITING, actor=staff)
            if target == "expired":
                order = orders.change_status(order, S.EXPIRED, actor=None, note="Not confirmed within 60 minutes")
            continue
        if target == "cancelled_by_customer":
            orders.change_status(order, S.CONFIRMED, actor=staff)
            orders.change_status(order, S.CANCELLED_CUSTOMER, actor=staff, note="Customer is travelling to Nepal")
            continue
        order = orders.change_status(order, S.CONFIRMED, actor=staff)
        if target == "confirmed":
            continue
        order = orders.change_status(order, S.PREPARING, actor=staff)
        if target == "preparing":
            continue
        order = weigh_and_ready(order)
        if target == "out_for_delivery":
            orders.change_status(order, S.OUT_FOR_DELIVERY, actor=staff)


def _board_today() -> None:
    """Task 2.6: move some open orders to today, so the order board has work on it. One order is late (not picked up)."""
    from apps.orders.models import Order

    S = Order.Status
    now = timezone.now().replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 5)
    moves = [
        (Order.objects.filter(status=S.READY).first(), -45),            # late: due 45 minutes ago, not picked up yet
        (Order.objects.filter(status=S.OUT_FOR_DELIVERY).first(), -15),
        (Order.objects.filter(status=S.PREPARING).first(), 40),
        (Order.objects.filter(status=S.CONFIRMED, fulfilment="pickup").first(), 90),
    ]  # the confirmed delivery order stays tomorrow ("Show tomorrow" on the board)
    for order, minutes in moves:
        if order is not None:
            Order.objects.filter(pk=order.pk).update(due_at=now + timedelta(minutes=minutes), due_until=None)


def _conversations(customers: list, users: dict) -> None:
    from apps.inbox.models import Conversation, Message

    agent = users.get("shop_staff")
    now = timezone.now()
    for n, script in enumerate(data.CONVERSATIONS):
        customer = customers[n]
        conv = Conversation.objects.create(external_id=customer.phone.lstrip("+"), customer=customer, assigned_to=agent if n == 0 else None,
                                           status=Conversation.Status.CLOSED if n == 2 else Conversation.Status.OPEN)
        times = []
        for m, (direction, text) in enumerate(script):
            at = now - timedelta(hours=3 * (3 - n), minutes=10 * (len(script) - m))
            msg = Message.objects.create(conversation=conv, direction=direction, text=text, sent_by=agent if direction == "out" else None,
                                         status=Message.Status.RECEIVED if direction == "in" else Message.Status.READ, provider_timestamp=at)
            Message.objects.filter(pk=msg.pk).update(created_at=at)
            times.append((direction, text, at))
        Conversation.objects.filter(pk=conv.pk).update(
            last_message_at=times[-1][2], last_message_preview=times[-1][1][:120],
            last_inbound_at=max(at for direction, _, at in times if direction == "in"),
            unread_count=1 if times[-1][0] == "in" else 0)


def _order_messages() -> None:
    """
    Made-up WhatsApp messages about the orders (task 2.3), as if they were sent:
    nothing is sent, because test businesses never connect WhatsApp (their
    customers' phone numbers could belong to real people).
    """
    from apps.inbox import services as inbox
    from apps.inbox.models import Conversation, Message
    from apps.orders import notify
    from apps.orders.models import Order, OrderMessage

    K, S = OrderMessage.Kind, Order.Status
    kinds = {S.AWAITING: K.CONFIRM_REQUEST, S.CONFIRMED: K.CONFIRMED, S.FINAL_SENT: K.FINAL_PRICE, S.READY: K.READY,
             S.OUT_FOR_DELIVERY: K.OUT_FOR_DELIVERY, S.CANCELLED_SHOP: K.CANCELLED}
    answers = {K.CONFIRM_REQUEST: (S.CONFIRMED, "Yes, confirm"), K.FINAL_PRICE: (S.FINAL_ACCEPTED, "Yes, accept")}
    OrderMessage.objects.filter(status=OrderMessage.Status.SKIPPED).delete()  # "WhatsApp is not connected" from making the orders
    for order in Order.objects.filter(customer__isnull=False).select_related("customer").order_by("number"):
        conversation = inbox.conversation_for_customer(order.customer)
        events = list(order.events.order_by("at", "id"))
        last_at = None
        for i, event in enumerate(events):
            kind = kinds.get(event.to_status)
            if kind is None or (kind == K.READY and event.from_status == S.OUT_FOR_DELIVERY):
                continue
            message = OrderMessage(order=order, kind=kind, extra=event.note if kind == K.CANCELLED else "",
                                   token=secrets.token_hex(8) if kind in notify.QUESTIONS else "")
            content = notify.build(message)
            after = events[i + 1] if i + 1 < len(events) else None
            answered = kind in answers and after is not None and after.to_status == answers[kind][0]
            is_open = kind in notify.QUESTIONS and after is None
            sent = Message.objects.create(
                conversation=conversation, direction=Message.Direction.OUT, kind="buttons" if kind in notify.BUTTONS else "text",
                text=content.text + "\n(made-up test message, never sent)",
                status=Message.Status.READ if (answered or not is_open) else Message.Status.DELIVERED)
            Message.objects.filter(pk=sent.pk).update(created_at=event.at)
            message.inbox_message, message.status, message.via = sent, OrderMessage.Status.SENT, OrderMessage.Via.MESSAGE
            message.is_open, message.asked_total = is_open, order.total if kind in notify.QUESTIONS else None
            if answered:
                message.answer, message.answered_at = OrderMessage.Answer.YES, after.at
                reply = Message.objects.create(conversation=conversation, direction=Message.Direction.IN, kind="interactive",
                                               text=answers[kind][1], status=Message.Status.RECEIVED, provider_timestamp=after.at)
                Message.objects.filter(pk=reply.pk).update(created_at=after.at)
            message.save()
            OrderMessage.objects.filter(pk=message.pk).update(created_at=event.at, sent_at=event.at)
            last_at = event.at
        if last_at is not None:
            Conversation.objects.filter(pk=conversation.pk, last_message_at__isnull=True).update(
                last_message_at=last_at, last_message_preview=f"Order #{order.number} (made-up test messages)")


def _ai_chats(spec: dict, customers: list) -> None:
    """
    AI assistant settings and two made-up AI chats (task 2.4): one order the AI
    made and sent to the customer to confirm, and one chat it handed to staff.
    No AI key is saved, so the AI never really answers in a test business.
    """
    from apps.ai.models import AIChat, AIRun, AISettings
    from apps.inbox import services as inbox
    from apps.inbox.models import Conversation, Message
    from apps.orders.models import Order

    AISettings.objects.update_or_create(pk=1, defaults={"enabled": True, "monthly_limit": Decimal("20.00"), "instructions": spec.get("ai_note", "")})
    now = timezone.now()
    made_up = " (made-up test message, never sent)"

    def chat_message(conversation, direction, text, minutes_ago):
        at = now - timedelta(minutes=minutes_ago)
        msg = Message.objects.create(conversation=conversation, direction=direction, text=text, bot=direction == "out",
                                     status=Message.Status.RECEIVED if direction == "in" else Message.Status.READ, provider_timestamp=at)
        Message.objects.filter(pk=msg.pk).update(created_at=at)
        return msg

    order = Order.objects.filter(status=Order.Status.AWAITING, customer__isnull=False).select_related("customer").first()
    if order is not None and order.lines.exists():
        conversation = inbox.conversation_for_customer(order.customer)
        line = order.lines.first()
        amount = f"{line.quantity.normalize():f}{' kg' if line.unit == 'kg' else ' x'}"
        when = timezone.localtime(order.due_at).strftime("%A %H:%M") if order.due_at else "tomorrow"
        ask = chat_message(conversation, "in", f"Namaste! Can I get {amount} {line.product_name} for pickup {when}?", 40)
        answer = chat_message(conversation, "out", f"Namaste! I have made order #{order.number}: {amount} {line.product_name}, pickup {when}, "
                                                   f"about ${order.estimated_total:.2f}. I sent you the summary: please press Yes to confirm.{made_up}", 39)
        AIChat.objects.update_or_create(conversation=conversation, defaults={"order": order})
        steps = [{"tool": "search_products", "args": {"query": line.product_name.split()[0].lower()}, "result": {"products": [{"name": line.product_name}]}},
                 {"tool": "set_order", "args": {"lines": [{"product_id": line.product_id, "quantity": str(line.quantity)}], "fulfilment": "pickup"},
                  "result": {"order": {"order_number": order.number}, "problems": "none"}},
                 {"tool": "send_for_confirmation", "args": {}, "result": {"sent": True}}]
        AIRun.objects.create(conversation=conversation, message=ask, reply=answer, order=order, provider="anthropic", model="claude-haiku-5-5",
                             result=AIRun.Result.ANSWERED, input_tokens=4600, output_tokens=290, cost=Decimal("0.00107"),
                             tools="search_products, set_order, send_for_confirmation", steps=steps, note="Made-up test entry", duration_ms=2400)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=answer.created_at, last_inbound_at=ask.created_at,
                                                               last_message_preview=answer.text[:120])
    # "Same as last time" (task 2.5): the AI copied a customer's last order into a new draft at today's prices.
    from apps.orders import services as orders

    busy = AIChat.objects.values("conversation__customer")
    source = (Order.objects.filter(status=Order.Status.COMPLETED, customer__isnull=False).exclude(customer__in=busy)
              .exclude(customer=customers[10] if len(customers) > 10 else None).select_related("customer").order_by("-completed_at").first())
    if source is not None:
        conversation = inbox.conversation_for_customer(source.customer)
        copy, left_out = orders.reorder(source, channel=Order.Channel.WHATSAPP)
        ask = chat_message(conversation, "in", "Pahile jastai order garna milcha? Same as last time please.", 15)
        answer = chat_message(conversation, "out", f"Of course! I copied your order #{source.number} into a new order #{copy.number} "
                                                   f"at today's prices (about ${copy.estimated_total:.2f}). What time would you like it?{made_up}", 14)
        AIChat.objects.update_or_create(conversation=conversation, defaults={"order": copy})
        AIRun.objects.create(conversation=conversation, message=ask, reply=answer, order=copy, provider="anthropic", model="claude-haiku-5-5",
                             result=AIRun.Result.ANSWERED, input_tokens=3900, output_tokens=210, cost=Decimal("0.00088"), tools="past_orders, reorder",
                             steps=[{"tool": "past_orders", "args": {}, "result": {"orders": [{"order_number": source.number}]}},
                                    {"tool": "reorder", "args": {"order_number": source.number}, "result": {"order": {"order_number": copy.number}}}],
                             note="Made-up test entry", duration_ms=1900)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=answer.created_at, last_inbound_at=ask.created_at,
                                                               last_message_preview=answer.text[:120])
    customer = customers[10] if len(customers) > 10 else None
    if customer is not None:
        conversation = inbox.conversation_for_customer(customer)
        ask = chat_message(conversation, "in", "My order yesterday came late and the food was cold. I want to talk to someone.", 25)
        answer = chat_message(conversation, "out", f"I am very sorry. A staff member will call you soon.{made_up}", 24)
        AIChat.objects.update_or_create(conversation=conversation, defaults={
            "handed_over_at": now - timedelta(minutes=24), "handover_reason": "Customer complaint about a late order", "told_customer_at": now - timedelta(minutes=24)})
        AIRun.objects.create(conversation=conversation, message=ask, reply=answer, provider="anthropic", model="claude-haiku-5-5",
                             result=AIRun.Result.HANDED_OVER, input_tokens=1500, output_tokens=60, cost=Decimal("0.00032"), tools="hand_over",
                             steps=[{"tool": "hand_over", "args": {"reason": "Customer complaint about a late order"}, "result": {"done": True}}],
                             note="Customer complaint about a late order", duration_ms=1300)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=answer.created_at, last_inbound_at=ask.created_at,
                                                               last_message_preview=answer.text[:120], unread_count=1, status=Conversation.Status.OPEN)


def _tickets(users: dict) -> None:
    from apps.tickets.models import Ticket, TicketComment

    reporter = users.get("shop_staff")
    handler = users.get("it_admin")
    now = timezone.now()
    for n, (title, description, category, priority, status) in enumerate(data.TICKETS):
        created = now - timedelta(days=n + 1, hours=2)
        ticket = Ticket.objects.create(
            title=title, description=description, category=category, priority=priority, status=status,
            reporter=reporter, reporter_name=reporter.get_full_name() if reporter else "", reporter_email=reporter.email if reporter else "",
            assigned_to=handler if status != "new" else None, page="/admin/orders/order/", browser="Chrome on Windows (test data)",
            created_at=created, first_response_at=created + timedelta(minutes=40) if status != "new" else None,
            resolved_at=created + timedelta(hours=5) if status == "resolved" else None,
        )
        if status != "new":
            TicketComment.objects.create(ticket=ticket, author=handler, author_name=handler.get_full_name() if handler else "",
                                         author_email=handler.email if handler else "", body=data.TICKET_ANSWER,
                                         created_at=created + timedelta(minutes=40))


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------
def remove(*, actor_email: str = "") -> list[str]:
    """Delete every test business (and its schema) and the platform test accounts. Real businesses are never touched."""
    from apps.accounts.models import User
    from apps.tickets.models import Ticket

    if not cache.add(LOCK_KEY, 1, 3600):
        raise ValidationError("Test data is being installed or removed right now. Wait until it has finished.")
    report = []
    try:
        tenants = list(test_businesses())
        for n, tenant in enumerate(tenants):
            _progress("running", f"Removing {tenant.name} ({n + 1} of {len(tenants)})", n, len(tenants))
            assert tenant.is_test and tenant.schema_name != get_public_schema_name()
            schema, name = tenant.schema_name, tenant.name
            with connection.cursor() as cursor:
                # Check waiting foreign-key checks now; PostgreSQL cannot drop tables that still have some.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            tenant.delete(force_drop=True)
            Ticket.objects.filter(from_schema=schema).delete()  # copies sent to platform support
            report.append(f"{name}: removed")
        gone, _ = User.objects.filter(email__startswith="roleas", email__endswith="@" + data.EMAIL_DOMAIN, is_superuser=False).delete()
        if gone:
            report.append("Platform test accounts: removed")
        audit("test_data.removed", actor=None, metadata={"by": actor_email, "result": report})
        _progress("done", "Test data removed.", len(tenants), len(tenants))
        return report
    except Exception as exc:
        _progress("failed", f"Stopped: {exc}")
        raise
    finally:
        cache.delete(LOCK_KEY)
