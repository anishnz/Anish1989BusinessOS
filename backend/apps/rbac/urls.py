from django.urls import path

from . import api

urlpatterns = [
    path("me/permissions/", api.MyPermissionsView.as_view(), name="rbac_my_permissions"),
    path("catalogue/", api.CatalogueView.as_view(), name="rbac_catalogue"),
    path("roles/", api.RoleListView.as_view(), name="rbac_roles"),
    path("roles/<int:pk>/", api.RoleDetailView.as_view(), name="rbac_role"),
    path("roles/<int:pk>/permissions/", api.RolePermissionsView.as_view(), name="rbac_role_permissions"),
    path("users/<int:user_id>/roles/", api.UserRolesView.as_view(), name="rbac_user_roles"),
    path("users/<int:user_id>/roles/<int:role_id>/", api.UserRoleDetailView.as_view(), name="rbac_user_role"),
]
