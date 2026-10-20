"""URLs for the platform site (public schema): Super Admin and platform pages."""
from django.contrib import admin
from django.urls import path

from apps.core.views import health

urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
]
