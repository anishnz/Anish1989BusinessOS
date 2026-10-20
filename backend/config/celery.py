"""Celery app for background jobs (crawls, reports, AI jobs, messaging, backups)."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("businessos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# NOTE: tasks that touch tenant data must run inside the right tenant schema.
# A tenant-aware task base will be added with the first tenant task.
