"""
Tickets: report, comment, change status, assign, send on to platform support,
and automatic tickets for failed checks and backups.

Who (business site; on the platform site the module is "support"):
- tickets.view + tickets.create: report a problem and follow your own tickets
- tickets.edit: see every ticket of the business, answer, change the status
- tickets.assign: assign tickets and send them on to platform support

Every change is audited. Emails never contain secrets; a failed email never
breaks the action.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit
from apps.rbac import policy

from .models import Ticket, TicketComment

log = logging.getLogger(__name__)


def on_platform() -> bool:
    return connection.schema_name == get_public_schema_name()


def module() -> str:
    return "support" if on_platform() else "tickets"


def can(user, action: str) -> bool:
    return policy.has_perm(user, f"{module()}.{action}")


def need(user, action: str, request=None) -> None:
    if not policy.require(user, f"{module()}.{action}", request=request):
        raise PermissionDenied


def _name(user) -> str:
    full = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    return full or getattr(user, "email", "")


def site_name() -> str:
    if on_platform():
        return "Platform support"
    from apps.health.services import current_tenant

    tenant = current_tenant()
    return tenant.name if tenant else connection.schema_name


# ---------------------------------------------------------------------------
# Seeing tickets
# ---------------------------------------------------------------------------
def visible(user):
    """Everyone with tickets.edit sees every ticket; others see the tickets they reported."""
    qs = Ticket.objects.select_related("assigned_to", "reporter")
    return qs if can(user, "edit") else qs.filter(reporter=user)


def can_see(user, ticket: Ticket) -> bool:
    return can(user, "edit") or (ticket.reporter_id is not None and ticket.reporter_id == getattr(user, "pk", None) and can(user, "view"))


def comments_for(user, ticket: Ticket):
    qs = ticket.comments.select_related("author")
    return qs if can(user, "edit") else qs.filter(internal=False)


def handlers():
    """Active people who can work on tickets here (shown in "Assign to" and told about new tickets)."""
    from apps.accounts.models import User

    return [u for u in User.objects.filter(is_active=True).order_by("email") if policy.has_perm(u, f"{module()}.edit")]


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------
def _link(ticket: Ticket, schema: str | None = None) -> str:
    from apps.tenants.domains import main_address, site_url
    from apps.tenants.models import Tenant

    schema = schema or connection.schema_name
    with schema_context(get_public_schema_name()):
        tenant = Tenant.objects.filter(schema_name=schema).first()
        host = main_address(tenant) if tenant else ""
    return site_url(host, None, f"/tickets/{ticket.pk}/") if host else ""


def _mail(subject: str, body: str, to: list[str]) -> None:
    to = sorted({t for t in to if t})
    if not to:
        return
    try:
        send_mail(subject, body, None, to)
    except Exception:  # noqa: BLE001 - an email problem must not stop the ticket
        log.exception("Ticket email could not be sent")


def _summary(ticket: Ticket) -> str:
    return (f"#{ticket.pk} {ticket.title}\nPriority: {ticket.get_priority_display()} · Status: {ticket.get_status_display()}\n"
            f"Reported by: {ticket.reporter_label}\n\nOpen: {_link(ticket)}")


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def _clean_page(page: str) -> str:
    """Keep only the path: query strings can hold tokens (password reset links, OAuth codes)."""
    parsed = urlparse(page or "")
    return (parsed.path or "")[:300]


@transaction.atomic
def report(user, *, title: str, description: str, priority: str = Ticket.Priority.NORMAL,
           category: str = Ticket.Category.PROBLEM, page: str = "", browser: str = "") -> Ticket:
    title, description = " ".join((title or "").split())[:200], (description or "").strip()[:10000]
    if not title:
        raise ValidationError("Enter a short title.")
    if not description:
        raise ValidationError("Describe the problem: what you did, what happened, and what you expected.")
    if priority not in Ticket.Priority.values or category not in Ticket.Category.values:
        raise ValidationError("Choose a priority and a type from the list.")
    ticket = Ticket.objects.create(
        title=title, description=description, priority=priority, category=category, reporter=user,
        reporter_name=_name(user), reporter_email=user.email, page=_clean_page(page), browser=(browser or "")[:300],
    )
    audit("ticket.create", target=ticket, actor=user, metadata={"priority": priority, "category": category})
    _mail(f"New ticket #{ticket.pk}: {ticket.title}", f"A new ticket was reported in {site_name()}.\n\n{_summary(ticket)}",
          [u.email for u in handlers() if u.pk != user.pk])
    return ticket


@transaction.atomic
def comment(user, ticket: Ticket, body: str, *, internal: bool = False) -> TicketComment:
    if not can_see(user, ticket):
        raise PermissionDenied
    body = (body or "").strip()[:10000]
    if not body:
        raise ValidationError("Write a message first.")
    handler = can(user, "edit")
    if internal and not handler:
        raise PermissionDenied
    note = TicketComment.objects.create(ticket=ticket, author=user, author_name=_name(user), author_email=user.email, body=body, internal=internal)
    changed = ["updated_at"]
    if handler and not internal and ticket.reporter_id != user.pk and ticket.first_response_at is None:
        ticket.first_response_at = note.created_at
        changed.append("first_response_at")
    if not handler and ticket.status == Ticket.Status.WAITING:  # the reporter answered
        ticket.status = Ticket.Status.IN_PROGRESS
        changed.append("status")
    ticket.save(update_fields=changed)
    audit("ticket.comment", target=ticket, actor=user, metadata={"internal": internal})
    if not internal and on_platform() and ticket.from_schema:
        notify_business(ticket, f"Platform support replied:\n\n{body}")
    elif not internal:
        if user.pk == ticket.reporter_id:
            to = [ticket.assigned_to.email] if ticket.assigned_to else [u.email for u in handlers()]
        else:
            to = [ticket.reporter_email]
        _mail(f"Ticket #{ticket.pk}: new reply", f"{_name(user)} wrote:\n\n{body}\n\n{_summary(ticket)}", [t for t in to if t != user.email])
    return note


@transaction.atomic
def set_status(user, ticket: Ticket, status: str) -> Ticket:
    if not can(user, "edit"):
        raise PermissionDenied
    if status not in Ticket.Status.values:
        raise ValidationError("Unknown status.")
    if status == ticket.status:
        return ticket
    old = ticket.status
    ticket.status = status
    now = timezone.now()
    if status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
        ticket.resolved_at = ticket.resolved_at or now
    else:
        ticket.resolved_at = None
    if ticket.first_response_at is None and old == Ticket.Status.NEW and ticket.reporter_id != user.pk:
        ticket.first_response_at = now
    ticket.save()
    audit("ticket.status", target=ticket, actor=user, metadata={"from": old, "to": status})
    if on_platform() and ticket.from_schema:
        notify_business(ticket, f"Platform support changed the status to: {ticket.get_status_display()}.")
    elif ticket.reporter_email and ticket.reporter_id != user.pk:
        _mail(f"Ticket #{ticket.pk} is now: {ticket.get_status_display()}", _summary(ticket), [ticket.reporter_email])
    return ticket


@transaction.atomic
def assign(user, ticket: Ticket, assignee) -> Ticket:
    if not can(user, "assign"):
        raise PermissionDenied
    if assignee is not None and assignee.pk not in {u.pk for u in handlers()}:
        raise ValidationError("This person cannot work on tickets (they need the Tickets - Edit permission).")
    ticket.assigned_to = assignee
    if assignee is not None and ticket.status == Ticket.Status.NEW:
        ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    audit("ticket.assign", target=ticket, actor=user, metadata={"to": getattr(assignee, "email", "")})
    if assignee is not None and assignee.pk != user.pk:
        _mail(f"Ticket #{ticket.pk} was assigned to you", _summary(ticket), [assignee.email])
    return ticket


# ---------------------------------------------------------------------------
# Platform support (a business sends a ticket on)
# ---------------------------------------------------------------------------
def platform_people_emails() -> list[str]:
    """Super Admins and Platform Support Admins."""
    from apps.accounts.models import User
    from apps.rbac.models import UserRole

    ids = set(UserRole.objects.filter(role__slug__in=["super_admin", "platform_support_admin"]).values_list("user_id", flat=True))
    users = User.objects.filter(is_active=True).filter(pk__in=ids) | User.objects.filter(is_active=True, is_superuser=True)
    return sorted({u.email for u in users if u.email})


@transaction.atomic
def send_to_platform(user, ticket: Ticket, note: str = "") -> int:
    if on_platform():
        raise ValidationError("This is already a platform ticket.")
    if not can(user, "assign"):
        raise PermissionDenied
    if ticket.platform_ticket_id:
        raise ValidationError("This ticket was already sent to platform support.")
    schema, business = connection.schema_name, site_name()
    page = f"\nPage: {ticket.page}" if ticket.page else ""
    text = (f"{ticket.description}\n\n---\nReported in {business} by {ticket.reporter_label} on "
            f"{timezone.localtime(ticket.created_at):%d %b %Y, %H:%M}.{page}")
    if note.strip():
        text += f"\n\nNote from {_name(user)}: {note.strip()[:2000]}"
    with schema_context(get_public_schema_name()):
        platform_ticket = Ticket.objects.create(
            title=ticket.title, description=text[:10000], category=ticket.category, priority=ticket.priority,
            source=Ticket.Source.BUSINESS, reporter_name=_name(user), reporter_email=user.email, browser=ticket.browser,
            page=ticket.page, from_schema=schema, from_business=business, from_ticket_id=ticket.pk,
        )
        audit("ticket.received_from_business", target=platform_ticket, metadata={"business": schema, "ticket": ticket.pk, "by": user.email})
        _mail(f"Support ticket #{platform_ticket.pk} from {business}: {ticket.title}",
              f"{business} sent a ticket to platform support.\n\n{_summary(platform_ticket)}", platform_people_emails())
    ticket.platform_ticket_id = platform_ticket.pk
    if ticket.status == Ticket.Status.NEW:
        ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    audit("ticket.sent_to_platform", target=ticket, actor=user, metadata={"platform_ticket": platform_ticket.pk})
    return platform_ticket.pk


def platform_view(ticket: Ticket) -> tuple[Ticket | None, list[TicketComment]]:
    """The platform ticket of a business ticket, and its comments meant for the business (read in the platform schema)."""
    if not ticket.platform_ticket_id or on_platform():
        return None, []
    schema = connection.schema_name
    with schema_context(get_public_schema_name()):
        remote = Ticket.objects.filter(pk=ticket.platform_ticket_id, from_schema=schema, from_ticket_id=ticket.pk).first()
        notes = list(remote.comments.filter(internal=False)) if remote else []
    return remote, notes


@transaction.atomic
def reply_to_platform(user, ticket: Ticket, body: str) -> None:
    if not can(user, "assign"):
        raise PermissionDenied
    body = (body or "").strip()[:10000]
    if not body:
        raise ValidationError("Write a message first.")
    schema, business = connection.schema_name, site_name()
    with schema_context(get_public_schema_name()):
        remote = Ticket.objects.select_for_update().filter(pk=ticket.platform_ticket_id or 0, from_schema=schema, from_ticket_id=ticket.pk).first()
        if remote is None:
            raise ValidationError("This ticket was not sent to platform support.")
        TicketComment.objects.create(ticket=remote, author_name=f"{_name(user)} ({business})", author_email=user.email, body=body)
        if remote.status == Ticket.Status.WAITING:
            remote.status = Ticket.Status.IN_PROGRESS
        remote.save()
        audit("ticket.comment", target=remote, metadata={"from_business": schema, "by": user.email})
        to = [remote.assigned_to.email] if remote.assigned_to else platform_people_emails()
        _mail(f"Support ticket #{remote.pk}: reply from {business}", f"{_name(user)} wrote:\n\n{body}\n\n{_summary(remote)}", to)
    audit("ticket.replied_to_platform", target=ticket, actor=user)


def notify_business(platform_ticket: Ticket, text: str) -> None:
    """Platform side: tell the business person who sent the ticket on (after a reply or a status change)."""
    if not platform_ticket.from_schema or not platform_ticket.reporter_email:
        return
    link = ""
    if platform_ticket.from_ticket_id:
        link = _link(Ticket(pk=platform_ticket.from_ticket_id), platform_ticket.from_schema)
    _mail(f"Platform support: your ticket “{platform_ticket.title}”", f"{text}\n\nOpen your ticket: {link}", [platform_ticket.reporter_email])


# ---------------------------------------------------------------------------
# Automatic tickets (failed checks and backups)
# ---------------------------------------------------------------------------
def system_ticket(*, source: str, key: str, title: str, description: str, priority: str = Ticket.Priority.HIGH) -> Ticket | None:
    """
    One open ticket per problem: a new failure of the same kind adds a comment
    to the open ticket instead of a new ticket. Nothing happens when the
    business does not use the Tickets module.
    """
    if not policy.module_enabled(module()):
        return None
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(source_key=key, status__in=Ticket.OPEN).first()
        if ticket:
            TicketComment.objects.create(ticket=ticket, body=f"It happened again:\n\n{description}"[:10000])
            ticket.save(update_fields=["updated_at"])
            return ticket
        ticket = Ticket.objects.create(title=title[:200], description=description[:10000], priority=priority, source=source,
                                       source_key=key[:100], category=Ticket.Category.PROBLEM)
        audit("ticket.create", target=ticket, metadata={"source": source, "automatic": True})
    _mail(f"New ticket #{ticket.pk}: {ticket.title}", f"A ticket was created automatically in {site_name()}.\n\n{_summary(ticket)}",
          [u.email for u in handlers()])
    return ticket


def stats(qs) -> dict:
    """Small numbers for the list page."""
    open_qs = qs.filter(status__in=Ticket.OPEN)
    overdue = sum(1 for t in open_qs.filter(first_response_at__isnull=True) if t.response_overdue)
    done = list(qs.exclude(first_response_at=None).values_list("created_at", "first_response_at")[:200])
    avg = sum(((b - a).total_seconds() for a, b in done), 0.0) / len(done) if done else None
    return {"open": open_qs.count(), "new": open_qs.filter(status=Ticket.Status.NEW).count(), "overdue": overdue,
            "avg_first_response_hours": round(avg / 3600, 1) if avg is not None else None}
