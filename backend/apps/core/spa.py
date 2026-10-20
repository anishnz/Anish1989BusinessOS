"""
Serves the staff screens (React app) at /app/ and every /app/... address.

The page itself holds no data: it loads, asks /api/auth/me/ who is logged in,
and shows the login page if nobody is. All data comes from the API, which
checks permissions on every request.
"""
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

# The app only loads its own files and talks to its own address.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@never_cache
@require_GET
def app_page(request, rest=""):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HttpResponse(
            "<h1>The staff screens are not built yet</h1><p>Run <code>npm ci && npm run build</code> in the frontend folder, "
            "or use the Docker image. The classic admin is at <a href='/admin/'>/admin/</a>.</p>",
            status=503,
        )
    response = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = CSP
    return response
