"""
Roles API for the React frontend.

GET    /api/rbac/me/permissions/          my permission codes (to show/hide menus)
GET    /api/rbac/catalogue/               every permission, grouped by module     roles.view
GET    /api/rbac/roles/                   list roles                              roles.view
POST   /api/rbac/roles/                   create a custom role                    roles.create
GET    /api/rbac/roles/<id>/              one role                                roles.view
PUT    /api/rbac/roles/<id>/permissions/  replace a role's permissions            roles.manage_permissions
DELETE /api/rbac/roles/<id>/              delete a custom role                    roles.delete
POST   /api/rbac/users/<id>/roles/        give a role to a user                   roles.assign
DELETE /api/rbac/users/<id>/roles/<role>/ take a role away                        roles.assign
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import policy, services
from .catalogue import ACTIONS, modules_for
from .models import Role
from .permissions import ModulePermission


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "slug", "name", "description", "is_system", "full_access", "permissions", "user_count"]

    def get_permissions(self, role):
        return sorted(role.permission_codes())

    def get_user_count(self, role):
        return role.assignments.count()


class RoleCreateSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=60)
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    permissions = serializers.ListField(child=serializers.CharField(max_length=80), required=False)


class PermissionListSerializer(serializers.Serializer):
    permissions = serializers.ListField(child=serializers.CharField(max_length=80))


class RoleIdSerializer(serializers.Serializer):
    role_id = serializers.IntegerField()


def _error(exc):
    if isinstance(exc, PermissionDenied):
        return Response({"detail": str(exc), "code": "permission_denied"}, status=status.HTTP_403_FORBIDDEN)
    return Response({"detail": "; ".join(exc.messages), "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)


class MyPermissionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"permissions": sorted(policy.effective_permissions(request.user))})


class CatalogueView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "roles"

    def get(self, request):
        return Response(
            {
                "actions": ACTIONS,
                "modules": [
                    {"code": m.code, "label": m.label, "permissions": [f"{m.code}.{a}" for a in m.actions]}
                    for m in modules_for(connection.schema_name)
                ],
            }
        )


class RoleListView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "roles"

    def get(self, request):
        return Response(RoleSerializer(Role.objects.all(), many=True).data)

    def post(self, request):
        data = RoleCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            role = services.create_role(
                request.user,
                slug=data.validated_data["slug"],
                name=data.validated_data["name"],
                description=data.validated_data.get("description", ""),
                codes=data.validated_data.get("permissions", []),
            )
        except (PermissionDenied, ValidationError) as exc:
            return _error(exc)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "roles"

    def get(self, request, pk):
        return Response(RoleSerializer(get_object_or_404(Role, pk=pk)).data)

    def delete(self, request, pk):
        try:
            services.delete_role(request.user, get_object_or_404(Role, pk=pk))
        except (PermissionDenied, ValidationError) as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RolePermissionsView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "roles"
    permission_actions = {"PUT": "manage_permissions"}

    def put(self, request, pk):
        data = PermissionListSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            role = services.update_role_permissions(request.user, get_object_or_404(Role, pk=pk), data.validated_data["permissions"])
        except (PermissionDenied, ValidationError) as exc:
            return _error(exc)
        return Response(RoleSerializer(role).data)


class UserRolesView(APIView):
    permission_classes = [ModulePermission]
    permission_module = "roles"
    permission_actions = {"GET": "view", "POST": "assign"}

    def get(self, request, user_id):
        user = get_object_or_404(get_user_model(), pk=user_id)
        roles = Role.objects.filter(assignments__user=user)
        return Response({"user_id": user.pk, "roles": RoleSerializer(roles, many=True).data})

    def post(self, request, user_id):
        data = RoleIdSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=user_id)
        role = get_object_or_404(Role, pk=data.validated_data["role_id"])
        try:
            services.assign_role(request.user, user, role)
        except (PermissionDenied, ValidationError) as exc:
            return _error(exc)
        return Response(status=status.HTTP_201_CREATED)


class UserRoleDetailView(APIView):
    """DELETE /api/rbac/users/<user_id>/roles/<role_id>/ removes one role."""

    permission_classes = [ModulePermission]
    permission_module = "roles"
    permission_actions = {"DELETE": "assign"}

    def delete(self, request, user_id, role_id):
        user = get_object_or_404(get_user_model(), pk=user_id)
        role = get_object_or_404(Role, pk=role_id)
        try:
            services.remove_role(request.user, user, role)
        except (PermissionDenied, ValidationError) as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
