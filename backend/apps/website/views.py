"""
The public website (task 2.9): "/" on a business's address, plus robots.txt
and sitemap.xml. It uses no cookies and no sessions, and loads no scripts.

The preview (/website/preview/) shows the saved draft to staff who may see
the website editor; the staff app shows it in a frame next to the fields.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

from apps.rbac import policy

from . import content, page

CSP = "default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _main_url(request, path: str = "/") -> str:
    from apps.health.services import current_tenant
    from apps.tenants.domains import main_address, site_url

    tenant = current_tenant()
    host = main_address(tenant) if tenant else ""
    return site_url(host, request, path) if host else ""


def _require_site() -> None:
    if not policy.module_enabled("websites"):  # (the platform site has no website routes at all)
        raise Http404("No website here.")


@require_safe
def home(request):
    _require_site()
    html = render_to_string("website/site.html", page.live_page(_main_url(request)))  # no request: no cookies, no user
    response = HttpResponse(html)
    response["Content-Security-Policy"] = CSP
    response["Cache-Control"] = "public, max-age=300"
    return response


@never_cache
@xframe_options_sameorigin
@require_safe
def preview(request):
    _require_site()
    user = request.user
    if not (user.is_authenticated and policy.has_perm(user, "websites.view")):
        raise PermissionDenied
    html = render_to_string("website/site.html", {**page.build(content.draft_content(), url=_main_url(request)), "preview": True})
    response = HttpResponse(html)
    response["Content-Security-Policy"] = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    return response


@require_safe
def robots(request):
    _require_site()
    body = f"User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /app/\nDisallow: /api/\nSitemap: {_main_url(request, '/sitemap.xml')}\n"
    return HttpResponse(body, content_type="text/plain")


@require_safe
def sitemap(request):
    _require_site()
    version = content.live()
    lastmod = f"<lastmod>{version.published_at:%Y-%m-%d}</lastmod>" if version else ""
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{_main_url(request)}</loc>{lastmod}</url></urlset>\n")
    return HttpResponse(body, content_type="application/xml")
