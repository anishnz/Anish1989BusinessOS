"""
Finds the business from the web address, and sends visitors on an extra
address to the business's main address.

Replaces django-tenants' TenantMainMiddleware (it must stay first in MIDDLEWARE):
- host names are matched without case and without a trailing dot;
- `www.` is removed for matching, as the library does;
- a GET or HEAD request on an address that is not the main one is sent to
  the main address with a temporary (302) redirect, keeping the path and query.
  Temporary on purpose: browsers remember permanent redirects for a long time,
  which would break a business that changes back to an earlier address.
- Webhooks, the API, health checks and static files are never redirected, so
  services such as the WhatsApp webhook keep working on an old address.
"""
from django.core.exceptions import DisallowedHost
from django.db import connection
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.http.request import split_domain_port
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_tenant_domain_model, remove_www

NEVER_REDIRECT = ("/webhooks/", "/api/", "/health/", "/static/")


def request_host(request) -> tuple[str, str]:
    """(host name in lower case without the port, ':port' or '')."""
    name, port = split_domain_port(request.get_host())  # lower case, trailing dot removed
    return name, (f":{port}" if port else "")


class TenantRoutingMiddleware(TenantMainMiddleware):
    def process_request(self, request):
        connection.set_schema_to_public()
        try:
            name, port = request_host(request)
        except DisallowedHost:
            return HttpResponseNotFound()
        hostname = remove_www(name)

        domain_model = get_tenant_domain_model()
        domain = domain_model.objects.select_related("tenant").filter(domain=hostname).first()
        if domain is None:
            return self.no_tenant_found(request, hostname)

        tenant = domain.tenant
        tenant.domain_url = hostname
        request.tenant = tenant
        connection.set_tenant(tenant)
        self.setup_url_routing(request)

        if (not domain.is_primary or name != hostname) and request.method in ("GET", "HEAD") \
                and not request.path.startswith(NEVER_REDIRECT):
            main = domain_model.objects.filter(tenant=tenant, is_primary=True).values_list("domain", flat=True).first()
            if main and main != name:
                return HttpResponseRedirect(f"{request.scheme}://{main}{port}{request.get_full_path()}")
        return None
