"""
Run a job in every business that may use the system (task 2.7).

Used by scheduled jobs (Celery beat) that work per business: the daily owner
summary and star feedback. Suspended or expired businesses, and businesses
without the needed modules, are skipped. One business failing never stops the
others.
"""
from __future__ import annotations

import logging
from typing import Callable

from django_tenants.utils import get_public_schema_name, schema_context

log = logging.getLogger(__name__)


def for_each_business(job: Callable[[], object], *, modules: tuple[str, ...] = ()) -> dict:
    from apps.health.checks import businesses
    from apps.licensing.services import is_access_allowed, module_is_active

    results = {}
    with schema_context(get_public_schema_name()):
        tenants = list(businesses())
    for tenant in tenants:
        if not is_access_allowed(tenant) or not all(module_is_active(m, tenant) for m in modules):
            results[tenant.schema_name] = "not run"  # suspended, expired or a module switched off
            continue
        with schema_context(tenant.schema_name):
            try:
                results[tenant.schema_name] = job()
            except Exception:  # noqa: BLE001 - one business must not stop the others
                log.exception("Scheduled job failed for %s", tenant.schema_name)
                results[tenant.schema_name] = "error"
    return results
