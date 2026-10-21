"""URL patterns used by both the platform site and every tenant site."""
from django.contrib import admin
from django.urls import include, path

from apps.accounts.urls import api_urlpatterns, password_reset_urlpatterns, web_urlpatterns
from apps.backups.urls import api_urlpatterns as backup_api_urlpatterns
from apps.backups.urls import web_urlpatterns as backup_web_urlpatterns
from apps.tickets.urls import api_urlpatterns as ticket_api_urlpatterns
from apps.tickets.urls import web_urlpatterns as ticket_web_urlpatterns
from apps.core.views import health
from apps.health.urls import api_urlpatterns as check_api_urlpatterns
from apps.health.urls import web_urlpatterns as check_web_urlpatterns
from apps.vault.urls import api_urlpatterns as vault_api_urlpatterns
from apps.vault.urls import web_urlpatterns as vault_web_urlpatterns

shared_urlpatterns = [
    path("health/", health, name="health"),
    *password_reset_urlpatterns,
    path("account/", include((web_urlpatterns, "accounts"))),
    path("api/auth/", include(api_urlpatterns)),
    path("api/rbac/", include("apps.rbac.urls")),
    path("api/tenant/", include("apps.licensing.urls")),
    path("api/integrations/", include(vault_api_urlpatterns)),
    path("settings/integrations/", include((vault_web_urlpatterns, "vault"))),
    *check_web_urlpatterns,
    path("api/system-check/", include(check_api_urlpatterns)),
    *backup_web_urlpatterns,
    path("api/backups/", include(backup_api_urlpatterns)),
    *ticket_web_urlpatterns,
    path("api/tickets/", include(ticket_api_urlpatterns)),
    path("admin/", admin.site.urls),
]
