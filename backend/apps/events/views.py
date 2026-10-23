"""
The public enquiry form (task 3.1, D-172 and D-173): /enquiry/ on a
business's address, and /enquiry/thanks/ after sending.

Like the website (D-164) it sets no cookies and has no session, so there is
no CSRF token: the form only creates a new enquiry, and the spam checks in
spam.py protect it. Nothing about other enquiries or customers is shown.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_safe

from apps.accounts.security import client_ip

from . import services, spam
from .models import Enquiry

FIELDS = ("contact_name", "contact_phone", "contact_email", "event_type", "event_date", "start_time", "guests", "venue",
          "menu", "dietary_needs", "budget", "message")
CSP = ("default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")
CSP_TURNSTILE = (f"default-src 'self'; script-src {spam.TURNSTILE_ORIGIN}; frame-src {spam.TURNSTILE_ORIGIN}; "
                 f"connect-src {spam.TURNSTILE_ORIGIN}; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                 "base-uri 'none'; form-action 'self'")


def _require_form() -> None:
    if not services.form_available():
        raise Http404("No enquiry form here.")


def _page(template: str, context: dict, *, keys=None, status: int = 200) -> HttpResponse:
    from apps.setup.services import business_name

    settings = services.current_settings()
    html = render_to_string(template, {"business": business_name(), "s": settings, "year": timezone.localdate().year,
                                       "turnstile": keys, "turnstile_script": spam.TURNSTILE_SCRIPT, **context})
    response = HttpResponse(html, status=status)
    response["Content-Security-Policy"] = CSP_TURNSTILE if keys else CSP
    response["Referrer-Policy"] = "same-origin"
    return response


def _form(values: dict, errors: dict, keys, *, status: int = 200) -> HttpResponse:
    today = timezone.localdate()
    return _page("events/enquiry_form.html", {
        "v": values, "errors": errors, "types": Enquiry.EventType.choices, "stamp": spam.stamp(),
        "honeypot": spam.HONEYPOT, "today": today.isoformat(),
    }, keys=keys, status=status)


@never_cache
@csrf_exempt
@require_http_methods(["GET", "HEAD", "POST"])
def enquiry_form(request):
    _require_form()
    keys = spam.turnstile()
    if request.method != "POST":
        return _form({}, {}, keys)

    values = {k: str(request.POST.get(k, "")).strip() for k in FIELDS}
    values["marketing"] = request.POST.get("marketing") == "yes"
    if request.POST.get(spam.HONEYPOT):  # a bot: pretend it worked, save nothing
        return HttpResponseRedirect("/enquiry/thanks/")
    errors: dict[str, str] = {}
    if not spam.stamp_ok(request.POST.get("started", "")):
        errors["form"] = "The form was sent too quickly or is too old. Please check your details and send it again."
    elif spam.over_limit(client_ip(request)):
        return _form(values, {"form": "Too many enquiries were sent. Please try again later, or call or message us."}, keys, status=429)
    elif keys is not None:
        passed, _reason = spam.check_turnstile(keys, request.POST.get("cf-turnstile-response", ""),
                                               address=client_ip(request), host=request.get_host().split(":")[0])
        if not passed:
            errors["form"] = "The spam check did not pass. Please try again."

    # What the form needs (the AI and staff may leave these empty)
    if not values["contact_name"]:
        errors["contact_name"] = "Please give your name."
    if not values["contact_phone"] and not values["contact_email"]:
        errors["contact_phone"] = "Please give a phone number or an email address, so we can reply."
    if not values["event_date"]:
        errors["event_date"] = "Please give the date of the event."
    if not values["guests"]:
        errors["guests"] = "Please give the number of guests (a rough number is fine)."
    try:
        services.clean_details(values)
    except ValidationError as exc:
        for key, messages in getattr(exc, "message_dict", {"form": exc.messages}).items():
            errors.setdefault(key, " ".join(messages))
    if errors:
        return _form(values, errors, keys, status=400)
    try:
        services.create(values, source=Enquiry.Source.WEBSITE, marketing_consent=values["marketing"])
    except ValidationError as exc:
        return _form(values, {k: " ".join(v) for k, v in getattr(exc, "message_dict", {"form": exc.messages}).items()}, keys, status=400)
    return HttpResponseRedirect("/enquiry/thanks/")


@require_safe
def enquiry_thanks(request):
    _require_form()
    response = _page("events/enquiry_thanks.html", {})
    response["Cache-Control"] = "public, max-age=300"
    return response
