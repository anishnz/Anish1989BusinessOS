"""URLs for tenant sites (for example gorkhabutchery.<platform-domain>)."""
from django.contrib import admin
from django.urls import include, path

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
    path("api/reports/", include("apps.reports.urls")),
    path("dashboard/", admin.site.admin_view(dashboard_page), name="dashboard"),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp_webhook"),
    # Staff screens (React). The page holds no data; the API checks every request.
    path("app/", app_page, name="app"),
    path("app/<path:rest>", app_page, name="app_page"),
]

urlpatterns = [
    *business_urlpatterns,
    *shared_urlpatterns,
]
