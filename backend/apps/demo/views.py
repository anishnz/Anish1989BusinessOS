"""
Platform page /platform/test-data/ (task 1.18): install or remove the test
businesses, and see every test login with a "Log in as" button.
Super Admin only. Removing needs the delete safety check.
"""
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django_tenants.utils import get_public_schema_name

from apps.accounts.login_as import is_super_admin
from apps.core import deleteguard

from . import data, services


def nav(request) -> dict:
    """Show "Test data" in the platform header for the Super Admin (template context processor)."""
    user = getattr(request, "user", None)
    on_platform = getattr(connection, "schema_name", "") == get_public_schema_name()
    if not on_platform or user is None or not user.is_authenticated or not user.is_staff:
        return {}
    return {"show_test_data_link": is_super_admin(user)}


def _start(kind: str, email: str) -> None:
    from . import tasks

    task = tasks.install_test_data if kind == "install" else tasks.remove_test_data
    services._progress("queued", "Starting…")
    transaction.on_commit(lambda: task.delay(email))


@never_cache
def test_data(request):
    if not is_super_admin(request.user):
        raise PermissionDenied
    here = reverse("platform_test_data")
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "install":
                services.password()
                _start("install", request.user.email)
                messages.success(request, "Installing test data. It takes about 2 minutes; this page updates by itself.")
            elif action == "remove":
                names = ", ".join(t.name for t in services.test_businesses()) or "no test businesses"
                page = deleteguard.require(
                    request, title="Remove all test data?", back=here, fields={"action": "remove"},
                    message=f"These test businesses and everything in them will be deleted: {names}. "
                            "The platform test accounts are deleted too. Real businesses are not touched.")
                if page is not None:
                    return page
                _start("remove", request.user.email)
                messages.success(request, "Removing test data. This page updates by itself.")
            else:
                messages.error(request, "Unknown action.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(here)
    state = services.progress()
    businesses = list(services.test_businesses().prefetch_related("domains"))
    chosen = next((b for b in businesses if b.schema_name == request.GET.get("business")), businesses[0] if businesses else None)
    return render(request, "demo/test_data.html", {
        **admin.site.each_context(request), "title": "Test data",
        "password_set": len(getattr(settings, "DEMO_PASSWORD", "") or "") >= 8,
        "businesses": businesses, "chosen": chosen,
        "accounts": services.accounts(chosen.schema_name) if chosen else [], "state": state,
        "platform_accounts": services.platform_accounts(),
        "running": bool(state and state["state"] in ("queued", "running")),
        "planned": data.BUSINESSES, "address": data.FULL_ADDRESS, "email_example": data.role_email("shop_staff"),
    })
