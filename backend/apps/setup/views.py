"""
/setup/?step=business|backups|connections|done   the setup wizard (Settings - Configure)
/setup/later/                                     POST: close the wizard for this sign-in
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.rbac import policy

from . import services


class ProfileForm(forms.Form):
    """Plain fields; services.clean_profile checks and tidies them (phone, GST number, postcode, website)."""

    trading_name = forms.CharField(required=False, max_length=200, label="Trading name", help_text="The name customers know. Leave empty to use the registered name.")
    phone = forms.CharField(required=False, max_length=30, widget=forms.TextInput(attrs={"placeholder": "09 123 4567", "inputmode": "tel"}))
    email = forms.CharField(required=False, max_length=254, label="Email for customers", widget=forms.EmailInput(attrs={"placeholder": "hello@example.co.nz"}))
    address = forms.CharField(required=False, max_length=200, label="Street address")
    suburb = forms.CharField(required=False, max_length=100)
    city = forms.CharField(required=False, max_length=100, label="Town or city")
    postcode = forms.CharField(required=False, max_length=10, widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    gst_number = forms.CharField(required=False, max_length=20, label="GST number", help_text="Optional. Shown on invoices later.",
                                 widget=forms.TextInput(attrs={"placeholder": "123-456-789"}))
    website = forms.CharField(required=False, max_length=200, widget=forms.TextInput(attrs={"placeholder": "www.example.co.nz"}))

    @classmethod
    def for_profile(cls, profile, data=None):
        return cls(data, initial={f: getattr(profile, f) for f in services.PROFILE_FIELDS})


def _require(request) -> None:
    if not services.on_business_site():
        raise Http404("Setup is for business sites.")
    if not policy.require(request.user, "settings.configure", request=request):
        raise PermissionDenied


def _url(step: str) -> str:
    return f"{reverse('setup')}?step={step}"


@never_cache
def wizard(request):
    _require(request)
    step = request.GET.get("step") or services.first_open_step()
    if step not in services.STEP_KEYS:
        step = services.first_open_step()
    prog = services.progress()
    if prog.started_at is None:
        from django.utils import timezone

        prog.started_at = timezone.now()
        prog.save(update_fields=["started_at"])

    form = None
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "business":
                form = ProfileForm.for_profile(services.profile(), request.POST)
                if form.is_valid():
                    services.save_profile(form.cleaned_data, actor=request.user)
                    messages.success(request, "Business details saved.")
                    return redirect(_url("backups"))
            elif action == "skip":
                services.skip(step, actor=request.user)
                return redirect(_url(services.next_step(step)))
            elif action == "test_backup":
                from apps.backups import services as backups
                from apps.backups.models import BackupRun

                backups.queue(BackupRun.Kind.BACKUP, user=request.user)
                messages.success(request, "Test backup started. This page updates by itself.")
                return redirect(_url("backups"))
            elif action == "connections":
                services.mark_connections_seen(actor=request.user)
                return redirect(_url("done"))
            elif action == "finish":
                services.finish(actor=request.user)
                request.session.pop(services.LATER_SESSION_KEY, None)
                messages.success(request, "Setup finished. You can change everything later in the admin pages.")
                return redirect("admin:index")
            else:
                messages.error(request, "Unknown action.")
        except ValidationError as exc:
            if form is not None and hasattr(exc, "error_dict"):
                for field, errs in exc.message_dict.items():
                    form.add_error(field if field in form.fields else None, errs)
            else:
                messages.error(request, " ".join(exc.messages))
    if step == "business" and form is None:
        form = ProfileForm.for_profile(services.profile())

    backup = services.backup_state() if step in ("backups", "done") else None
    return render(request, "setup/wizard.html", {
        **admin.site.each_context(request),
        "title": "Set up your business",
        "step": step,
        "steps": [(key, label, services.step_done(key), key == step) for key, label in services.STEPS],
        "business_name": services.business_name(),
        "form": form,
        "backup": backup,
        "connections": services.connection_state() if step in ("connections", "done") else None,
        "here": _url(step),
        "progress": prog,
    })


@require_POST
def later(request):
    _require(request)
    request.session[services.LATER_SESSION_KEY] = True
    messages.info(request, "Setup is closed for now. Open it again any time from “Set up your business” at the top.")
    return redirect("admin:index")
