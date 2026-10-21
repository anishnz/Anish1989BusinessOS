"""
Backups page and API, on the platform site and on every business site.

/backups/                     status, buttons, settings, history
/backups/google/finish/       end of "Connect Google Drive"
/backups/tool/                the stand-alone tool that opens a backup file
/oauth/google/callback/       (platform site only) Google's return address
GET  /api/backups/            status and the last 20 runs
POST /api/backups/run/        {"kind": "backup" | "restore_test"}

Who: seeing needs Settings - View (business) or Platform settings - View;
buttons and changes need the Configure permission. Connecting or
disconnecting Google Drive and setting the passphrase also need the password.
"""
from pathlib import Path

from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.security import recheck_password
from apps.health.services import on_platform
from apps.rbac import policy

from . import google_connect, keys, services
from .models import BackupRun, BackupSettings

PASSWORD_WRONG = "The password is not correct (or the account is locked for a while after too many tries)."


def _code(action: str) -> str:
    return f"{'platform_settings' if on_platform() else 'settings'}.{action}"


def _require(request, action: str = "view") -> None:
    if not policy.require(request.user, _code(action), request=request):
        raise PermissionDenied


def _can(request, action: str) -> bool:
    return policy.require(request.user, _code(action), request=request)


def _key_info() -> dict:
    if not on_platform():
        return {}
    try:
        kid = next(iter(keys.platform_keys()))
    except ImproperlyConfigured as exc:
        return {"key_problem": str(exc)}
    return {"key_id": kid, "dev_key": kid == keys.DEV_KEY_ID}


def _folder_size() -> int:
    return sum(p.stat().st_size for p in services.local_dir().glob("*.a1989backup") if p.is_file())


def _context(request, **extra) -> dict:
    s = services.site_settings()
    drive = services.drive_connection()
    active = services.active_run()
    return {
        **admin.site.each_context(request),
        "title": "Backups",
        "on_platform": on_platform(),
        "site_name": services.site_name(),
        "settings_row": s,
        "every_choices": BackupSettings.EVERY_HOURS_CHOICES,
        "set_up": services.is_set_up(),
        "drive": drive,
        "has_sign_in_app": google_connect.sign_in_app() is not None,
        "redirect_uri": google_connect.redirect_uri(request),
        "last_backup": services.latest(BackupRun.Kind.BACKUP),
        "last_good": services.latest_good_backup(),
        "last_test": services.latest(BackupRun.Kind.RESTORE_TEST),
        "next_backup": services.next_backup_due() if services.is_set_up() else None,
        "next_test": services.next_restore_test_due() if services.is_set_up() else None,
        "now": timezone.now(),
        "active": active,
        "history": services.history(),
        "can_configure": _can(request, "configure"),
        "default_folder": services.default_folder_name(),
        "server_size": _folder_size(),
        "server_count": BackupRun.objects.filter(kind=BackupRun.Kind.BACKUP, kept_locally=True).count(),
        **_key_info(),
        **extra,
    }


@never_cache
def backups_page(request):
    _require(request)
    if request.method == "POST":
        _require(request, "configure")
        return _post(request)
    google = request.GET.get("google")
    if google == "cancelled":
        messages.warning(request, "Google Drive was not connected (the sign-in was cancelled).")
    return render(request, "backups/backups.html", _context(request))


def _post(request):
    action = request.POST.get("action", "")
    here = reverse("backups")
    try:
        if action in ("backup", "restore_test"):
            kind = BackupRun.Kind.BACKUP if action == "backup" else BackupRun.Kind.RESTORE_TEST
            services.queue(kind, user=request.user)
            messages.success(request, "Started. This page updates by itself until it has finished.")
        elif action == "settings":
            every = request.POST.get("every_hours", "")
            folder = request.POST.get("folder_name")
            services.update_settings(every_hours=int(every) if every.isdigit() else -1, folder_name=folder, actor=request.user)
            messages.success(request, "Backup settings saved.")
        elif action == "passphrase":
            return _passphrase(request)
        elif action == "connect":
            if not recheck_password(request):
                raise ValidationError(PASSWORD_WRONG)
            return HttpResponseRedirect(google_connect.start(request))
        elif action == "disconnect":
            if not recheck_password(request):
                raise ValidationError(PASSWORD_WRONG)
            if services.disconnect_drive(actor=request.user):
                messages.success(request, "Google Drive disconnected. Copies already in the Drive stay there.")
        else:
            messages.error(request, "Unknown action.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect(here)


def _passphrase(request):
    if on_platform():
        raise ValidationError("Platform backups use the BACKUP_ENCRYPTION_KEYS key, not a passphrase.")
    if not recheck_password(request):
        raise ValidationError(PASSWORD_WRONG)
    if request.POST.get("generate"):
        passphrase = keys.generate_passphrase()
    else:
        passphrase = request.POST.get("passphrase", "")
        if passphrase != request.POST.get("passphrase_again", ""):
            raise ValidationError("The two passphrases are not the same.")
    had_one = services.site_settings().has_passphrase
    services.set_passphrase(passphrase, actor=request.user)
    # Shown once, on this response only (never stored in a message or the session).
    response = render(request, "backups/passphrase_saved.html", {
        **admin.site.each_context(request), "title": "Backup passphrase saved", "passphrase": passphrase,
        "generated": bool(request.POST.get("generate")), "changed": had_one,
    })
    response["Cache-Control"] = "no-store"
    return response


@never_cache
def google_finish(request):
    _require(request, "configure")
    try:
        conn = google_connect.finish(request)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("backups")
    try:
        services.prepare_folder(conn)
    except Exception as exc:  # noqa: BLE001 - the connection itself is saved
        messages.warning(request, f"Google Drive connected, but the backup folder could not be made yet ({exc}). It is tried again at the next backup.")
    else:
        messages.success(request, f"Google Drive connected ({conn.config.get('account_email', '')}). Backups are copied to the folder “{services.site_settings().drive_folder_name}”.")
    return redirect("backups")


@never_cache
def google_callback(request):
    """Platform site only (see urls_public). Needs no login: the signed state and the session check protect it."""
    target, problem = google_connect.callback(request)
    if target:
        return HttpResponseRedirect(target)
    return render(request, "backups/google_problem.html", {"problem": problem}, status=400)


@require_GET
def decrypt_tool(request):
    _require(request)
    source = (Path(__file__).parent / "fileformat.py").read_text(encoding="utf-8")
    response = HttpResponse(source, content_type="text/x-python; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="anish1989-backup-tool.py"'
    return response


class BackupApi(APIView):
    permission_classes = [IsAuthenticated]
    action_needed = {"GET": "view", "POST": "configure"}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not policy.require(request.user, _code(self.action_needed[request.method]), request=request._request):
            self.permission_denied(request, message="You do not have permission for backups.")


class BackupStatusView(BackupApi):
    def get(self, request):
        set_up = services.is_set_up()
        drive = services.drive_connection()
        return Response({
            "set_up": set_up,
            "every_hours": services.site_settings().every_hours,
            "google_drive": {"connected": drive is not None, "account": drive.config.get("account_email", "") if drive else "",
                             "paused": services.site_settings().drive_paused_reason},
            "next_backup": services.next_backup_due() if set_up else None,
            "next_restore_test": services.next_restore_test_due() if set_up else None,
            "running": services.run_json(services.active_run()),
            "last_backup": services.run_json(services.latest(BackupRun.Kind.BACKUP)),
            "last_restore_test": services.run_json(services.latest(BackupRun.Kind.RESTORE_TEST)),
            "history": [services.run_json(r) for r in services.history()],
        })


class BackupRunView(BackupApi):
    def post(self, request):
        kind = request.data.get("kind", BackupRun.Kind.BACKUP)
        if kind not in (BackupRun.Kind.BACKUP, BackupRun.Kind.RESTORE_TEST):
            return Response({"detail": "kind must be 'backup' or 'restore_test'.", "code": "invalid"}, status=http.HTTP_400_BAD_REQUEST)
        try:
            run = services.queue(kind, user=request.user)
        except ValidationError as exc:
            return Response({"detail": " ".join(exc.messages), "code": "not_possible"}, status=http.HTTP_409_CONFLICT)
        return Response(services.run_json(run), status=http.HTTP_202_ACCEPTED)
