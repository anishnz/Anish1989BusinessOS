"""
Security sweeps (task 1.10).

These tests do not list pages by hand: they walk every URL the platform site
and the business sites have, so a page or API added later is checked
automatically. They prove that:

1. without logging in, nothing but the public pages answers;
2. a logged-in person with no role gets nothing (deny by default);
3. staff who have not finished two-step verification get nothing;
4. a full admin of business B never sees business A's data, on any API or admin page;
5. a switched-off module, or a suspended business, is blocked everywhere;
6. CSRF protection is on, session cookies stay on their own business's address,
   and Django's production checks pass.
"""
import re
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib import admin
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django_tenants.utils import schema_context

from tests.conftest import PASSWORD, add_totp_device, host_of, https_client, make_user

PARAM = re.compile(r"<(?:(\w+):)?(\w+)>")

# Pages anyone may open (they protect themselves in other ways).
PUBLIC_ROUTES = {
    "health/",
    "api/auth/csrf/",
    "api/auth/login/",
    "api/auth/password/reset/",
    "admin/login/",
    "admin/logout/",
    "admin/password_reset/",
    "account/password_reset/done/",
    "account/reset/<uidb64>/<token>/",
    "account/reset/done/",
    "webhooks/whatsapp/",  # checked by the Meta signature instead (test_inbox.py)
}
# Pages about the logged-in person themselves.
SELF_ROUTES = {r for r in [
    "api/auth/logout/", "api/auth/me/", "api/auth/mfa/verify/", "api/auth/mfa/totp/setup/", "api/auth/mfa/totp/confirm/",
    "api/auth/mfa/backup-codes/", "api/rbac/me/permissions/", "account/mfa/setup/", "account/mfa/verify/", "account/mfa/",
]}


def routes(urlconf: str) -> list[str]:
    found = []

    def walk(patterns, prefix):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                found.append(prefix + str(p.pattern))

    walk(get_resolver(urlconf).url_patterns, "")
    return sorted(set(found))


def is_regex(route: str) -> bool:
    return route.startswith("^") or "(?P" in route or route.endswith("$")


def concrete(route: str, values: dict | None = None) -> str:
    def sub(m):
        name = m.group(2)
        if values and name in values:
            return str(values[name])
        return "1" if m.group(1) == "int" else ("tenant_a" if name == "schema" else "x")

    return "/" + PARAM.sub(sub, route)


BUSINESS_ROUTES = [r for r in routes("config.urls") if not is_regex(r)]
PLATFORM_ROUTES = [r for r in routes("config.urls_public") if not is_regex(r)]


def test_route_lists_are_complete():
    """The sweeps really see the pages (guards against the sweep silently testing nothing)."""
    for expected in ("api/products/", "api/orders/<int:pk>/status/", "api/inbox/conversations/<int:pk>/reply/", "dashboard/",
                     "admin/catalog/product/import/", "settings/integrations/", "api/reports/dashboard/"):
        assert expected in BUSINESS_ROUTES, expected
    assert "platform/people/<slug:schema>/<int:user_id>/" in PLATFORM_ROUTES
    assert "api/products/" not in PLATFORM_ROUTES and "dashboard/" not in PLATFORM_ROUTES
    # Regex routes only exist inside Django's admin, which wraps every view in its login check.
    for urlconf in ("config.urls", "config.urls_public"):
        assert all(r.startswith("admin/") for r in routes(urlconf) if is_regex(r))


def _login_redirect(response) -> bool:
    return response.status_code == 302 and "login" in response["Location"]


def _assert_no_data(response, url, allowed_codes):
    assert response.status_code != 500, f"{url} crashed"
    assert response.status_code in allowed_codes or _login_redirect(response), f"{url} answered {response.status_code}"


# ---------------------------------------------------------------------------
# 1. Not logged in
# ---------------------------------------------------------------------------
@pytest.mark.django_db
@pytest.mark.parametrize("site", ["business", "platform"])
def test_nothing_answers_without_login(client_for, tenant_a, public_tenant, site):
    tenant, route_list = (tenant_a, BUSINESS_ROUTES) if site == "business" else (public_tenant, PLATFORM_ROUTES)
    client = client_for(tenant)
    for route in route_list:
        url = concrete(route)
        for method in ("get", "post"):
            response = getattr(client, method)(url)
            assert response.status_code != 500, f"{method.upper()} {url} crashed"
            if route not in PUBLIC_ROUTES:
                _assert_no_data(response, f"{method.upper()} {url}", {401, 403, 404, 405})


# ---------------------------------------------------------------------------
# 2. Logged in, but no role (deny by default)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_a_person_without_roles_gets_nothing(client_for, tenant_a):
    make_user("tenant_a", "nobody@a.test")
    client = client_for(tenant_a)
    assert client.post("/api/auth/login/", {"email": "nobody@a.test", "password": PASSWORD}).status_code == 200
    for route in BUSINESS_ROUTES:
        if route in PUBLIC_ROUTES | SELF_ROUTES:
            continue
        url = concrete(route)
        for method in ("get", "post"):
            response = getattr(client, method)(url)
            allowed = {403, 405} if route.startswith("api/") else {302, 403, 405}
            _assert_no_data(response, f"{method.upper()} {url}", allowed)


@pytest.mark.django_db
def test_staff_without_roles_sees_no_admin_pages(client_for, tenant_a):
    from tests.test_rbac import verified_staff_client

    client = verified_staff_client(client_for, tenant_a, "staff@a.test")
    for model, model_admin in admin.site._registry.items():
        opts = model._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        response = client.get(url)
        assert response.status_code in (302, 403, 404), f"{url} answered {response.status_code}"
    index = client.get("/admin/").content.decode()
    assert "/admin/catalog/" not in index and "/admin/orders/" not in index


# ---------------------------------------------------------------------------
# 3. Staff who have not finished two-step verification
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_unverified_staff_are_stopped_everywhere(client_for, tenant_a):
    user = make_user("tenant_a", "boss@a.test", superuser=True)
    add_totp_device("tenant_a", user)
    client = client_for(tenant_a)
    body = client.post("/api/auth/login/", {"email": "boss@a.test", "password": PASSWORD}).json()
    assert body["mfa"]["required"] is True
    exempt = ("account/", "api/auth/", "admin/login/", "admin/logout/", "admin/password_reset/", "health/")
    for route in BUSINESS_ROUTES:
        if route.startswith(exempt) or route in PUBLIC_ROUTES:
            continue
        url = concrete(route)
        response = client.get(url)
        if route.startswith("api/"):
            assert response.status_code == 403 and response.json().get("code") == "mfa_required", url
        else:
            assert response.status_code == 302 and response["Location"].startswith("/account/mfa/"), url


# ---------------------------------------------------------------------------
# 4. Business B never sees business A's data
# ---------------------------------------------------------------------------
MARKER = "leakmarker"


def seed_business_a() -> dict[str, list[int]]:
    """Put a recognisable marker into every kind of record in business A."""
    from apps.catalog.models import Category, Product
    from apps.customers.models import Customer
    from apps.inbox.models import Conversation, Message
    from apps.orders import services as orders
    from apps.rbac.models import Role, UserRole
    from apps.vault import services as vault

    user = make_user("tenant_a", f"{MARKER}@a.test", staff=True)
    with schema_context("tenant_a"):
        role = Role.objects.create(slug=f"{MARKER}_role", name=f"{MARKER} role")
        UserRole.objects.create(user=user, role=role)
        category = Category.objects.create(name=f"{MARKER} category")
        product = Product.objects.create(name=f"{MARKER} lamb", sku=f"{MARKER}-1", price=Decimal("10"), category=category)
        customer = Customer.objects.create(name=f"{MARKER} customer", phone="+64211234567", email=f"{MARKER}@cust.test", notes=MARKER)
        order = orders.create_order(lines=[orders.LineInput(product.pk, Decimal("1"))], customer=customer, notes=f"{MARKER} notes")
        conversation = Conversation.objects.create(external_id="64211234567", customer=customer, last_message_preview=MARKER)
        Message.objects.create(conversation=conversation, direction="in", text=f"{MARKER} message", status="received", provider_message_id=f"wamid.{MARKER}")
        connection = vault.create_connection(provider_code="openai", label=f"{MARKER} ai", config={}, secrets={"api_key": f"sk-{MARKER}-123456789"})
    return {
        "ids": sorted({user.pk, role.pk, category.pk, product.pk, customer.pk, order.pk, conversation.pk, connection.pk}),
        "objects": {"user": user, "product": product, "customer": customer, "order": order, "conversation": conversation, "connection": connection, "role": role},
    }


def _no_marker(response, url):
    assert response.status_code != 500, f"{url} crashed"
    assert MARKER not in response.content.decode(errors="ignore").lower(), f"{url} shows business A's data"


@pytest.mark.django_db
def test_full_admin_of_business_b_never_sees_business_a(client_for, tenant_a, tenant_b):
    from tests.test_rbac import verified_staff_client

    seeded = seed_business_a()
    client = verified_staff_client(client_for, tenant_b, "admin@b.test", "system_admin")
    checked = 0
    for route in BUSINESS_ROUTES:
        if route in PUBLIC_ROUTES or route.startswith("admin/"):
            continue
        params = PARAM.findall(route)
        candidates = [concrete(route, {name: pk for _, name in params}) for pk in seeded["ids"]] if params else [concrete(route)]
        for url in candidates:
            _no_marker(client.get(url), url)
            checked += 1
    # Every admin list page, and every A object's change page, as seen from B.
    for model in admin.site._registry:
        opts = model._meta
        _no_marker(client.get(reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")), opts.label)
        for pk in seeded["ids"]:
            url = f"/admin/{opts.app_label}/{opts.model_name}/{pk}/change/"
            _no_marker(client.get(url), url)
            checked += 1
    # Searches in B for A's data find nothing.
    # (Search for part of the marker: the page repeats the search words, but must not show A's records.)
    term = MARKER[:-2]
    for url in ("/api/products/?q=" + term, "/api/customers/?q=" + term, "/api/orders/?q=" + term, "/api/inbox/conversations/?q=" + term,
                "/admin/customers/customer/?q=" + term, "/admin/catalog/product/?q=" + term, "/admin/accounts/user/?q=" + term):
        _no_marker(client.get(url), url)
    assert checked > 100  # the sweep really ran


@pytest.mark.django_db
def test_platform_apis_do_not_show_business_data(verified_admin_client, public_tenant, tenant_a):
    seeded = seed_business_a()
    client = verified_admin_client(public_tenant)
    for route in PLATFORM_ROUTES:
        if route in PUBLIC_ROUTES or route.startswith(("admin/", "platform/")):
            continue  # the Super Admin's "Businesses and users" pages show business users on purpose
        params = PARAM.findall(route)
        for url in ([concrete(route, {n: pk for _, n in params}) for pk in seeded["ids"]] if params else [concrete(route)]):
            _no_marker(client.get(url), url)


@pytest.mark.django_db
def test_platform_admin_pages_never_crash_or_show_business_only_records(verified_admin_client, public_tenant):
    """Business-only tables do not exist on the platform site; their admin pages must be refused, never crash."""
    from django.conf import settings as s

    business_only = {app.split(".")[-1] for app in s.TENANT_APPS if app not in s.SHARED_APPS}
    client = verified_admin_client(public_tenant)
    for model in admin.site._registry:
        opts = model._meta
        for name in ("changelist", "add"):
            try:
                url = reverse(f"admin:{opts.app_label}_{opts.model_name}_{name}")
            except Exception:  # noqa: BLE001 - some admins have no add page
                continue
            response = client.get(url)
            assert response.status_code != 500, f"{url} crashed on the platform site"
            if opts.app_label in business_only:
                assert response.status_code in (302, 403, 404), f"{url} answered {response.status_code} on the platform site"


# ---------------------------------------------------------------------------
# 5. Switched-off modules and suspended businesses
# ---------------------------------------------------------------------------
MODULE_ROUTES = {
    "products": ("api/products/", "admin/catalog/"),
    "crm": ("api/customers/", "api/inbox/", "admin/customers/", "admin/inbox/"),
    "orders": ("api/orders/", "admin/orders/"),
    "reports": ("api/reports/", "dashboard/"),
}


@pytest.mark.django_db
@pytest.mark.parametrize("module", sorted(MODULE_ROUTES))
def test_a_switched_off_module_is_blocked_everywhere(client_for, tenant_a, module):
    from apps.licensing.services import set_module_enabled
    from tests.test_rbac import verified_staff_client

    seeded = seed_business_a()["objects"]
    real_ids = {"product": seeded["product"].pk, "customer": seeded["customer"].pk, "order": seeded["order"].pk,
                "conversation": seeded["conversation"].pk, "category": seeded["product"].category_id}
    client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
    set_module_enabled(tenant_a, module, False)
    try:
        checked = 0
        for route in BUSINESS_ROUTES:
            if not route.startswith(MODULE_ROUTES[module]):
                continue
            # Use a real record of the right kind, so "not found" cannot hide a missing check.
            kind = next((k for k in real_ids if f"/{k}/" in "/" + route), None)
            value = real_ids.get(kind, real_ids["order"])
            url = concrete(route, {"pk": value, "object_id": value})
            response = client.get(url)
            if response.status_code == 302 and response["Location"] == url + "change/":
                url = response["Location"]  # Django's admin moves ".../<id>/" to ".../<id>/change/"
                response = client.get(url)
            assert response.status_code in (403, 405), f"{url} answered {response.status_code} with {module} off"
            checked += 1
        assert checked
    finally:
        set_module_enabled(tenant_a, module, True)


@pytest.mark.django_db
def test_a_suspended_business_is_blocked_everywhere(client_for, tenant_a):
    from apps.licensing.services import reactivate, suspend
    from tests.test_rbac import verified_staff_client

    client = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
    suspend(tenant_a, "Unpaid invoice")
    try:
        for route in BUSINESS_ROUTES:
            if route == "health/":
                continue
            url = concrete(route)
            for c in (client, client_for(tenant_a)):
                response = c.get(url)
                assert response.status_code == 403, f"{url} answered {response.status_code} while suspended"
        assert client_for(tenant_a).get("/health/").status_code == 200
    finally:
        reactivate(tenant_a)


# ---------------------------------------------------------------------------
# 6. CSRF, cookies, production settings
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_csrf_protection_is_on_for_logged_in_api_calls(tenant_a):
    from tests.test_rbac import give_role

    user = make_user("tenant_a", "owner@a.test")
    give_role("tenant_a", user, "business_owner")
    client = Client(HTTP_HOST=host_of(tenant_a), enforce_csrf_checks=True)
    client.defaults["wsgi.url_scheme"] = "https"
    token = client.get("/api/auth/csrf/", secure=True).json()["csrfToken"]
    login = client.post("/api/auth/login/", {"email": "owner@a.test", "password": PASSWORD}, secure=True, HTTP_X_CSRFTOKEN=token,
                        HTTP_REFERER=f"https://{host_of(tenant_a)}/")
    assert login.status_code == 200
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    data = {"name": "Lamb", "price": "10"}
    refused = client.post("/api/products/", data, content_type="application/json", secure=True, HTTP_REFERER=f"https://{host_of(tenant_a)}/")
    assert refused.status_code == 403 and "CSRF" in refused.content.decode()
    accepted = client.post("/api/products/", data, content_type="application/json", secure=True, HTTP_X_CSRFTOKEN=token,
                           HTTP_REFERER=f"https://{host_of(tenant_a)}/")
    assert accepted.status_code == 201


@pytest.mark.django_db
def test_session_cookie_from_one_business_does_not_work_on_another(client_for, tenant_a, tenant_b):
    assert settings.SESSION_COOKIE_DOMAIN is None and settings.CSRF_COOKIE_DOMAIN is None  # cookies stay on their own address
    make_user("tenant_a", "owner@a.test")
    a = client_for(tenant_a)
    assert a.post("/api/auth/login/", {"email": "owner@a.test", "password": PASSWORD}).status_code == 200
    assert a.get("/api/auth/me/").status_code == 200
    b = https_client(host_of(tenant_b))
    b.cookies[settings.SESSION_COOKIE_NAME] = a.cookies[settings.SESSION_COOKIE_NAME].value
    assert b.get("/api/auth/me/").status_code == 403


def test_password_rules():
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    for weak in ("short1", "password1234", "123456789012"):
        with pytest.raises(ValidationError):
            validate_password(weak)
    validate_password("a-long-test-password-123")


@pytest.mark.skipif(settings.DEBUG or not getattr(settings, "SESSION_COOKIE_SECURE", False), reason="production settings only (CI runs them)")
def test_django_production_checks_pass():
    from django.core.management import call_command

    call_command("check", deploy=True, fail_level="WARNING")
