"""
Scheduled jobs (Celery beat, see CELERY_BEAT_SCHEDULE in settings):
- heartbeat every 5 minutes: proves the scheduler and a worker run;
- the system checks every hour, for the platform and every business.
"""
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from .checks import HEARTBEAT_KEY


@shared_task(name="health.heartbeat", ignore_result=True)
def heartbeat():
    with schema_context(get_public_schema_name()):
        cache.set(HEARTBEAT_KEY, timezone.now().isoformat(), timeout=24 * 3600)


@shared_task(name="health.scheduled_checks", ignore_result=True)
def scheduled_checks():
    from .services import run_everywhere

    return run_everywhere()
