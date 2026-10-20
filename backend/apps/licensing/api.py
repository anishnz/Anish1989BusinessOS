"""
Business-side licence API (the business sees its own licence and switches
its licensed modules on or off).

GET   /api/tenant/licence/            plan, status, dates, limits and usage      settings.view
GET   /api/tenant/modules/            every module: core, entitled, enabled      settings.view
PATCH /api/tenant/modules/<code>/     {"enabled": true|false}                     settings.configure
"""
from django.core.exceptions import ValidationError
from django.db import connection
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac.catalogue import TENANT_MODULES
from apps.rbac.permissions import ModulePermission

from . import services
from .models import TenantModule
from .templates_catalogue import CORE_MODULES


def _tenant(request):
    return getattr(request._request, "tenant", None) or connection.tenant


class NotOnPlatform:
    def initial(self, request, *args, **kwargs):
        if _tenant(request).schema_name == "public":
            from rest_framework.exceptions import NotFound

            raise NotFound("Only available on a business site.")
        super().initial(request, *args, **kwargs)


class LicenceView(NotOnPlatform, APIView):
    permission_classes = [ModulePermission]
    permission_module = "settings"

    def get(self, request):
        tenant = _tenant(request)
        licence = tenant.licence
        return Response(
            {
                "business": tenant.name,
                "plan": licence.plan_name,
                "status": services.access_state(tenant),
                "trial_ends_at": licence.trial_ends_at if tenant.status == "trial" else None,
                "ends_at": licence.ends_at,
                "grace_ends_at": licence.grace_ends_at(),
                "usage": services.usage(tenant),
            }
        )


class ModuleSwitchSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ModuleListView(NotOnPlatform, APIView):
    permission_classes = [ModulePermission]
    permission_module = "settings"

    def get(self, request):
        tenant = _tenant(request)
        rows = {m.module: m for m in TenantModule.objects.filter(tenant=tenant)}
        result = []
        for module in TENANT_MODULES:
            core = module.code in CORE_MODULES
            row = rows.get(module.code)
            result.append(
                {
                    "code": module.code,
                    "label": module.label,
                    "core": core,
                    "entitled": core or bool(row and row.entitled),
                    "enabled": core or bool(row and row.is_active),
                }
            )
        return Response(result)


class ModuleDetailView(NotOnPlatform, APIView):
    permission_classes = [ModulePermission]
    permission_module = "settings"
    permission_actions = {"PATCH": "configure"}

    def patch(self, request, code):
        data = ModuleSwitchSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            row = services.set_module_enabled(_tenant(request), code, data.validated_data["enabled"], actor=request.user)
        except ValidationError as exc:
            return Response({"detail": "; ".join(exc.messages), "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"code": row.module, "entitled": row.entitled, "enabled": row.is_active})
