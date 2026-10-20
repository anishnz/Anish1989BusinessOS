"""Page shown when no business uses the web address (no database access, nothing to leak)."""
from django.http import HttpResponseNotFound
from django.template.loader import render_to_string
from django_tenants.utils import remove_www

from .middleware import request_host


def unknown_address(request):
    name, _ = request_host(request)
    # Rendered without the request: no context processors, sessions or users are touched.
    return HttpResponseNotFound(render_to_string("tenants/unknown_address.html", {"address": remove_www(name)}))
