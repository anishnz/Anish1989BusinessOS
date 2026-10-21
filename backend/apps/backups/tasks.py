"""
Background jobs for backups (run by the worker):
- backups.scheduled every 15 minutes (CELERY_BEAT_SCHEDULE): runs each site's
  backup when it is due (every 6 hours by default) and the restore test
  (every 7 days by default);
- backups.run: a run started with a button.
"""
from celery import shared_task
from django_tenants.utils import schema_context


@shared_task(name="backups.scheduled", ignore_result=True)
def scheduled():
    from .services import run_everywhere

    return run_everywhere()


@shared_task(name="backups.run", ignore_result=True)
def run_task(schema_name: str, run_id: int):
    from .models import BackupRun
    from .services import execute

    with schema_context(schema_name):
        run = BackupRun.objects.filter(pk=run_id, status=BackupRun.Status.QUEUED).first()
        if run is not None:
            execute(run)
