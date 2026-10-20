"""
Health endpoint used by Docker, the load balancer and monitoring.

It only reports OK / failed per check. It never returns error details,
host names, schema names or other internal information.
The full "Check system" dashboard button (task 1.13) builds on these checks.
"""
import logging
import uuid

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def check_database() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except Exception:  # noqa: BLE001 - report failure, log details privately
        logger.exception("Health check: database failed")
        return False


def check_cache() -> bool:
    key = f"health:{uuid.uuid4().hex}"
    try:
        cache.set(key, "ok", timeout=5)
        ok = cache.get(key) == "ok"
        cache.delete(key)
        return ok
    except Exception:  # noqa: BLE001
        logger.exception("Health check: cache failed")
        return False


@never_cache
@require_GET
def health(request):
    checks = {"database": check_database(), "cache": check_cache()}
    healthy = all(checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "error", "checks": {k: "ok" if v else "failed" for k, v in checks.items()}},
        status=200 if healthy else 503,
    )
