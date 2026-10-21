"""
Login security helpers: lockout counters, login history, and MFA devices.

Lockout counters live in the cache. Cache keys are prefixed with the current
tenant schema (see CACHES in settings), so a lockout in one business never
affects the same email address in another business.
"""
from __future__ import annotations

import base64
import secrets

import segno
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django_otp import devices_for_user, user_has_device
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import LoginEvent

TOTP_DEVICE_NAME = "Authenticator app"
BACKUP_DEVICE_NAME = "Backup codes"
# Backup codes: 16 characters, without letters that look alike (I, L, O, 0, 1).
BACKUP_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
BACKUP_CODE_LENGTH = 16


# ---------------------------------------------------------------------------
# Request details
# ---------------------------------------------------------------------------
def client_ip(request) -> str | None:
    # REMOTE_ADDR only. When a trusted reverse proxy is added, read its header here.
    return request.META.get("REMOTE_ADDR") if request is not None else None


def user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:300]


_AUDIT_OUTCOMES = {
    LoginEvent.Event.LOGIN_FAILED: "failed",
    LoginEvent.Event.MFA_FAILED: "failed",
    LoginEvent.Event.LOCKED_OUT: "denied",
}


def record_event(event: str, request=None, user=None, email: str = "") -> LoginEvent:
    """Write to the login history and to the audit log."""
    from apps.audit.services import audit

    if user is not None and not email:
        email = user.email
    audit(
        f"auth.{event}",
        request=request,
        actor=user,
        actor_email=(email or "").lower(),
        target=user if (user is not None and user.pk) else None,
        outcome=_AUDIT_OUTCOMES.get(event, "success"),
    )
    return LoginEvent.objects.create(
        user=user if (user is not None and user.pk) else None,
        email=(email or "")[:254].lower(),
        event=event,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------
def _lockout_key(email: str) -> str:
    return f"login-fail:{(email or '').strip().lower()}"


def failed_attempts(email: str) -> int:
    return cache.get(_lockout_key(email), 0)


def is_locked_out(email: str) -> bool:
    return failed_attempts(email) >= settings.LOGIN_LOCKOUT_ATTEMPTS


def register_failure(email: str) -> int:
    key = _lockout_key(email)
    # add() only sets the key if missing, so the window starts at the first failure.
    cache.add(key, 0, timeout=settings.LOGIN_LOCKOUT_SECONDS)
    try:
        return cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.set(key, 1, timeout=settings.LOGIN_LOCKOUT_SECONDS)
        return 1


def clear_failures(email: str) -> None:
    cache.delete(_lockout_key(email))


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------
def recheck_password(request) -> bool:
    """
    Ask for the password again before a sensitive change (MFA, backups). Uses
    the normal lockout: 5 wrong passwords lock the account for a while.
    """
    user = request.user
    if is_locked_out(user.email):
        return False
    if user.check_password(request.POST.get("password", "")):
        clear_failures(user.email)
        return True
    register_failure(user.email)
    record_event(LoginEvent.Event.LOGIN_FAILED, request, user=user)
    return False


def totp_issuer(device) -> str:
    tenant = getattr(connection, "tenant", None)
    base = "Anish1989 Business OS"
    if tenant is not None and getattr(tenant, "schema_name", "public") != "public":
        return f"{base} - {tenant.name}"
    return base


def has_mfa(user) -> bool:
    return user.is_authenticated and user_has_device(user, confirmed=True)


def has_totp(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def start_totp_setup(user) -> TOTPDevice:
    """Create a new, unconfirmed authenticator device (replacing any unfinished setup)."""
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    return TOTPDevice.objects.create(user=user, name=TOTP_DEVICE_NAME, confirmed=False)


def pending_totp_device(user) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-id").first()


def totp_setup_details(device: TOTPDevice) -> dict:
    """What the user needs to add the account to an authenticator app."""
    qr = segno.make(device.config_url, error="m")
    svg = qr.svg_inline(scale=5, border=2)
    return {
        "otpauth_url": device.config_url,
        "secret": base64.b32encode(device.bin_key).decode(),
        "qr_svg": svg,
    }


def confirm_totp(device: TOTPDevice, token: str) -> bool:
    token = (token or "").strip().replace(" ", "")
    with transaction.atomic():
        device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
        if not device.verify_token(token):
            return False
        device.confirmed = True
        device.save(update_fields=["confirmed"])
    return True


def normalise_code(token: str) -> str:
    """Accept codes typed with spaces or dashes, and backup codes in lower case."""
    token = (token or "").strip().replace(" ", "").replace("-", "")
    return token.upper() if len(token) == BACKUP_CODE_LENGTH else token


def format_backup_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4)) if len(code) == BACKUP_CODE_LENGTH else code


def verify_mfa(user, token: str):
    """Check a code from the authenticator app or a backup code. Returns the device or None."""
    token = normalise_code(token)
    if not token:
        return None
    with transaction.atomic():
        for device in devices_for_user(user, confirmed=True, for_verify=True):
            allowed, _ = device.verify_is_allowed()
            if allowed and device.verify_token(token):
                return device
    return None


def create_backup_codes(user) -> list[str]:
    """Replace the user's backup codes with a new set. Each code works once."""
    device, _ = StaticDevice.objects.get_or_create(user=user, name=BACKUP_DEVICE_NAME, defaults={"confirmed": True})
    device.token_set.all().delete()
    codes = ["".join(secrets.choice(BACKUP_CODE_ALPHABET) for _ in range(BACKUP_CODE_LENGTH)) for _ in range(settings.MFA_BACKUP_CODE_COUNT)]
    StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return [format_backup_code(code) for code in codes]


def backup_codes_remaining(user) -> int:
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def replace_authenticator(user, device: TOTPDevice) -> None:
    """After the new authenticator is confirmed, remove the old ones."""
    TOTPDevice.objects.filter(user=user, confirmed=True).exclude(pk=device.pk).delete()


# ---------------------------------------------------------------------------
# Administrator actions (Super Admin, or the reset_mfa command)
# ---------------------------------------------------------------------------
def _admin_event(event: str, user, *, by_email: str, request=None, reason: str = "") -> None:
    from apps.audit.services import audit

    audit(
        f"auth.{event}", request=request, actor_email=by_email, target=user,
        metadata={"by": by_email or "server command", **({"reason": reason} if reason else {})},
    )
    LoginEvent.objects.create(user=user, email=user.email, event=event, ip_address=client_ip(request), user_agent=user_agent(request))


@transaction.atomic
def reset_mfa(user, *, by_email: str = "", request=None) -> None:
    """Remove the authenticator and backup codes. The person sets MFA up again at the next login."""
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
    user.mfa_exempt, user.mfa_exempt_reason, user.mfa_exempt_by, user.mfa_exempt_at = False, "", "", None
    user.save(update_fields=["mfa_exempt", "mfa_exempt_reason", "mfa_exempt_by", "mfa_exempt_at"])
    _admin_event(LoginEvent.Event.MFA_RESET, user, by_email=by_email, request=request)


@transaction.atomic
def set_mfa_switched_off(user, off: bool, *, reason: str = "", by_email: str = "", request=None) -> None:
    """
    Switch two-step verification off (the person logs in with a password only)
    or on again (they must set it up at the next login). A reason is required
    to switch it off, and both are recorded.
    """
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if off:
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("Give a reason for switching two-step verification off.")
        TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()
        user.mfa_exempt, user.mfa_exempt_reason, user.mfa_exempt_by, user.mfa_exempt_at = True, reason[:200], by_email, timezone.now()
        event = LoginEvent.Event.MFA_SWITCHED_OFF
    else:
        user.mfa_exempt, user.mfa_exempt_reason, user.mfa_exempt_by, user.mfa_exempt_at = False, "", "", None
        event = LoginEvent.Event.MFA_SWITCHED_ON
    user.save(update_fields=["mfa_exempt", "mfa_exempt_reason", "mfa_exempt_by", "mfa_exempt_at"])
    _admin_event(event, user, by_email=by_email, request=request, reason=reason if off else "")


def mfa_status(user) -> str:
    """'on', 'off' (switched off by an admin) or 'not_set_up'."""
    if user.mfa_exempt and not has_totp(user):
        return "off"
    return "on" if has_totp(user) else "not_set_up"
