"""
Block businesses whose access has ended (expired, suspended, cancelled, or no
licence). Applies to every page and API, including admins, except the health
check and static files.
"""
from django.http import JsonResponse
from django.shortcuts import render

from . import services

EXEMPT_PREFIXES = ("/health/", "/static/")

MESSAGES = {
    "expired": ("This account has expired", "The trial or subscription for this business has ended."),
    "suspended": ("This account is suspended", "Access to this business has been suspended by the platform."),
    "cancelled": ("This account is closed", "This business account has been cancelled."),
    "unlicensed": ("This account is not set up yet", "This business does not have a licence yet."),
    "unknown": ("This account is not available", "This business account could not be found."),
}


class LicenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None or request.path.startswith(EXEMPT_PREFIXES):
            return self.get_response(request)

        state = services.access_state(tenant)
        if state not in services.ALLOWED_STATES:
            title, message = MESSAGES.get(state, MESSAGES["unknown"])
            if request.path.startswith("/api/"):
                return JsonResponse({"detail": message, "code": f"account_{state}"}, status=403)
            return render(request, "licensing/blocked.html", {"title": title, "message": message}, status=403)

        response = self.get_response(request)
        if state == "grace":
            response["X-Account-Status"] = "grace"  # the frontend shows a "please renew" banner
        return response
