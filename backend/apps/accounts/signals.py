from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import security
from .models import LoginEvent


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    security.clear_failures(user.email)
    security.record_event(LoginEvent.Event.LOGIN_SUCCESS, request, user=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    email = (credentials.get("username") or credentials.get("email") or "").strip().lower()
    if request is not None and getattr(request, "login_locked_out", False):
        security.record_event(LoginEvent.Event.LOCKED_OUT, request, email=email)
        return
    if email:
        security.register_failure(email)
    security.record_event(LoginEvent.Event.LOGIN_FAILED, request, email=email)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        security.record_event(LoginEvent.Event.LOGOUT, request, user=user)
