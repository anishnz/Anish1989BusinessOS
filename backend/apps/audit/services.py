"""
Write audit events.

    from apps.audit.services import audit
    audit("role.create", target=role, changes={...})

The actor, IP address and user agent come from the current request
(set by AuditContextMiddleware), or `system` outside a request.
"""
from __future__ import annotations

import contextvars
import json
import re
from contextlib import contextmanager

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from .models import AuditEvent

_current_request: contextvars.ContextVar = contextvars.ContextVar("audit_request", default=None)

# Values under keys like these are never written to the audit log.
SECRET_KEY_PATTERN = re.compile(r"pass(word)?|secret|token|api[_-]?key|private|otp|bin_key|credential", re.IGNORECASE)
REDACTED = "[redacted]"


def set_current_request(request):
    return _current_request.set(request)


def reset_current_request(token):
    _current_request.reset(token)


def current_request():
    return _current_request.get()


def _json_safe(value):
    """Exactly what the JSON column will store, so the hash matches after reading it back."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


CHANGED_MARKER = {"changed": True}  # "this secret was changed", without the value


def redact(value):
    if isinstance(value, dict):
        return {
            k: (v if v == CHANGED_MARKER else REDACTED) if SECRET_KEY_PATTERN.search(str(k)) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


_platform_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar("platform_actor", default=None)


@contextmanager
def platform_actor(email: str):
    """
    Use while the platform Super Admin changes something inside a business.
    Their user id belongs to the platform, not to the business, so the
    business's audit log records "platform administrator <email>" instead.
    """
    token = _platform_actor.set(email)
    try:
        yield
    finally:
        _platform_actor.reset(token)


def _actor(request, actor):
    platform_email = _platform_actor.get()
    if platform_email:
        return AuditEvent.ActorType.PLATFORM, None, platform_email
    user = actor if actor is not None else (getattr(request, "user", None) if request is not None else None)
    if user is not None and getattr(user, "is_authenticated", False):
        return AuditEvent.ActorType.USER, user.pk, user.email
    if request is not None:
        return AuditEvent.ActorType.ANONYMOUS, None, ""
    return AuditEvent.ActorType.SYSTEM, None, ""


def audit(
    action: str,
    *,
    target=None,
    target_type: str = "",
    target_id="",
    target_repr: str = "",
    outcome: str = AuditEvent.Outcome.SUCCESS,
    changes: dict | None = None,
    metadata: dict | None = None,
    request=None,
    actor=None,
    actor_type: str | None = None,
    actor_email: str = "",
) -> AuditEvent:
    request = request if request is not None else current_request()
    a_type, a_id, a_email = _actor(request, actor)
    if actor_type:
        a_type = actor_type
    if actor_email and not a_email:
        a_email = actor_email

    if target is not None:
        target_type = target_type or f"{target._meta.app_label}.{target._meta.model_name}"
        target_id = target_id or (str(target.pk) if target.pk is not None else "")
        # Models holding personal data can give a neutral label (e.g. "Customer #12").
        target_repr = target_repr or getattr(target, "audit_label", None) or str(target)

    event = AuditEvent(
        created_at=timezone.now(),
        actor_type=a_type,
        actor_id=a_id,
        actor_email=(a_email or "")[:254],
        action=action[:100],
        target_type=target_type[:100],
        target_id=str(target_id)[:64],
        target_repr=str(target_repr)[:200],
        outcome=outcome,
        ip_address=request.META.get("REMOTE_ADDR") if request is not None else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:300],
        changes=_json_safe(redact(changes or {})),
        metadata=_json_safe(redact(metadata or {})),
    )
    with transaction.atomic():
        # One writer at a time per schema, so the hash chain has no forks.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema() || ':audit'))")
        last = AuditEvent.objects.order_by("-id").values_list("hash", flat=True).first()
        event.prev_hash = last or ""
        event.hash = event.compute_hash()
        event.save()
    return event


def verify_chain() -> tuple[bool, list[str]]:
    """Recompute every hash in order. Returns (ok, problems)."""
    problems: list[str] = []
    previous = ""
    for event in AuditEvent.objects.order_by("id").iterator():
        if event.prev_hash != previous:
            problems.append(f"Event {event.pk}: link to the previous event is broken (an event was removed or reordered).")
        if event.compute_hash() != event.hash:
            problems.append(f"Event {event.pk}: content does not match its hash (it was changed).")
        previous = event.hash
    return (not problems), problems
