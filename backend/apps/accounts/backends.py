from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

from . import security


class LockoutEmailBackend(ModelBackend):
    """
    Email + password login for the current tenant schema.

    After LOGIN_LOCKOUT_ATTEMPTS failures for an email address, every attempt
    (even with the right password) is refused for LOGIN_LOCKOUT_SECONDS.
    The counter is per tenant and per email, so it does not reveal whether
    an account exists.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = (username or kwargs.get("email") or "").strip().lower()
        if email and security.is_locked_out(email):
            if request is not None:
                request.login_locked_out = True
            # PermissionDenied stops authentication and fires user_login_failed.
            raise PermissionDenied("Too many failed login attempts.")
        return super().authenticate(request, username=email, password=password, **kwargs)
