"""
Backups for the current site (the platform, or one business):

- run_backup: pg_dump -> encrypted file in BACKUP_DIR -> copy to Google Drive
  -> remove old copies (retention.py).
- run_restore_test: take the newest backup (from Google Drive when there is a
  copy there), open it, check every checksum, load it into a temporary
  database and compare every table's row count with the counts taken at
  backup time.

The platform's backup holds the whole database (every business) and is
encrypted with BACKUP_ENCRYPTION_KEYS. A business's backup holds only its own
data and is encrypted with its own passphrase; it exists to put a copy in the
business's own Google Drive.

Runs happen in the background worker (tasks.py). Messages are plain words;
technical errors go to the server log only.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import send_mail
from django.db import connection, transaction
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from apps.audit.services import audit
from apps.health.services import alert_recipients, current_tenant, on_platform
from apps.vault import crypto
from apps.vault.models import Connection

from . import dbtools, gdrive, keys, retention
from .fileformat import EXTENSION, BackupFileError, extract_archive, sha256_file, write_archive
from .models import BackupRun, BackupSettings

log = logging.getLogger(__name__)
DONE = (BackupRun.Status.OK, BackupRun.Status.WARNING, BackupRun.Status.FAILED)
ACTIVE = (BackupRun.Status.QUEUED, BackupRun.Status.RUNNING)
STUCK_AFTER = timezone.timedelta(hours=4)
RETRY_FAILED_AFTER = timezone.timedelta(hours=1)
BUSINESS_LOCAL_KEEP = 1  # a business's own backup is kept on the server only until the next one
LOCK_KEY = "backups:lock"


class NotSetUp(Exception):
    pass


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
def site_code() -> str:
    return "platform" if on_platform() else connection.schema_name


def site_name() -> str:
    if on_platform():
        return "the platform"
    tenant = current_tenant()
    return tenant.name if tenant else connection.schema_name


def site_settings() -> BackupSettings:
    obj, _ = BackupSettings.objects.get_or_create(pk=1)
    return obj


def default_folder_name() -> str:
    return "Anish1989 Backups - Platform" if on_platform() else f"Anish1989 Backups - {site_name()}"[:120]


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def local_dir() -> Path:
    sub = Path("platform") if on_platform() else Path("businesses") / connection.schema_name
    return _private_dir(Path(settings.BACKUP_DIR) / sub)


def work_dir() -> str:
    return tempfile.mkdtemp(prefix="work-", dir=_private_dir(Path(settings.BACKUP_DIR) / "tmp"))


# ---------------------------------------------------------------------------
# Passphrase (business sites)
# ---------------------------------------------------------------------------
def _passphrase_aad() -> bytes:
    return f"{connection.schema_name}:backup-passphrase".encode()


@transaction.atomic
def set_passphrase(passphrase: str, *, actor=None) -> None:
    if on_platform():
        raise ValidationError("Platform backups use the BACKUP_ENCRYPTION_KEYS key, not a passphrase.")
    keys.check_passphrase(passphrase)
    s = site_settings()
    had_one = s.has_passphrase
    sealed = crypto.seal(passphrase.encode(), _passphrase_aad())
    s.passphrase_kid, s.passphrase_wrapped_key, s.passphrase_key_nonce = sealed.kid, sealed.wrapped_key, sealed.key_nonce
    s.passphrase_nonce, s.passphrase_ciphertext = sealed.nonce, sealed.ciphertext
    s.passphrase_set_at = timezone.now()
    s.passphrase_set_by_email = getattr(actor, "email", "") or ""
    s.save()
    audit("backup.passphrase_changed" if had_one else "backup.passphrase_set", target_type="backups.settings", target_id="1", actor=actor)


def read_passphrase() -> str | None:
    s = site_settings()
    if not s.has_passphrase:
        return None
    sealed = crypto.Sealed(s.passphrase_kid, s.passphrase_wrapped_key, s.passphrase_key_nonce, s.passphrase_nonce, s.passphrase_ciphertext)
    return crypto.open_sealed(sealed, _passphrase_aad()).decode()


def _source():
    if on_platform():
        return keys.platform_source()
    passphrase = read_passphrase()
    if not passphrase:
        raise NotSetUp("Set a backup passphrase first.")
    from .fileformat import KeySource

    return KeySource(passphrase=passphrase)


def _open_keys() -> dict:
    return {"keys": keys.platform_keys()} if on_platform() else {"passphrase": read_passphrase()}


# ---------------------------------------------------------------------------
# Google Drive connection (stored in the vault, see google_connect.py)
# ---------------------------------------------------------------------------
def drive_connection() -> Connection | None:
    return Connection.objects.filter(provider="google_drive").exclude(status=Connection.Status.DISABLED).order_by("id").first()


def drive_account(conn: Connection) -> gdrive.Account:
    from apps.vault.services import read_secrets

    secrets = read_secrets(conn)
    return gdrive.Account(conn.config.get("client_id", ""), secrets.get("client_secret", ""), secrets.get("refresh_token", ""))


def is_set_up() -> bool:
    """Platform: always (backups stay on the server). Business: Google Drive connected and a passphrase set."""
    if on_platform():
        return True
    return drive_connection() is not None and site_settings().has_passphrase


@transaction.atomic
def save_drive_connection(*, client_id: str, client_secret: str, refresh_token: str, email: str, actor=None) -> Connection:
    from apps.vault.services import create_connection

    old = list(Connection.objects.filter(provider="google_drive"))
    for conn in old:
        conn.delete()
    conn = create_connection(
        provider_code="google_drive", label=f"Google Drive ({email})"[:100] if email else "Google Drive",
        config={"client_id": client_id, "account_email": email},
        secrets={"client_secret": client_secret, "refresh_token": refresh_token}, actor=actor, connect_page="backups",
    )
    Connection.objects.filter(pk=conn.pk).update(status=Connection.Status.CONNECTED, last_tested_at=timezone.now(),
                                                 last_test_message=f"Connected to Google Drive ({email}).")
    s = site_settings()
    s.drive_paused_reason = ""
    if not s.drive_folder_name:
        s.drive_folder_name = default_folder_name()
    if old:  # a new Google account cannot see the old account's folder
        s.drive_folder_id = ""
    s.save()
    audit("backup.drive_connected", target=conn, actor=actor, metadata={"account": email, "replaced": len(old)})
    return conn


def prepare_folder(conn: Connection, token: str | None = None) -> str:
    """Create (or find) the backup folder in Google Drive and remember its id."""
    s = site_settings()
    token = token or gdrive.access_token(drive_account(conn))
    folder = gdrive.ensure_folder(token, s.drive_folder_id, s.drive_folder_name or default_folder_name())
    if folder != s.drive_folder_id:
        s.drive_folder_id = folder
        s.save(update_fields=["drive_folder_id", "updated_at"])
    return folder


@transaction.atomic
def disconnect_drive(*, actor=None) -> bool:
    conns = list(Connection.objects.filter(provider="google_drive"))
    if not conns:
        return False
    for conn in conns:
        try:
            gdrive.revoke(drive_account(conn).refresh_token)
        except crypto.VaultError:
            pass
        audit("backup.drive_disconnected", target=conn, actor=actor, metadata={"account": conn.config.get("account_email", "")})
        conn.delete()
    s = site_settings()
    s.drive_folder_id = ""
    s.drive_paused_reason = ""
    s.save()
    return True


def _pause_drive(conn: Connection, reason: str) -> bool:
    """Stop Drive copies until someone connects again. True if this is new."""
    s = site_settings()
    new = s.drive_paused_reason != reason
    s.drive_paused_reason = reason[:300]
    s.save(update_fields=["drive_paused_reason", "updated_at"])
    Connection.objects.filter(pk=conn.pk).update(status=Connection.Status.FAILED, last_tested_at=timezone.now(), last_test_message=reason[:300])
    if new:
        audit("backup.drive_paused", target=conn, outcome="failed", metadata={"reason": reason})
    return new


@transaction.atomic
def update_settings(*, every_hours: int | None = None, folder_name: str | None = None, actor=None) -> BackupSettings:
    s = site_settings()
    changed = {}
    if every_hours is not None:
        if every_hours not in dict(BackupSettings.EVERY_HOURS_CHOICES):
            raise ValidationError("Choose every 6 hours, every 12 hours or once a day.")
        if every_hours != s.every_hours:
            changed["every_hours"] = [s.every_hours, every_hours]
            s.every_hours = every_hours
    if folder_name is not None:
        folder_name = " ".join(folder_name.split())[:120]
        if not folder_name:
            raise ValidationError("Enter a folder name.")
        if any(ch in folder_name for ch in "/\\'\""):
            raise ValidationError("The folder name cannot contain / \\ ' or \".")
        if folder_name != s.drive_folder_name:
            changed["folder_name"] = [s.drive_folder_name, folder_name]
            s.drive_folder_name = folder_name
            s.drive_folder_id = ""  # a new folder is made on the next copy
    if changed:
        s.save()
        audit("backup.settings_changed", target_type="backups.settings", target_id="1", actor=actor, metadata=changed)
    return s


# ---------------------------------------------------------------------------
# Status (for the page, the API and "Check system")
# ---------------------------------------------------------------------------
def latest(kind: str, *, statuses=DONE) -> BackupRun | None:
    return BackupRun.objects.filter(kind=kind, status__in=statuses).order_by("-queued_at", "-id").first()


def latest_good_backup() -> BackupRun | None:
    return BackupRun.objects.filter(kind=BackupRun.Kind.BACKUP, status__in=[BackupRun.Status.OK, BackupRun.Status.WARNING]).order_by("-queued_at", "-id").first()


def active_run() -> BackupRun | None:
    run = BackupRun.objects.filter(status__in=ACTIVE).order_by("-queued_at").first()
    if run and timezone.now() - run.queued_at > STUCK_AFTER:
        BackupRun.objects.filter(pk=run.pk).update(status=BackupRun.Status.FAILED, finished_at=timezone.now(),
                                                   message="This run did not finish (the worker may have stopped).")
        return None
    return run


def next_backup_due():
    last = latest(BackupRun.Kind.BACKUP)
    if last is None:
        return timezone.now()
    if last.status == BackupRun.Status.FAILED:
        return last.queued_at + RETRY_FAILED_AFTER
    return last.queued_at + timezone.timedelta(hours=site_settings().every_hours)


def next_restore_test_due():
    if latest_good_backup() is None:
        return None
    last = latest(BackupRun.Kind.RESTORE_TEST)
    if last is None:
        return timezone.now()
    if last.status == BackupRun.Status.FAILED:
        return last.queued_at + timezone.timedelta(days=1)
    return last.queued_at + timezone.timedelta(days=settings.BACKUP_RESTORE_TEST_EVERY_DAYS)


# ---------------------------------------------------------------------------
# Queue (button) and run (worker)
# ---------------------------------------------------------------------------
def queue(kind: str, *, trigger: str = BackupRun.Trigger.BUTTON, user=None) -> BackupRun:
    if active_run() is not None:
        raise ValidationError("A backup or restore test is already running. Wait until it has finished.")
    if not is_set_up():
        raise ValidationError("Connect Google Drive and set a backup passphrase first.")
    if kind == BackupRun.Kind.RESTORE_TEST and latest_good_backup() is None:
        raise ValidationError("There is no backup to test yet. Make a backup first.")
    run = BackupRun.objects.create(kind=kind, trigger=trigger, queued_at=timezone.now(), run_by_email=getattr(user, "email", "") or "")
    audit(f"backup.{'restore_test' if kind == BackupRun.Kind.RESTORE_TEST else 'backup'}_requested", target_type="backups.run",
          target_id=str(run.pk), actor=user)
    schema = connection.schema_name

    def start():
        from .tasks import run_task

        run_task.delay(schema, run.pk)

    transaction.on_commit(start)
    return run


def execute(run: BackupRun) -> BackupRun:
    """Do a queued run now (in the worker)."""
    if not cache.add(LOCK_KEY, run.pk, timeout=int(STUCK_AFTER.total_seconds())):
        _finish(run, BackupRun.Status.FAILED, "Another backup or restore test was running at the same time.")
        return run
    try:
        run.status, run.started_at = BackupRun.Status.RUNNING, timezone.now()
        run.save(update_fields=["status", "started_at"])
        try:
            if run.kind == BackupRun.Kind.BACKUP:
                status, message = _backup(run)
            else:
                status, message = _restore_test(run)
        except (NotSetUp, dbtools.DatabaseToolError, BackupFileError, gdrive.DriveError, ImproperlyConfigured, crypto.VaultError) as exc:
            status, message = BackupRun.Status.FAILED, str(exc)
        except Exception:  # noqa: BLE001 - always record the run
            log.exception("Backup run %s failed", run.pk)
            status, message = BackupRun.Status.FAILED, "The run failed because of an unexpected error. Details are in the server log."
        _finish(run, status, message)
    finally:
        cache.delete(LOCK_KEY)
    return run


def _finish(run: BackupRun, status: str, message: str) -> None:
    previous = (BackupRun.objects.filter(kind=run.kind, status__in=DONE).exclude(pk=run.pk).order_by("-queued_at", "-id").first())
    run.status, run.message, run.finished_at = status, message[:500], timezone.now()
    run.started_at = run.started_at or run.finished_at
    run.save()
    action = "backup.made" if run.kind == BackupRun.Kind.BACKUP else "backup.restore_tested"
    audit(action, target_type="backups.run", target_id=str(run.pk), target_repr=f"{run.get_kind_display()}: {status}",
          outcome="failed" if status == BackupRun.Status.FAILED else "success",
          metadata={"trigger": run.trigger, "by": run.run_by_email, "status": status, "size": run.size_bytes,
                    "drive": run.drive_status, "tables": run.details.get("tables"), "rows": run.details.get("rows")})
    newly_failed = status == BackupRun.Status.FAILED and (previous is None or previous.status != BackupRun.Status.FAILED)
    if run.trigger == BackupRun.Trigger.SCHEDULE and (newly_failed or run.details.get("drive_newly_paused")):
        run.alert_sent = send_alert(run)
        run.save(update_fields=["alert_sent"])


def send_alert(run: BackupRun) -> bool:
    recipients = alert_recipients()
    if not recipients:
        return False
    from apps.tenants.domains import main_address, site_url

    tenant = current_tenant()
    link = site_url(main_address(tenant), None, "/backups/") if tenant else ""
    what = "backup" if run.kind == BackupRun.Kind.BACKUP else "restore test"
    when = timezone.localtime(run.queued_at)
    drive = run.details.get("drive_error", "")
    body = (
        f"The automatic {what} of {site_name()} at {when:%H:%M on %d %b %Y} needs attention:\n\n{run.message}\n"
        + (f"\nGoogle Drive: {drive}\n" if drive and drive not in run.message else "")
        + f"\nOpen Backups: {link}\n\nYou get this email when the problem starts. It is not sent again until it is fixed."
    )
    try:
        send_mail(f"{what.capitalize()} needs attention: {site_name()}", body, None, recipients)
    except Exception:  # noqa: BLE001 - the alert must not break the run
        log.exception("Backup alert email could not be sent")
        return False
    audit("backup.alert_sent", target_type="backups.run", target_id=str(run.pk), metadata={"recipients": len(recipients)})
    return True


# ---------------------------------------------------------------------------
# Making a backup
# ---------------------------------------------------------------------------
def _media_files() -> tuple[list[tuple[str, str]], int]:
    root = Path(settings.MEDIA_ROOT)
    base = root if on_platform() else root / connection.schema_name
    files, total = [], 0
    if base.is_dir():
        for path in sorted(p for p in base.rglob("*") if p.is_file() and not p.is_symlink()):
            files.append((f"media/{path.relative_to(base).as_posix()}", str(path)))
            total += path.stat().st_size
    return files, total


def _backup(run: BackupRun) -> tuple[str, str]:
    source = _source()
    started = timezone.localtime(run.started_at)
    # A short random part keeps names unique even for two backups in the same second.
    name = f"{site_code()}-{started:%Y-%m-%d-%H%M%S}-{secrets.token_hex(2)}{EXTENSION}"
    final = local_dir() / name
    work = work_dir()
    try:
        dump_path = os.path.join(work, "database.dump")
        tables = dbtools.dump(dump_path, schema=None if on_platform() else connection.schema_name)
        media, media_bytes = _media_files()
        manifest = {
            "format": 1, "kind": "platform" if on_platform() else "business", "site": site_code(), "site_name": "Platform" if on_platform() else site_name(),
            "schema": None if on_platform() else connection.schema_name,
            "created_at": run.started_at.isoformat(), "app_version": os.environ.get("APP_VERSION", ""),
            "postgres_version": dbtools.server_major_version(),
            "database": {"file": "database.dump", "sha256": sha256_file(dump_path), "size": os.path.getsize(dump_path)},
            "tables": tables, "media": {"files": len(media), "bytes": media_bytes},
        }
        partial = final.with_name(final.name + ".partial")
        with open(partial, "wb") as out:
            os.chmod(partial, 0o600)
            write_archive(out, source, info={"kind": manifest["kind"], "site": site_code(), "created_at": manifest["created_at"]},
                          manifest=manifest, files=[("database.dump", dump_path), *media])
        os.replace(partial, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        for leftover in local_dir().glob("*.partial"):
            leftover.unlink(missing_ok=True)
    run.file_name, run.size_bytes, run.sha256, run.kept_locally = name, final.stat().st_size, sha256_file(str(final)), True
    run.details = {"tables": len(tables), "rows": sum(tables.values()), "media_files": len(media)}
    run.save()

    _copy_to_drive(run, final)
    run.details["cleanup"] = cleanup()
    run.save()

    size = filesizeformat(run.size_bytes)
    summary = f"Backup made: {size}, {len(tables)} tables, {sum(tables.values()):,} rows."
    if run.drive_status == BackupRun.Drive.UPLOADED:
        return BackupRun.Status.OK, f"{summary} Copied to Google Drive."
    reason = run.details.get("drive_error", "")
    if run.drive_status == BackupRun.Drive.NOT_SET_UP:
        return BackupRun.Status.OK, f"{summary} Kept on the server (no Google Drive copy is set up)."
    # A business backup exists to put a copy in its Google Drive, so a failed copy is a failed backup.
    status = BackupRun.Status.WARNING if on_platform() else BackupRun.Status.FAILED
    return status, f"{summary} Not copied to Google Drive: {reason}"


def _copy_to_drive(run: BackupRun, path: Path) -> None:
    conn = drive_connection()
    s = site_settings()
    if conn is None:
        run.drive_status = BackupRun.Drive.NOT_SET_UP
        return
    if s.drive_paused_reason:
        run.drive_status = BackupRun.Drive.PAUSED
        run.details["drive_error"] = f"Paused: {s.drive_paused_reason}"
        return
    try:
        token = gdrive.access_token(drive_account(conn))
        folder = prepare_folder(conn, token)
        uploaded = gdrive.upload(token, folder, str(path), run.file_name)
    except gdrive.DriveAccessRemoved as exc:
        run.drive_status = BackupRun.Drive.PAUSED
        run.details["drive_error"] = str(exc)
        run.details["drive_newly_paused"] = _pause_drive(conn, str(exc))
        return
    except (gdrive.DriveError, crypto.VaultError) as exc:
        run.drive_status = BackupRun.Drive.FAILED
        run.details["drive_error"] = str(exc)
        return
    run.drive_status, run.drive_file_id = BackupRun.Drive.UPLOADED, uploaded["id"]
    Connection.objects.filter(pk=conn.pk).update(status=Connection.Status.CONNECTED, last_tested_at=timezone.now(),
                                                 last_test_message="Backup copied to Google Drive.")


def cleanup() -> dict:
    """Remove old copies on the server and in Google Drive (see retention.py). Never fails the backup."""
    now = timezone.now()
    rules = {"all_days": settings.BACKUP_KEEP_ALL_DAYS, "daily_days": settings.BACKUP_KEEP_DAILY_DAYS, "monthly": settings.BACKUP_KEEP_MONTHLY}
    result = {"server": 0, "drive": 0}
    local = list(BackupRun.objects.filter(kind=BackupRun.Kind.BACKUP, kept_locally=True).order_by("-queued_at", "-id"))
    if on_platform():
        keep = retention.to_keep([(r.pk, r.queued_at) for r in local], now=now, **rules)
    else:
        keep = {r.pk for r in local[:BUSINESS_LOCAL_KEEP]}
    for r in local:
        if r.pk not in keep:
            (local_dir() / r.file_name).unlink(missing_ok=True)
            BackupRun.objects.filter(pk=r.pk).update(kept_locally=False)
            result["server"] += 1
    conn, s = drive_connection(), site_settings()
    if conn and s.drive_folder_id and not s.drive_paused_reason:
        try:
            token = gdrive.access_token(drive_account(conn))
            files = gdrive.list_backups(token, s.drive_folder_id, EXTENSION)
            parsed = [(f["id"], timezone.datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00"))) for f in files]
            keep = retention.to_keep(parsed, now=now, **rules)
            for file_id, _ in parsed:
                if file_id not in keep:
                    gdrive.delete(token, file_id)
                    result["drive"] += 1
            if result["drive"]:
                BackupRun.objects.filter(drive_file_id__in=[f for f, _ in parsed if f not in keep]).update(drive_file_id="")
        except (gdrive.DriveError, crypto.VaultError, KeyError, ValueError) as exc:
            log.warning("Removing old Google Drive copies failed: %s", exc)
            result["drive_error"] = str(exc)[:200]
    return result


# ---------------------------------------------------------------------------
# Restore test
# ---------------------------------------------------------------------------
def _fetch(backup: BackupRun, work: str, run: BackupRun) -> str:
    """The backup file: downloaded from Google Drive when there is a copy there, else the server copy."""
    conn = drive_connection()
    if backup.drive_file_id and conn and not site_settings().drive_paused_reason:
        path = os.path.join(work, backup.file_name)
        try:
            gdrive.download(gdrive.access_token(drive_account(conn)), backup.drive_file_id, path)
            run.details["source"] = "Google Drive"
            return path
        except gdrive.DriveError as exc:
            run.details["drive_error"] = str(exc)
            if not backup.kept_locally:
                raise
    if backup.kept_locally and (local_dir() / backup.file_name).is_file():
        run.details["source"] = "this server"
        return str(local_dir() / backup.file_name)
    raise BackupFileError("The newest backup is no longer available on the server or in Google Drive.")


def _restore_test(run: BackupRun) -> tuple[str, str]:
    backup = latest_good_backup()
    if backup is None:
        raise BackupFileError("There is no backup to test yet.")
    run.tested_backup = backup
    run.details = {}
    made = timezone.localtime(backup.queued_at)
    label = f"the backup from {made:%d %b %Y, %H:%M}"
    dbtools.drop_old_test_databases()
    work = work_dir()
    try:
        path = _fetch(backup, work, run)
        if sha256_file(path) != backup.sha256:
            raise BackupFileError(f"The file of {label} has changed since it was made.")
        folder = os.path.join(work, "opened")
        with open(path, "rb") as fh:
            manifest = extract_archive(fh, folder, **_open_keys())
        dump_path = os.path.join(folder, "database.dump")
        if not os.path.isfile(dump_path) or sha256_file(dump_path) != manifest["database"]["sha256"]:
            raise BackupFileError(f"The database copy inside {label} does not match its checksum.")
        media_found = sum(1 for p in Path(folder, "media").rglob("*") if p.is_file()) if Path(folder, "media").is_dir() else 0
        if media_found != manifest["media"]["files"]:
            raise BackupFileError(f"{label.capitalize()} should hold {manifest['media']['files']} uploaded files but has {media_found}.")
        dbtools.check_archive(dump_path)
        expected = manifest["tables"]
        source = run.details.get("source", "")
        try:
            with dbtools.restored_copy(dump_path) as cur:
                found = dbtools.count_rows(cur, [manifest["schema"]] if manifest.get("schema") else None)
        except dbtools.CannotCreateDatabase as exc:
            dbtools.read_all_data(dump_path)
            run.details.update({"tables": len(expected), "rows": sum(expected.values()), "loaded": False})
            return BackupRun.Status.WARNING, (
                f"{label.capitalize()} (from {source}) opens and all its data can be read, but it was not loaded into a test "
                f"database: {exc} Give the database user the CREATEDB right for a full test."
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    missing = sorted(set(expected) - set(found))
    different = sorted(t for t in expected if t in found and found[t] != expected[t])
    run.details.update({"tables": len(found), "rows": sum(found.values()), "loaded": True,
                        "missing": missing[:20], "different": [[t, expected[t], found[t]] for t in different[:20]]})
    if missing or different:
        return BackupRun.Status.FAILED, (
            f"Restore test of {label} found differences: {len(missing)} missing tables and {len(different)} tables with "
            f"different row counts. See the details below."
        )
    return BackupRun.Status.OK, (
        f"Restore test passed: {label} was taken from {source}, opened, and loaded into a test database. "
        f"All {len(found)} tables and {sum(found.values()):,} rows match."
    )


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def run_due(trigger: str = BackupRun.Trigger.SCHEDULE) -> list[str]:
    """Run the backup and/or restore test of the current site if due. Returns what ran."""
    done = []
    if not is_set_up() or active_run() is not None:
        return done
    if not on_platform() and site_settings().drive_paused_reason:
        return done  # nothing to do until Google Drive is connected again
    if next_backup_due() <= timezone.now():
        run = BackupRun.objects.create(kind=BackupRun.Kind.BACKUP, trigger=trigger, queued_at=timezone.now())
        execute(run)
        done.append(f"backup {run.status}")
    due = next_restore_test_due()
    if due is not None and due <= timezone.now():
        run = BackupRun.objects.create(kind=BackupRun.Kind.RESTORE_TEST, trigger=trigger, queued_at=timezone.now())
        execute(run)
        done.append(f"restore test {run.status}")
    return done


def run_everywhere() -> dict:
    """The platform first (its backup holds every business), then each business that is set up."""
    from django_tenants.utils import get_public_schema_name, schema_context

    from apps.health.checks import businesses
    from apps.licensing.services import is_access_allowed

    summary = {}
    with schema_context(get_public_schema_name()):
        try:
            summary["public"] = run_due()
        except Exception:  # noqa: BLE001
            log.exception("Scheduled platform backup failed")
            summary["public"] = ["error"]
        tenants = list(businesses())
    for tenant in tenants:
        if not is_access_allowed(tenant):
            continue
        with schema_context(tenant.schema_name):
            try:
                summary[tenant.schema_name] = run_due()
            except Exception:  # noqa: BLE001 - one business must not stop the others
                log.exception("Scheduled backup failed for %s", tenant.schema_name)
                summary[tenant.schema_name] = ["error"]
    return summary


def history(limit: int = 20) -> list[BackupRun]:
    return list(BackupRun.objects.select_related("tested_backup").order_by("-queued_at", "-id")[:limit])


def run_json(run: BackupRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.pk, "kind": run.kind, "trigger": run.trigger, "status": run.status, "run_by": run.run_by_email,
        "queued_at": run.queued_at, "started_at": run.started_at, "finished_at": run.finished_at, "seconds": run.seconds,
        "file_name": run.file_name, "size_bytes": run.size_bytes, "drive_status": run.drive_status, "message": run.message,
        "details": {k: v for k, v in run.details.items() if k in ("tables", "rows", "media_files", "source", "loaded", "missing", "different", "cleanup", "drive_error")},
        "tested_backup": run.tested_backup_id,
    }


def describe_json() -> str:
    """Debug helper for the management command."""
    return json.dumps({"site": site_code(), "set_up": is_set_up(), "next_backup": str(next_backup_due())}, indent=2)
