"""
The business's own page for its web addresses (task 2.8): /settings/web-addresses/

Settings – View to look; Settings – Configure (System Admin, IT Admin) to add
an own domain, check it now, make an address the main one, or remove an own
domain. Platform subdomains are still added by the Super Admin.
"""
from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django_tenants.utils import get_public_schema_name, schema_context

from apps.core import deleteguard
from apps.rbac import policy

from . import custom_domains, domains
from .models import CustomDomain, Domain, Tenant

CHECK_NOW_EVERY = timedelta(minutes=1)


class AddDomainForm(forms.Form):
    name = forms.CharField(max_length=253, label="Your domain", help_text="For example gorkhabutchery.co.nz or shop.gorkhabutchery.co.nz.")


def _require(request, code: str) -> None:
    if not policy.require(request.user, code, request=request):
        raise PermissionDenied


def _tenant() -> Tenant:
    schema = connection.schema_name  # read before switching to the platform's tables
    with schema_context(get_public_schema_name()):
        return Tenant.objects.get(schema_name=schema)


@never_cache
def web_addresses(request):
    _require(request, "settings.view")
    tenant = _tenant()
    here = reverse("web_addresses")
    can_change = policy.has_perm(request.user, "settings.configure")
    form = AddDomainForm()
    if request.method == "POST":
        _require(request, "settings.configure")
        action = request.POST.get("action", "")
        try:
            with schema_context(get_public_schema_name()):
                result = _post(request, tenant, action, here)
            if isinstance(result, AddDomainForm):
                form = result
            else:
                return result
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(here)
    with schema_context(get_public_schema_name()):
        rows = [{"domain": d, "url": domains.site_url(d.domain, request), "own": hasattr(d, "custom")}
                for d in Domain.objects.filter(tenant=tenant).select_related("custom").order_by("-is_primary", "domain")]
        own = list(CustomDomain.objects.filter(tenant=tenant).order_by("name"))
        main_platform = Domain.objects.filter(tenant=tenant, custom__isnull=True).order_by("-is_primary", "created_at").first()
        server_ips = sorted(custom_domains.server_ips()) if any(c.status == CustomDomain.Status.PENDING for c in own) else []
    return render(request, "tenants/business/web_addresses.html", {
        **admin.site.each_context(request), "title": "Web addresses", "tenant": tenant, "rows": rows, "own": own, "form": form,
        "can_change": can_change, "server_ips": server_ips, "cname_target": main_platform.domain if main_platform else "",
        "max_own": custom_domains.MAX_PER_BUSINESS,
    })


def _post(request, tenant, action: str, here: str):
    if action == "add":
        form = AddDomainForm(request.POST)
        if not form.is_valid():
            return form
        try:
            cd = custom_domains.add(tenant, form.cleaned_data["name"], actor=request.user, request=request, by_business=True)
        except ValidationError as exc:
            form.add_error("name", exc)
            return form
        messages.success(request, f"Added {cd.name}. Now add the two DNS records below at your domain company.")
        return redirect(here)
    if action == "main":
        domain = Domain.objects.filter(tenant=tenant, pk=_id(request)).select_related("custom").first()
        if domain is None:
            raise ValidationError("That address does not belong to this business.")
        custom = getattr(domain, "custom", None)
        if custom is not None and custom.status != CustomDomain.Status.LIVE:
            raise ValidationError(f"{domain.domain} has a DNS problem. Fix it first.")
        custom_domains.make_main_by_business(domain, actor=request.user, request=request)
        messages.success(request, f"{domain.domain} is now the main address. Sign in again there.")
        return redirect(here)
    cd = CustomDomain.objects.filter(tenant=tenant, pk=_id(request)).first()
    if cd is None:
        raise ValidationError("That domain does not belong to this business.")
    if action == "check":
        if cd.last_checked_at and timezone.now() - cd.last_checked_at < CHECK_NOW_EVERY:
            raise ValidationError("It was checked less than a minute ago. DNS changes can take up to a few hours; try again later.")
        cd = custom_domains.check(cd, actor=request.user, by_business=True)
        level = messages.success if cd.status == CustomDomain.Status.LIVE else messages.warning
        level(request, f"{cd.name}: {cd.get_status_display()}. {cd.last_result}")
        return redirect(here)
    if action == "remove":
        if cd.domain_id and Domain.objects.filter(pk=cd.domain_id, is_primary=True).exists():
            raise ValidationError("This is the main address. Make another address the main one first.")
        page = deleteguard.require(
            request, title=f"Remove {cd.name}?", back=here, fields={"action": "remove", "id": cd.pk},
            message=f"{cd.name} will stop opening {tenant.name}. Links, QR codes and posters that use it will stop working.")
        if page is not None:
            return page
        custom_domains.remove(cd, actor=request.user, request=request, by_business=True)
        messages.success(request, f"Removed {cd.name}. You can also delete its DNS records at your domain company.")
        return redirect(here)
    raise ValidationError("Unknown action.")


def _id(request) -> int:
    value = str(request.POST.get("id", ""))
    return int(value) if value.isdigit() else 0
