"""
Server-rendered MFA pages used by the admin site (and any page before the
React frontend exists). The React app will use the JSON API in api.py.
"""
from urllib.parse import quote

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login

from . import security
from .models import LoginEvent


def _safe_next(request, default="/admin/") -> str:
    target = request.POST.get("next") or request.GET.get("next") or default
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


def _context(request, **extra):
    context = admin.site.each_context(request)
    context["is_nav_sidebar_enabled"] = False  # no admin menu until MFA is done
    context.update(extra)
    return context


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    user = request.user
    next_url = _safe_next(request)

    # Someone who already has MFA must prove it before adding a new device.
    # Otherwise a stolen password alone could be used to enrol a new authenticator.
    if security.has_mfa(user) and not user.is_verified():
        return redirect(f"{reverse('accounts:mfa_verify')}?next={quote(next_url)}")
    if security.has_totp(user) and user.is_verified():
        return redirect(next_url)

    device = security.pending_totp_device(user) or security.start_totp_setup(user)
    error = ""
    if request.method == "POST":
        if security.confirm_totp(device, request.POST.get("token", "")):
            device.refresh_from_db()
            otp_login(request, device)
            if user.mfa_exempt:  # they chose to use MFA again
                user.mfa_exempt, user.mfa_exempt_reason, user.mfa_exempt_by, user.mfa_exempt_at = False, "", "", None
                user.save(update_fields=["mfa_exempt", "mfa_exempt_reason", "mfa_exempt_by", "mfa_exempt_at"])
            security.record_event(LoginEvent.Event.MFA_ENABLED, request, user=user)
            codes = security.create_backup_codes(user)
            security.record_event(LoginEvent.Event.BACKUP_CODES_CREATED, request, user=user)
            return render(
                request,
                "accounts/mfa_backup_codes.html",
                _context(request, title="Save your backup codes", codes=codes, next=next_url),
            )
        error = "That code did not match. Wait a few seconds, check the time on your phone is correct, and try the newest code."

    return render(
        request,
        "accounts/mfa_setup.html",
        _context(request, title="Set up two-step verification", setup=security.totp_setup_details(device), next=next_url, error=error),
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    user = request.user
    next_url = _safe_next(request)
    if not security.has_mfa(user):
        return redirect(f"{reverse('accounts:mfa_setup')}?next={quote(next_url)}")
    if user.is_verified():
        return redirect(next_url)

    error = ""
    if request.method == "POST":
        device = security.verify_mfa(user, request.POST.get("token", ""))
        if device is not None:
            otp_login(request, device)
            security.record_event(LoginEvent.Event.MFA_SUCCESS, request, user=user)
            return redirect(next_url)
        security.record_event(LoginEvent.Event.MFA_FAILED, request, user=user)
        error = "That code is not valid. Wait a few seconds and enter the newest 6-digit code from your authenticator app, or a backup code."

    return render(request, "accounts/mfa_verify.html", _context(request, title="Two-step verification", next=next_url, error=error))


def _password_ok(request) -> bool:
    """Re-check the password before changing MFA (with the normal lockout)."""
    return security.recheck_password(request)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def mfa_manage(request):
    """
    "My two-step verification": see the status, get new backup codes, or move
    to a new phone (new QR code). Both changes need the password again.
    """
    from django.contrib import messages

    user = request.user
    here = reverse("accounts:mfa_manage")
    if security.has_mfa(user) and not user.is_verified():
        return redirect(f"{reverse('accounts:mfa_verify')}?next={quote(here)}")
    if not security.has_totp(user):
        if user.mfa_exempt or not user.mfa_required:
            context = _context(request, title="My two-step verification", status=security.mfa_status(user), exempt=user)
            context["is_nav_sidebar_enabled"] = True
            return render(request, "accounts/mfa_manage.html", context)
        return redirect(f"{reverse('accounts:mfa_setup')}?next={quote(here)}")

    error = ""
    action = request.POST.get("action") if request.method == "POST" else None
    if action in ("codes", "new_qr"):
        if not _password_ok(request):
            error = "The password is not correct." if not security.is_locked_out(user.email) else "Too many wrong passwords. Try again in 15 minutes."
        elif action == "codes":
            codes = security.create_backup_codes(user)
            security.record_event(LoginEvent.Event.BACKUP_CODES_CREATED, request, user=user)
            return render(request, "accounts/mfa_backup_codes.html", _context(request, title="Your new backup codes", codes=codes, next=here))
        else:
            device = security.start_totp_setup(user)
            return render(request, "accounts/mfa_replace.html", _context(request, title="Move to a new phone", setup=security.totp_setup_details(device)))
    elif action == "confirm_qr":
        device = security.pending_totp_device(user)
        if device is not None and security.confirm_totp(device, request.POST.get("token", "")):
            device.refresh_from_db()
            security.replace_authenticator(user, device)
            otp_login(request, device)
            security.record_event(LoginEvent.Event.AUTHENTICATOR_REPLACED, request, user=user)
            messages.success(request, "Your new authenticator app is now active. The old one no longer works.")
            return redirect(here)
        if device is None:
            return redirect(here)
        return render(request, "accounts/mfa_replace.html", _context(
            request, title="Move to a new phone", setup=security.totp_setup_details(device),
            error="That code did not match. Use the newest code from the new app.",
        ))

    context = _context(request, title="My two-step verification", status="on", remaining=security.backup_codes_remaining(user), error=error)
    context["is_nav_sidebar_enabled"] = True
    return render(request, "accounts/mfa_manage.html", context)
