"""The backup lines of "Check system" (task 1.13): backups, Google Drive copy, restore test, and the platform key."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from apps.health.checks import FAILED, NOT_SET_UP, OK, WARNING, Result, _ago

from . import keys, services
from .models import BackupRun

AREA = "Backups"


def _key() -> Result:
    label = "Backup encryption key"
    try:
        kid = next(iter(keys.platform_keys()))
    except ImproperlyConfigured:
        return Result("backup_key", AREA, label, FAILED, "BACKUP_ENCRYPTION_KEYS is not set, so no backups can be made. See the setup guide, “Backups”.")
    if kid == keys.DEV_KEY_ID:
        return Result("backup_key", AREA, label, WARNING, "Development key (made from DJANGO_SECRET_KEY). Set BACKUP_ENCRYPTION_KEYS on a real server.")
    return Result("backup_key", AREA, label, OK, f"Key “{kid}” is set. Keep a copy of it outside the server.")


def _backups() -> Result:
    label = "Backups"
    last = services.latest(BackupRun.Kind.BACKUP)
    good = services.latest_good_backup()
    hours = services.site_settings().every_hours
    every = timedelta(hours=hours)
    if last is None:
        return Result("backups", AREA, label, WARNING, "No backup yet. The first one starts within 15 minutes, or click “Back up now” on the Backups page.")
    if last.status == BackupRun.Status.FAILED:
        return Result("backups", AREA, label, FAILED, f"The last backup ({_ago(last.queued_at)}) failed: {last.message}")
    age = timezone.now() - good.queued_at
    if age > 2 * every + timedelta(hours=1):
        return Result("backups", AREA, label, FAILED, f"The last backup is from {_ago(good.queued_at)}. Backups should run every {hours} hours. Check that the worker and scheduler run.")
    if age > every + timedelta(hours=1):
        return Result("backups", AREA, label, WARNING, f"The last backup is from {_ago(good.queued_at)}, later than planned.")
    return Result("backups", AREA, label, OK, f"Last backup {_ago(good.queued_at)} ({filesizeformat(good.size_bytes)}).")


def _drive() -> Result:
    label = "Copy in Google Drive"
    conn = services.drive_connection()
    s = services.site_settings()
    if conn is None:
        return Result("backups_drive", AREA, label, WARNING, "Backups are only on this server. Connect Google Drive on the Backups page for an off-site copy.")
    if s.drive_paused_reason:
        return Result("backups_drive", AREA, label, FAILED, f"Copies have stopped: {s.drive_paused_reason}")
    last = BackupRun.objects.filter(kind=BackupRun.Kind.BACKUP, status__in=services.DONE).exclude(drive_status=BackupRun.Drive.NOT_SET_UP).order_by("-queued_at").first()
    if last is None:
        return Result("backups_drive", AREA, label, WARNING, f"Connected ({conn.config.get('account_email', '')}), but no backup has been copied yet.")
    if last.drive_status != BackupRun.Drive.UPLOADED:
        return Result("backups_drive", AREA, label, FAILED, f"The last copy ({_ago(last.queued_at)}) failed: {last.details.get('drive_error') or last.message}")
    return Result("backups_drive", AREA, label, OK, f"Last copy {_ago(last.queued_at)} to {conn.config.get('account_email', 'Google Drive')}.")


def _restore() -> Result:
    label = "Restore test"
    last = services.latest(BackupRun.Kind.RESTORE_TEST)
    if last is None:
        return Result("backups_restore", AREA, label, WARNING, "No restore test yet. A backup only counts once a restore from it has worked. Click “Test restore” on the Backups page.")
    if last.status == BackupRun.Status.FAILED:
        return Result("backups_restore", AREA, label, FAILED, f"The last restore test ({_ago(last.queued_at)}) failed: {last.message}")
    if last.status == BackupRun.Status.WARNING:
        return Result("backups_restore", AREA, label, WARNING, last.message)
    if timezone.now() - last.queued_at > timedelta(days=2 * settings.BACKUP_RESTORE_TEST_EVERY_DAYS + 1):
        return Result("backups_restore", AREA, label, WARNING, f"The last restore test was {_ago(last.queued_at)}. It should run every {settings.BACKUP_RESTORE_TEST_EVERY_DAYS} days.")
    return Result("backups_restore", AREA, label, OK, f"Passed {_ago(last.queued_at)}.")


def results() -> list[Result]:
    if services.on_platform():
        return [_key(), _backups(), _drive(), _restore()]
    if not services.is_set_up():
        return [Result("backups", AREA, "Backups", NOT_SET_UP,
                       "Backups to your own Google Drive are not set up. Open Backups to set them up. The platform's own backups include your data.")]
    return [_backups(), _drive(), _restore()]
