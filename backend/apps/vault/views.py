"""
Settings pages for integrations (server-rendered, admin look) so businesses
can connect providers before the React screens exist.
Secret inputs are password fields that are never filled back in.
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from . import access, providers, services
from .models import Connection


def _need(request, action):
    if not access.allowed(request, action):
        raise PermissionDenied


def _context(request, **extra):
    context = admin.site.each_context(request)
    context.update(extra)
    return context


def build_form(provider: providers.Provider, *, editing: bool, data=None, initial=None):
    class ConnectionForm(forms.Form):
        label = forms.CharField(max_length=100, required=False, initial=provider.label)
        is_backup = forms.BooleanField(required=False, label="Backup connection (used only if the main one fails)")

    form = ConnectionForm(data=data, initial=initial)
    for f in provider.config_fields:
        form.fields[f"config__{f.name}"] = forms.CharField(label=f.label, required=f.required, initial=f.default, help_text=f.help, max_length=500)
    for f in provider.secret_fields:
        required = f.required and not editing
        help_text = f.help + (" Leave empty to keep the saved value." if editing else "")
        form.fields[f"secret__{f.name}"] = forms.CharField(
            label=f.label, required=required, help_text=help_text.strip(), max_length=4000,
            widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        )
    return form


def _split(cleaned: dict):
    config = {k.removeprefix("config__"): v for k, v in cleaned.items() if k.startswith("config__")}
    secrets = {k.removeprefix("secret__"): v for k, v in cleaned.items() if k.startswith("secret__") and v}
    return config, secrets


@never_cache
@login_required
def connection_list(request):
    _need(request, "view")
    by_category = {}
    for conn in Connection.objects.all():
        by_category.setdefault(providers.CATEGORIES.get(conn.category, conn.category), []).append(conn)
    available = [p for p in providers.PROVIDERS.values()]
    on_business_site = connection.schema_name != "public"
    webhook_url = request.build_absolute_uri("/webhooks/whatsapp/").replace("http://", "https://", 1) if on_business_site else ""
    from apps.backups.google_connect import redirect_uri

    google_redirect_url = redirect_uri(request)
    return render(
        request,
        "vault/connection_list.html",
        _context(request, title="Integrations and API keys", by_category=by_category, available=available, categories=providers.CATEGORIES,
                 can_manage=access.allowed(request, "manage"), can_configure=access.allowed(request, "configure"), webhook_url=webhook_url,
                 google_redirect_url=google_redirect_url),
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def connection_add(request, provider_code):
    _need(request, "manage")
    try:
        provider = providers.get(provider_code)
    except KeyError:
        messages.error(request, "This provider is not available yet.")
        return redirect("vault:list")
    form = build_form(provider, editing=False, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        config, secrets = _split(form.cleaned_data)
        try:
            conn = services.create_connection(
                provider_code=provider.code, label=form.cleaned_data["label"], config=config, secrets=secrets,
                is_backup=form.cleaned_data["is_backup"], actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"{conn.label} saved. Click “Test connection” to check it works.")
            return redirect("vault:list")
    return render(request, "vault/connection_form.html", _context(request, title=f"Connect {provider.label}", form=form, provider=provider))


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def connection_edit(request, pk):
    _need(request, "configure")
    conn = get_object_or_404(Connection, pk=pk)
    provider = providers.get(conn.provider)
    initial = {"label": conn.label, "is_backup": conn.is_backup, **{f"config__{k}": v for k, v in conn.config.items()}}
    form = build_form(provider, editing=True, data=request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        config, secrets = _split(form.cleaned_data)
        if secrets and not access.allowed(request, "manage"):
            form.add_error(None, "Changing secret values needs the 'Manage integrations' permission.")
        else:
            try:
                services.update_connection(conn, label=form.cleaned_data["label"], config=config, secrets=secrets, is_backup=form.cleaned_data["is_backup"], actor=request.user)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, f"{conn.label} updated.")
                return redirect("vault:list")
    return render(request, "vault/connection_form.html", _context(request, title=f"Edit {conn.label}", form=form, provider=provider, connection=conn))


@login_required
@require_POST
def connection_test(request, pk):
    _need(request, "configure")
    conn = get_object_or_404(Connection, pk=pk)
    result = services.test_connection(conn, actor=request.user)
    (messages.success if result.ok else messages.error)(request, f"{conn.label}: {result.message}")
    return redirect("vault:list")


@login_required
@require_POST
def connection_toggle(request, pk):
    _need(request, "configure")
    conn = get_object_or_404(Connection, pk=pk)
    services.set_disabled(conn, conn.status != Connection.Status.DISABLED, actor=request.user)
    return redirect("vault:list")


@login_required
@require_POST
def connection_delete(request, pk):
    _need(request, "manage")
    conn = get_object_or_404(Connection, pk=pk)
    label = conn.label
    services.delete_connection(conn, actor=request.user)
    messages.success(request, f"{label} removed.")
    return redirect("vault:list")
