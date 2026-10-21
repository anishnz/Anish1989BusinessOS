"""
Ticket pages and API (business sites and the platform site).

/tickets/                       list (mine, or all for people who handle tickets) + "Report a problem"
/tickets/new/?from=<page>       report a problem
/tickets/<id>/                  one ticket: messages, status, assign, send to platform support
/tickets/from-check/<run id>/   POST: ticket from a red "Check system" run
/tickets/from-backup/<run id>/  POST: ticket from a failed backup or restore test
GET/POST  /api/tickets/                  list / report
GET/PATCH /api/tickets/<id>/             one ticket / {"status", "assigned_to"}
POST      /api/tickets/<id>/comments/    {"body", "internal"}
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import Ticket

FILTERS = {"open": "Open", "mine": "Reported by me", "assigned": "Assigned to me", "all": "All"}


class ReportForm(forms.Form):
    title = forms.CharField(max_length=200, label="Short title", widget=forms.TextInput(attrs={"placeholder": "For example: Orders page shows an error"}))
    description = forms.CharField(max_length=10000, label="What happened?", widget=forms.Textarea(attrs={"rows": 7}),
                                  help_text="What you did, what happened, and what you expected. Never type passwords or API keys here.")
    category = forms.ChoiceField(choices=Ticket.Category.choices, initial=Ticket.Category.PROBLEM, label="Type")
    priority = forms.ChoiceField(choices=Ticket.Priority.choices, initial=Ticket.Priority.NORMAL, label="How urgent?")
    page = forms.CharField(max_length=300, required=False, widget=forms.HiddenInput)


def _ctx(request, **extra):
    return {**admin.site.each_context(request), "on_platform": services.on_platform(), **extra}


def _get_ticket(request, pk) -> Ticket:
    ticket = Ticket.objects.select_related("assigned_to", "reporter").filter(pk=pk).first()
    if ticket is None or not services.can_see(request.user, ticket):
        raise Http404("No such ticket.")
    return ticket


@never_cache
def ticket_list(request):
    services.need(request.user, "view", request)
    show = request.GET.get("show", "open")
    show = show if show in FILTERS else "open"
    base = services.visible(request.user)
    qs = base
    if show == "open":
        qs = qs.filter(status__in=Ticket.OPEN)
    elif show == "mine":
        qs = qs.filter(reporter=request.user)
    elif show == "assigned":
        qs = qs.filter(assigned_to=request.user)
    handler = services.can(request.user, "edit")
    return render(request, "tickets/list.html", _ctx(
        request, title="Platform support tickets" if services.on_platform() else "Tickets", tickets=qs[:200],
        show=show, filters=FILTERS, handler=handler, stats=services.stats(base) if handler else None,
        can_report=services.can(request.user, "create"),
    ))


@never_cache
def ticket_new(request):
    services.need(request.user, "create", request)
    form = ReportForm(request.POST or None, initial={"page": services._clean_page(request.GET.get("from", ""))})
    if request.method == "POST" and form.is_valid():
        try:
            ticket = services.report(request.user, browser=request.META.get("HTTP_USER_AGENT", ""), **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Thank you. Ticket #{ticket.pk} was sent. You get an email when someone answers.")
            return redirect("ticket_detail", pk=ticket.pk)
    return render(request, "tickets/new.html", _ctx(request, title="Report a problem", form=form, from_page=services._clean_page(request.GET.get("from", ""))))


@never_cache
def ticket_detail(request, pk):
    services.need(request.user, "view", request)
    ticket = _get_ticket(request, pk)
    if request.method == "POST":
        return _act(request, ticket)
    remote, remote_notes = services.platform_view(ticket) if services.can(request.user, "assign") else (None, [])
    return render(request, "tickets/detail.html", _ctx(
        request, title=f"Ticket #{ticket.pk}", ticket=ticket, comments=services.comments_for(request.user, ticket),
        handler=services.can(request.user, "edit"), can_assign=services.can(request.user, "assign"),
        people=services.handlers() if services.can(request.user, "assign") else [], statuses=Ticket.Status.choices,
        remote=remote, remote_notes=remote_notes,
    ))


def _act(request, ticket):
    action, user = request.POST.get("action", ""), request.user
    try:
        if action == "comment":
            services.comment(user, ticket, request.POST.get("body", ""), internal=bool(request.POST.get("internal")))
            messages.success(request, "Message added.")
        elif action == "status":
            services.set_status(user, ticket, request.POST.get("status", ""))
            messages.success(request, f"Status: {ticket.get_status_display()}.")
        elif action == "assign":
            from apps.accounts.models import User

            pk = request.POST.get("assigned_to", "")
            services.assign(user, ticket, User.objects.filter(pk=int(pk)).first() if pk.isdigit() else None)
            messages.success(request, "Assignment saved.")
        elif action == "platform":
            number = services.send_to_platform(user, ticket, request.POST.get("note", ""))
            messages.success(request, f"Sent to platform support (their ticket #{number}).")
        elif action == "platform_reply":
            services.reply_to_platform(user, ticket, request.POST.get("body", ""))
            messages.success(request, "Message sent to platform support.")
        else:
            messages.error(request, "Unknown action.")
    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("ticket_detail", pk=ticket.pk)


@require_POST
def from_check(request, run_id):
    services.need(request.user, "create", request)
    from apps.health.models import CheckRun

    run = get_object_or_404(CheckRun, pk=run_id)
    red = [r for r in run.results if r["status"] == "failed"]
    if not red:
        messages.info(request, "That check run has no failed results.")
        return redirect("system_check")
    lines = "\n".join(f"- {r['area']} / {r['label']}: {r['message']}" for r in red)
    ticket = services.report(request.user, title=f"Check system: {len(red)} failed check(s)", priority=Ticket.Priority.HIGH,
                             description=f"Check system run of {run.started_at:%d %b %Y, %H:%M} (UTC) found:\n\n{lines}",
                             page=reverse("system_check_run", args=[run.pk]), browser=request.META.get("HTTP_USER_AGENT", ""))
    messages.success(request, f"Ticket #{ticket.pk} created.")
    return redirect("ticket_detail", pk=ticket.pk)


@require_POST
def from_backup(request, run_id):
    services.need(request.user, "create", request)
    from apps.backups.models import BackupRun

    run = get_object_or_404(BackupRun, pk=run_id)
    if run.status not in (BackupRun.Status.FAILED, BackupRun.Status.WARNING):
        messages.info(request, "That run did not fail.")
        return redirect("backups")
    ticket = services.report(request.user, title=f"{run.get_kind_display()} failed", priority=Ticket.Priority.HIGH,
                             description=f"{run.get_kind_display()} of {run.queued_at:%d %b %Y, %H:%M} (UTC): {run.message}",
                             page=reverse("backups"), browser=request.META.get("HTTP_USER_AGENT", ""))
    messages.success(request, f"Ticket #{ticket.pk} created.")
    return redirect("ticket_detail", pk=ticket.pk)


# ---------------------------------------------------------------------------
# API (for the staff app)
# ---------------------------------------------------------------------------
def ticket_json(ticket: Ticket, user, *, full=False) -> dict:
    data = {
        "id": ticket.pk, "title": ticket.title, "status": ticket.status, "priority": ticket.priority, "category": ticket.category,
        "source": ticket.source, "reporter": ticket.reporter_label, "assigned_to": getattr(ticket.assigned_to, "email", None),
        "created_at": ticket.created_at, "updated_at": ticket.updated_at, "response_due": ticket.response_due,
        "response_overdue": ticket.response_overdue, "sent_to_platform": bool(ticket.platform_ticket_id),
    }
    if full:
        data["description"] = ticket.description
        data["page"] = ticket.page
        data["comments"] = [{"author": c.author_label, "body": c.body, "internal": c.internal, "created_at": c.created_at}
                            for c in services.comments_for(user, ticket)]
    return data


class TicketApi(APIView):
    permission_classes = [IsAuthenticated]
    needs = {"GET": "view", "POST": "view", "PATCH": "edit"}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not services.can(request.user, self.needs[request.method]):
            from apps.rbac import policy

            policy.require(request.user, f"{services.module()}.{self.needs[request.method]}", request=request._request)
            self.permission_denied(request, message="You do not have permission for tickets.")

    def handle_exception(self, exc):
        if isinstance(exc, ValidationError):
            return Response({"detail": " ".join(exc.messages), "code": "invalid"}, status=http.HTTP_400_BAD_REQUEST)
        if isinstance(exc, Http404):
            return Response({"detail": "No such ticket.", "code": "not_found"}, status=http.HTTP_404_NOT_FOUND)
        return super().handle_exception(exc)


class TicketListApi(TicketApi):
    def get(self, request):
        qs = services.visible(request.user)
        if request.query_params.get("open") == "1":
            qs = qs.filter(status__in=Ticket.OPEN)
        return Response([ticket_json(t, request.user) for t in qs[:200]])

    def post(self, request):
        if not services.can(request.user, "create"):
            self.permission_denied(request, message="You cannot report tickets.")
        d = request.data
        ticket = services.report(request.user, title=str(d.get("title", "")), description=str(d.get("description", "")),
                                 priority=str(d.get("priority", "normal")), category=str(d.get("category", "problem")),
                                 page=str(d.get("page", "")), browser=request.META.get("HTTP_USER_AGENT", ""))
        return Response(ticket_json(ticket, request.user, full=True), status=http.HTTP_201_CREATED)


class TicketDetailApi(TicketApi):
    def get(self, request, pk):
        return Response(ticket_json(_get_ticket(request, pk), request.user, full=True))

    def patch(self, request, pk):
        ticket = _get_ticket(request, pk)
        if "status" in request.data:
            services.set_status(request.user, ticket, str(request.data["status"]))
        if "assigned_to" in request.data:
            from apps.accounts.models import User

            value = request.data["assigned_to"]
            assignee = User.objects.filter(email__iexact=str(value)).first() if value else None
            if value and assignee is None:
                raise ValidationError("No such person.")
            services.assign(request.user, ticket, assignee)
        return Response(ticket_json(ticket, request.user, full=True))


class TicketCommentApi(TicketApi):
    def post(self, request, pk):
        ticket = _get_ticket(request, pk)
        services.comment(request.user, ticket, str(request.data.get("body", "")), internal=bool(request.data.get("internal")))
        return Response(ticket_json(ticket, request.user, full=True), status=http.HTTP_201_CREATED)
