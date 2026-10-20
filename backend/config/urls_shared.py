"""URL patterns used by both the platform site and every tenant site."""
from django.contrib import admin
from django.urls import include, path

from apps.accounts.urls import api_urlpatterns, password_reset_urlpatterns, web_urlpatterns
from apps.core.views import health

shared_urlpatterns = [
    path("health/", health, name="health"),
    *password_reset_urlpatterns,
    path("account/", include((web_urlpatterns, "accounts"))),
    path("api/auth/", include(api_urlpatterns)),
    path("api/rbac/", include("apps.rbac.urls")),
    path("api/tenant/", include("apps.licensing.urls")),
    path("admin/", admin.site.urls),
]
