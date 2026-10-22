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
- A business's own domain (task 2.8) is not in DJANGO_ALLOWED_HOSTS. It is
  let in when it is a live custom domain in the database (D-162).
- /internal/tls-allowed/?domain=<name> answers Caddy's "may I get a
  certificate for this name?" (200 yes, 404 no) before any host check. The
  public site never reaches it: the Caddyfile answers /internal/* with 404.
"""
from django.core.exceptions import DisallowedHost
from django.db import connection
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.http.request import split_domain_port
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_tenant_domain_model, remove_www

NEVER_REDIRECT = ("/webhooks/", "/api/", "/health/", "/static/")
TLS_ASK_PATH = "/internal/tls-allowed/"


def tls_answer(request):
    from .custom_domains import tls_allowed

    if request.method != "GET":
        return HttpResponseNotFound()
    return HttpResponse("ok", content_type="text/plain") if tls_allowed(request.GET.get("domain", "")) else HttpResponseNotFound()


def request_host(request) -> tuple[str, str]:
    """(host name in lower case without the port, ':port' or '')."""
    name, port = split_domain_port(request.get_host())  # lower case, trailing dot removed
    return name, (f":{port}" if port else "")


class TenantRoutingMiddleware(TenantMainMiddleware):
    def process_request(self, request):
        connection.set_schema_to_public()
        if request.path == TLS_ASK_PATH:
            return tls_answer(request)
        try:
            name, port = request_host(request)
        except DisallowedHost:
            from .custom_domains import is_live

            raw = request._get_raw_host()
            name, port = split_domain_port(raw)
            if not name or not is_live(name):
                return HttpResponseNotFound()
            request.get_host = lambda raw=raw: raw  # a live custom domain, checked just now against the database
            port = f":{port}" if port else ""
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
