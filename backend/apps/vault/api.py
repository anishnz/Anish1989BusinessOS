"""
Integrations API. Secrets can be sent in, never read out.

GET    /api/integrations/providers/               what can be connected            view
GET    /api/integrations/connections/             my connections (masked)          view
POST   /api/integrations/connections/             add a connection                 manage
GET    /api/integrations/connections/<id>/        one connection (masked)          view
PATCH  /api/integrations/connections/<id>/        change label/settings/secrets    configure (+ manage for secrets)
DELETE /api/integrations/connections/<id>/        remove                           manage
POST   /api/integrations/connections/<id>/test/   test connection                  configure
POST   /api/integrations/connections/<id>/disable/ {"disabled": true|false}        configure
"""
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from . import access, providers, services
from .models import Connection

METHOD_ACTION = {"GET": "view", "HEAD": "view", "OPTIONS": "view", "POST": "manage", "PATCH": "configure", "PUT": "configure", "DELETE": "manage"}


class VaultPermission(BasePermission):
    message = "You do not have permission to do this."

    def has_permission(self, request, view):
        action = getattr(view, "vault_actions", {}).get(request.method) or METHOD_ACTION.get(request.method)
        return bool(action) and access.allowed(request._request, action)


def connection_data(conn: Connection) -> dict:
    """Everything about a connection except secret values."""
    provider = providers.PROVIDERS.get(conn.provider)
    return {
        "id": conn.pk,
        "provider": conn.provider,
        "provider_label": provider.label if provider else conn.provider,
        "category": conn.category,
        "label": conn.label,
        "is_backup": conn.is_backup,
        "status": conn.status,
        "config": conn.config,
        "secrets": conn.secret_hints,  # masked, e.g. {"api_key": "••••a9f2"}
        "last_tested_at": conn.last_tested_at,
        "last_test_message": conn.last_test_message,
        "updated_at": conn.updated_at,
    }


class ConnectionInput(serializers.Serializer):
    provider = serializers.CharField(max_length=50, required=False)
    label = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_backup = serializers.BooleanField(required=False)
    config = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=500), required=False)
    secrets = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=4000), required=False, write_only=True)


def _invalid(exc: ValidationError):
    return Response({"detail": "; ".join(exc.messages), "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)


class ProvidersView(APIView):
    permission_classes = [VaultPermission]

    def get(self, request):
        return Response(
            [
                {
                    "code": p.code, "label": p.label, "category": p.category, "available": p.available, "help": p.help,
                    "docs_url": p.docs_url,
                    "secret_fields": [{"name": f.name, "label": f.label, "required": f.required, "help": f.help} for f in p.secret_fields],
                    "config_fields": [{"name": f.name, "label": f.label, "required": f.required, "help": f.help, "default": f.default} for f in p.config_fields],
                }
                for p in providers.PROVIDERS.values()
            ]
        )


class ConnectionListView(APIView):
    permission_classes = [VaultPermission]

    def get(self, request):
        return Response([connection_data(c) for c in Connection.objects.all()])

    def post(self, request):
        data = ConnectionInput(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        try:
            conn = services.create_connection(
                provider_code=d.get("provider", ""), label=d.get("label", ""), config=d.get("config", {}),
                secrets=d.get("secrets", {}), is_backup=d.get("is_backup", False), actor=request.user,
            )
        except ValidationError as exc:
            return _invalid(exc)
        return Response(connection_data(conn), status=status.HTTP_201_CREATED)


class ConnectionDetailView(APIView):
    permission_classes = [VaultPermission]

    def get(self, request, pk):
        return Response(connection_data(get_object_or_404(Connection, pk=pk)))

    def patch(self, request, pk):
        conn = get_object_or_404(Connection, pk=pk)
        data = ConnectionInput(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        secrets = {k: v for k, v in d.get("secrets", {}).items() if v}
        if secrets and not access.allowed(request._request, "manage"):
            return Response({"detail": "Changing secret values needs the 'Manage integrations' permission.", "code": "permission_denied"}, status=status.HTTP_403_FORBIDDEN)
        try:
            conn = services.update_connection(conn, label=d.get("label"), config=d.get("config"), secrets=secrets, is_backup=d.get("is_backup"), actor=request.user)
        except ValidationError as exc:
            return _invalid(exc)
        return Response(connection_data(conn))

    def delete(self, request, pk):
        services.delete_connection(get_object_or_404(Connection, pk=pk), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConnectionTestView(APIView):
    permission_classes = [VaultPermission]
    vault_actions = {"POST": "configure"}

    def post(self, request, pk):
        conn = get_object_or_404(Connection, pk=pk)
        result = services.test_connection(conn, actor=request.user)
        conn.refresh_from_db()
        return Response({"ok": result.ok, "message": result.message, "connection": connection_data(conn)})


class ConnectionDisableView(APIView):
    permission_classes = [VaultPermission]
    vault_actions = {"POST": "configure"}

    def post(self, request, pk):
        conn = services.set_disabled(get_object_or_404(Connection, pk=pk), bool(request.data.get("disabled", True)), actor=request.user)
        return Response(connection_data(conn))
