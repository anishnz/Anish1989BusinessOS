"""
Login security helpers: lockout counters, login history, and MFA devices.

Lockout counters live in the cache. Cache keys are prefixed with the current
tenant schema (see CACHES in settings), so a lockout in one business never
affects the same email address in another business.
"""
from __future__ import annotations

import base64

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


def verify_mfa(user, token: str):
    """Check a code from the authenticator app or a backup code. Returns the device or None."""
    token = (token or "").strip().replace(" ", "")
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
    codes = [StaticToken.random_token() for _ in range(settings.MFA_BACKUP_CODE_COUNT)]
    StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return codes


def backup_codes_remaining(user) -> int:
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()
