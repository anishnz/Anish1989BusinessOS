from django.urls import path

from . import api, views

app_name = "vault"

# Settings pages: /settings/integrations/...
web_urlpatterns = [
    path("", views.connection_list, name="list"),
    path("add/<slug:provider_code>/", views.connection_add, name="add"),
    path("<int:pk>/edit/", views.connection_edit, name="edit"),
    path("<int:pk>/test/", views.connection_test, name="test"),
    path("<int:pk>/toggle/", views.connection_toggle, name="toggle"),
    path("<int:pk>/delete/", views.connection_delete, name="delete"),
]

# JSON API: /api/integrations/...
api_urlpatterns = [
    path("providers/", api.ProvidersView.as_view(), name="api_providers"),
    path("connections/", api.ConnectionListView.as_view(), name="api_connections"),
    path("connections/<int:pk>/", api.ConnectionDetailView.as_view(), name="api_connection"),
    path("connections/<int:pk>/test/", api.ConnectionTestView.as_view(), name="api_connection_test"),
    path("connections/<int:pk>/disable/", api.ConnectionDisableView.as_view(), name="api_connection_disable"),
]
