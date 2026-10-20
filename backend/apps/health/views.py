"""
"Check system" page and API, on the platform site and on every business site.

/system-check/                 page with the button, latest results and history
/system-check/<run id>/        one earlier run
GET  /api/system-check/        latest run and the last 20 runs (summary)
POST /api/system-check/run/    run the checks now (once a minute at most)

Who: on a business site, Settings - View (System Admin, IT Admin, Business
Owner); on the platform site, Platform settings - View.
"""
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac import policy

from . import checks, services
from .models import CheckRun


def permission_code() -> str:
    return "platform_settings.view" if services.on_platform() else "settings.view"


def _require(request) -> None:
    if not policy.require(request.user, permission_code(), request=request):
        raise PermissionDenied


def _context(request, record, **extra):
    return {
        **admin.site.each_context(request),
        "record": record,
        "groups": services.grouped(record.results) if record else [],
        "history": CheckRun.objects.order_by("-started_at", "-id")[:20],
        "counts": [(k, label, record.counts.get(k)) for k, label in checks.STATUS_LABELS.items() if record and record.counts.get(k)],
        "covers": "database, every business's database, background jobs, disk space, licences, saved connections, security and backups"
        if services.on_platform() else
        "database, background jobs, licence, web address, saved connections (API keys), email, WhatsApp, security and backups",
        "where": "the platform" if services.on_platform() else (services.current_tenant().name if services.current_tenant() else ""),
        **extra,
    }


@never_cache
def check_page(request):
    _require(request)
    if request.method == "POST":
        try:
            record = services.run(CheckRun.Trigger.BUTTON, user=request.user)
        except ValidationError as exc:
            messages.warning(request, " ".join(exc.messages))
        else:
            messages.success(request, f"Checks finished in {record.seconds} seconds.")
        return redirect(reverse("system_check"))
    record = CheckRun.objects.order_by("-started_at", "-id").first()
    return render(request, "health/check_system.html", _context(request, record, title="Check system", latest=True))


@never_cache
def run_page(request, pk: int):
    _require(request)
    record = CheckRun.objects.filter(pk=pk).first()
    if record is None:
        raise Http404("No such check run.")
    return render(request, "health/check_system.html", _context(request, record, title="Check system: earlier run", latest=False))


def run_json(record: CheckRun | None, *, full: bool = True) -> dict | None:
    if record is None:
        return None
    data = {
        "id": record.pk, "started_at": record.started_at, "finished_at": record.finished_at, "seconds": record.seconds,
        "trigger": record.trigger, "run_by": record.run_by_email, "status": record.status, "counts": record.counts,
    }
    if full:
        data["results"] = record.results
    return data


class CheckApi(APIView):
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not policy.require(request.user, permission_code(), request=request._request):
            self.permission_denied(request, message="You do not have permission to see the system checks.")


class CheckStatusView(CheckApi):
    def get(self, request):
        runs = list(CheckRun.objects.order_by("-started_at", "-id")[:20])
        return Response({
            "latest": run_json(runs[0] if runs else None),
            "history": [run_json(r, full=False) for r in runs],
        })


class CheckRunView(CheckApi):
    def post(self, request):
        try:
            record = services.run(CheckRun.Trigger.BUTTON, user=request.user)
        except ValidationError as exc:
            return Response({"detail": " ".join(exc.messages), "code": "too_soon"}, status=http.HTTP_429_TOO_MANY_REQUESTS)
        return Response(run_json(record), status=http.HTTP_201_CREATED)
