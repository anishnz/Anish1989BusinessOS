"""URLs for tenant sites (for example gorkhabutchery.<platform-domain>)."""
from django.contrib import admin
from django.urls import include, path

from apps.accounts import login_as
from apps.core.spa import app_page
from apps.inbox.whatsapp import webhook as whatsapp_webhook
from apps.reports.views import dashboard_page

from .urls_shared import shared_urlpatterns

# Business-only pages and APIs (their data lives only in business schemas).
business_urlpatterns = [
    path("api/products/", include("apps.catalog.urls")),
    path("api/customers/", include("apps.customers.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/inbox/", include("apps.inbox.urls")),
    path("api/ai/", include("apps.ai.urls")),
    path("api/reports/", include("apps.reports.urls")),
    path("dashboard/", admin.site.admin_view(dashboard_page), name="dashboard"),
    path("", include("apps.setup.urls")),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp_webhook"),
    # "Log in as" from the platform's Super Admin (task 1.18)
    path("login-as/", login_as.accept, name="login_as_accept"),
    path("login-as/stop/", login_as.stop, name="login_as_stop"),
    # Staff screens (React). The page holds no data; the API checks every request.
    path("app/", app_page, name="app"),
    path("app/<path:rest>", app_page, name="app_page"),
]

urlpatterns = [
    *business_urlpatterns,
    *shared_urlpatterns,
]
