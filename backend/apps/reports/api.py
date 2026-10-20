"""
GET /api/reports/dashboard/?date=YYYY-MM-DD   today's numbers (or another day)   reports.view
"""
from datetime import date
from decimal import Decimal

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac import policy
from apps.rbac.permissions import ModulePermission

from . import dashboard


def exact(value):
    """Money as exact strings ("12.50"), like the other APIs; never floating point."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {k: exact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [exact(v) for v in value]
    return value


class DashboardView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "reports"

    def get(self, request):
        value = request.query_params.get("date")
        try:
            day = date.fromisoformat(value) if value else None
        except ValueError:
            return Response({"detail": "Dates must look like 2026-10-21."}, status=400)
        return Response(exact(dashboard.summary(day, include_inbox=policy.has_perm(request.user, "crm.view"))))
