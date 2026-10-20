from django.urls import path

from . import api

urlpatterns = [
    path("licence/", api.LicenceView.as_view(), name="tenant_licence"),
    path("modules/", api.ModuleListView.as_view(), name="tenant_modules"),
    path("modules/<slug:code>/", api.ModuleDetailView.as_view(), name="tenant_module"),
]
