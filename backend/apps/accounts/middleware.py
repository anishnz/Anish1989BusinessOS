"""
Require MFA for staff and admins.

A staff user who has signed in with a password but has not yet entered an
authenticator code is sent to the MFA pages (or gets a 403 from the API)
until they verify. If they have no authenticator yet, they must set one up.
"""
from urllib.parse import quote

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import login_as, security

# Paths a signed-in but unverified staff user may still use.
EXEMPT_PREFIXES = (
    "/account/",          # MFA setup/verify pages and password reset
    "/api/auth/",         # login, logout, MFA API
    "/admin/login/",
    "/admin/logout/",
    "/admin/password_reset/",
    "/health/",
    "/static/",
)


class StaffMFAMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not request.path.startswith(EXEMPT_PREFIXES)
            and not user.is_verified()
            and not login_as.info(request)  # a Super Admin using "Log in as" passed it on the platform (task 1.18)
            # Staff must use MFA; anyone else who turned MFA on must use it too.
            and (user.mfa_required or security.has_mfa(user))
        ):
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Multi-factor authentication is required.", "code": "mfa_required"}, status=403
                )
            target = "accounts:mfa_verify" if security.has_mfa(user) else "accounts:mfa_setup"
            return redirect(f"{reverse(target)}?next={quote(request.get_full_path())}")
        return self.get_response(request)
