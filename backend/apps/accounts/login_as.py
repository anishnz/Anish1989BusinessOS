"""
"Log in as" (task 1.18, D-128): the platform Super Admin opens a business's
pages as one of its users, then comes back.

1. Platform site, POST /platform/login-as/<business>/<user id>/ (Super Admin
   only; a reason is needed for real businesses, not for test businesses).
   It makes a signed link that works once, for 60 seconds, for that one user.
2. Business site, GET /login-as/?token=... signs that user in. The session
   remembers who is really there and ends after 60 minutes at the latest.
   Two-step verification is not asked: the Super Admin already passed it.
3. A red bar on every page says "You are logged in as ... - Back to Super
   Admin". POST /login-as/stop/ signs out of the business and goes back.

Both audit logs record it: the platform's ("security.login_as") and the
business's ("security.login_as_started" / "_ended", by the platform admin).
The Super Admin's own session on the platform site is not touched (each site
has its own login cookie).
"""
from __future__ import annotations

import secrets
import time

from django.contrib import messages
from django.contrib.auth import login, logout
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit, platform_actor

from .models import User

SALT = "anish1989.login-as"
LINK_SECONDS = 60
SESSION_SECONDS = 60 * 60
SESSION_KEY = "login_as"
BACKEND = "apps.accounts.backends.LockoutEmailBackend"


def is_super_admin(user) -> bool:
    from apps.rbac.models import UserRole

    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or UserRole.objects.filter(user=user, role__full_access=True).exists()))


def info(request) -> dict | None:
    """Who is really logged in, while a Super Admin uses "Log in as" (None otherwise)."""
    session = getattr(request, "session", None)
    return session.get(SESSION_KEY) if session is not None else None


# ---------------------------------------------------------------------------
# 1. Platform site
# ---------------------------------------------------------------------------
@never_cache
@require_POST
def start(request, schema: str, user_id: int):
    from apps.tenants import domains
    from apps.tenants.models import Tenant

    if connection.schema_name != get_public_schema_name() or not is_super_admin(request.user):
        raise PermissionDenied
    back = request.POST.get("back") or reverse("platform_people_list", args=[schema])
    if not back.startswith("/platform/"):
        back = reverse("platform_people_list", args=[schema])
    tenant = Tenant.objects.filter(schema_name=schema).exclude(schema_name=get_public_schema_name()).first()
    if tenant is None:
        raise PermissionDenied
    reason = " ".join(str(request.POST.get("reason", "")).split())[:200]
    if not tenant.is_test and not reason:
        messages.error(request, f"Write why you need to log in to {tenant.name} (it is a real business).")
        return redirect(back)
    with schema_context(schema):
        person = User.objects.filter(pk=user_id, is_active=True).first()
    if person is None:
        messages.error(request, "That person does not exist or is locked.")
        return redirect(back)
    host = tenant.domains.filter(is_primary=True).values_list("domain", flat=True).first()
    if not host:
        messages.error(request, f"{tenant.name} has no web address.")
        return redirect(back)
    nonce = secrets.token_urlsafe(16)
    cache.set(f"login-as:{nonce}", 1, LINK_SECONDS)
    token = signing.dumps({"s": schema, "u": person.pk, "by": request.user.email, "n": nonce, "r": reason,
                           "back": request.build_absolute_uri(back)}, salt=SALT, compress=True)
    audit("security.login_as", target=tenant, actor=request.user, metadata={"as": person.email, "reason": reason})
    return HttpResponseRedirect(domains.site_url(host, request, "/login-as/?token=" + token))


# ---------------------------------------------------------------------------
# 2. and 3. Business site
# ---------------------------------------------------------------------------
def _refuse(text: str):
    return HttpResponseBadRequest(f"<p>{text}</p><p>Go back to the platform site and click <strong>Log in as</strong> again.</p>")


@never_cache
@require_GET
def accept(request):
    try:
        data = signing.loads(request.GET.get("token", ""), salt=SALT, max_age=LINK_SECONDS)
    except signing.SignatureExpired:
        return _refuse("This link is older than 60 seconds.")
    except signing.BadSignature:
        return _refuse("This link is not valid.")
    if data.get("s") != connection.schema_name:
        return _refuse("This link is for another business.")
    with schema_context(get_public_schema_name()):  # cache keys carry the site's name; the link was made on the platform site
        fresh = cache.delete(f"login-as:{data.get('n')}")
    if not fresh:
        return _refuse("This link was used already.")
    person = User.objects.filter(pk=data.get("u"), is_active=True).first()
    if person is None:
        return _refuse("That person does not exist or is locked.")
    logout(request)
    login(request, person, backend=BACKEND)
    request.session[SESSION_KEY] = {"by": data["by"], "until": time.time() + SESSION_SECONDS, "back": data["back"],
                                    "reason": data.get("r", ""), "since": timezone.now().isoformat()}
    with platform_actor(data["by"]):
        audit("security.login_as_started", target=person, metadata={"reason": data.get("r", "")})
    return redirect("/admin/" if person.is_staff else "/app/")


def _end(request, why: str, *, as_json: bool = False):
    data = info(request) or {}
    user = request.user if request.user.is_authenticated else None
    if user is not None and data.get("by"):
        with platform_actor(data["by"]):
            audit("security.login_as_ended", target=user, metadata={"why": why})
    logout(request)
    back = data.get("back") or "/"
    return JsonResponse({"back": back}) if as_json else HttpResponseRedirect(back)


@never_cache
@require_POST
def stop(request):
    # The staff app asks for JSON and then opens the platform page itself.
    return _end(request, "back to Super Admin", as_json="application/json" in request.headers.get("Accept", ""))


class LoginAsMiddleware:
    """Ends a "Log in as" session after 60 minutes (back to the platform site)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        data = info(request)
        if data and time.time() > data.get("until", 0):
            if request.path.startswith("/api/"):
                _end(request, "time limit")
                return JsonResponse({"detail": "The Log in as time (60 minutes) is over.", "code": "login_as_ended"}, status=403)
            return _end(request, "time limit")
        return self.get_response(request)


def context(request) -> dict:
    """The red bar on admin pages (template context processor)."""
    data = info(request)
    if not data or not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    minutes = max(0, int((data["until"] - time.time()) // 60))
    return {"login_as": {"by": data["by"], "minutes_left": minutes, "user": request.user.email}}
