"""
Super Admin page (platform site only): a business's web addresses.

/platform/businesses/<business id>/addresses/

tenants.view to look; tenants.edit to add an address, choose the main one,
or remove one.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django_tenants.utils import get_public_schema_name

from apps.rbac import policy

from . import domains
from .models import Domain, Tenant


class AddAddressForm(forms.Form):
    label = forms.CharField(max_length=63, label="New web address name", help_text="Lowercase letters, numbers and hyphens, e.g. gorkha-butchery.")
    make_main = forms.BooleanField(required=False, label="Make it the main address")


def _require(request, code: str) -> None:
    if not policy.require(request.user, code, request=request):
        raise PermissionDenied


@never_cache
def addresses(request, schema: str):
    _require(request, "tenants.view")
    tenant = Tenant.objects.filter(schema_name=schema).exclude(schema_name=get_public_schema_name()).first()
    if tenant is None:
        raise Http404("No such business.")
    here = reverse("platform_addresses", args=[schema])
    can_change = policy.has_perm(request.user, "tenants.edit")
    form = AddAddressForm()

    if request.method == "POST":
        _require(request, "tenants.edit")
        action = request.POST.get("action", "")
        try:
            if action == "add":
                form = AddAddressForm(request.POST)
                if form.is_valid():
                    domain = domains.add_subdomain(tenant, form.cleaned_data["label"], make_main=form.cleaned_data["make_main"], actor=request.user, request=request)
                    messages.success(request, f"Added {domain.domain}." + (" It is now the main address." if domain.is_primary else ""))
                    return redirect(here)
            else:
                domain = Domain.objects.filter(tenant=tenant, pk=request.POST.get("domain") or 0).first() \
                    if str(request.POST.get("domain", "")).isdigit() else None
                if domain is None:
                    raise ValidationError("That address does not belong to this business.")
                if action == "main":
                    domains.make_main(domain, actor=request.user, request=request)
                    messages.success(request, f"{domain.domain} is now the main address. Visitors on the other addresses are sent there.")
                elif action == "remove":
                    domains.remove(domain, actor=request.user, request=request)
                    messages.success(request, f"Removed {domain.domain}. It no longer opens this business.")
                else:
                    raise ValidationError("Unknown action.")
                return redirect(here)
        except ValidationError as exc:
            if action == "add":
                form.add_error("label", exc)
            else:
                messages.error(request, " ".join(exc.messages))
                return redirect(here)

    rows = [{"domain": d, "url": domains.site_url(d.domain, request)} for d in domains.addresses(tenant)]
    return render(request, "tenants/platform/addresses.html", {
        **admin.site.each_context(request),
        "title": f"Web addresses of {tenant.name}",
        "tenant": tenant,
        "rows": rows,
        "form": form,
        "can_change": can_change,
        "suffix": "." + domains.platform_domain(),
        "max_addresses": domains.MAX_SUBDOMAINS,
        "back": reverse("admin:tenants_tenant_change", args=[tenant.pk]),
    })
