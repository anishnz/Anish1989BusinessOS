"""URLs for tenant sites (for example gorkhabutchery.<platform-domain>)."""
from django.urls import include, path

from apps.inbox.whatsapp import webhook as whatsapp_webhook

from .urls_shared import shared_urlpatterns

# Business-only pages and APIs (their data lives only in business schemas).
business_urlpatterns = [
    path("api/products/", include("apps.catalog.urls")),
    path("api/customers/", include("apps.customers.urls")),
    path("api/orders/", include("apps.orders.urls")),
    path("api/inbox/", include("apps.inbox.urls")),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp_webhook"),
]

urlpatterns = [
    *business_urlpatterns,
    *shared_urlpatterns,
]
