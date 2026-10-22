"""
Super Admin page (platform site only): a business's web addresses.

/platform/businesses/<business id>/addresses/

tenants.view to look; tenants.edit to add an address, choose the main one,
or remove one. The business's own domains (task 2.8) are added by the
business; the Super Admin sees them here and can remove them.
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

from apps.core import deleteguard
from apps.rbac import policy

from . import custom_domains, domains
from .models import CustomDomain, Domain, Tenant


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
            elif action == "remove_own":
                cd = CustomDomain.objects.filter(tenant=tenant, pk=request.POST.get("custom") or 0).first() \
                    if str(request.POST.get("custom", "")).isdigit() else None
                if cd is None:
                    raise ValidationError("That domain does not belong to this business.")
                if cd.domain_id and Domain.objects.filter(pk=cd.domain_id, is_primary=True).exists():
                    raise ValidationError("This is the main address. Make another address the main one first.")
                page = deleteguard.require(
                    request, title=f"Remove {cd.name}?", back=here, fields={"action": "remove_own", "custom": cd.pk},
                    message=f"{cd.name} is the business's own domain. It will stop opening {tenant.name}.")
                if page is not None:
                    return page
                custom_domains.remove(cd, actor=request.user, request=request)
                messages.success(request, f"Removed {cd.name}.")
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
                    domains.check_removable(domain)
                    page = deleteguard.require(
                        request, title=f"Remove {domain.domain}?", back=here, fields={"action": "remove", "domain": domain.pk},
                        message=f"{domain.domain} will stop opening {tenant.name}. Links, QR codes and webhooks that use it will stop working. "
                                "Update the WhatsApp webhook first if it uses this address.")
                    if page is not None:  # the safety check is not done yet (task 1.18)
                        return page
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
        "own": CustomDomain.objects.filter(tenant=tenant).order_by("name"),
        "platform_count": Domain.objects.filter(tenant=tenant, custom__isnull=True).count(),
        "back": reverse("admin:tenants_tenant_change", args=[tenant.pk]),
    })
