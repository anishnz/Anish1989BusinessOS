"""URLs for tenant sites (for example gorkhabutchery.<platform-domain>)."""
from django.urls import include, path

from .urls_shared import shared_urlpatterns

# Business-only pages and APIs (their data lives only in business schemas).
business_urlpatterns = [
    path("api/products/", include("apps.catalog.urls")),
    path("api/customers/", include("apps.customers.urls")),
]

urlpatterns = [
    *business_urlpatterns,
    *shared_urlpatterns,
]
