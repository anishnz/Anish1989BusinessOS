"""URLs for tenant sites (for example gorkhabutchery.<platform-domain>)."""
from .urls_shared import shared_urlpatterns

urlpatterns = [
    *shared_urlpatterns,
]
