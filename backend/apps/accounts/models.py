"""
User model and login history.

This app is in both SHARED_APPS and TENANT_APPS, so there is one users table
per schema: platform admins live in the public schema, and each business's
staff live in that business's schema. A user in one business cannot log in
to another business's site.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Email login is case-insensitive.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(AbstractUser):
    username = None
    email = models.EmailField("email address", unique=True)
    phone = models.CharField(max_length=30, blank=True)
    # Two-step verification switched off for this person by the platform Super Admin (with a reason).
    mfa_exempt = models.BooleanField("Two-step verification switched off", default=False)
    mfa_exempt_reason = models.CharField(max_length=200, blank=True)
    mfa_exempt_by = models.CharField(max_length=254, blank=True)
    mfa_exempt_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def mfa_required(self) -> bool:
        """Staff and admins must use MFA, unless the Super Admin switched it off for them."""
        return bool(self.is_staff and getattr(settings, "MFA_REQUIRED_FOR_STAFF", True) and not self.mfa_exempt)


class LoginEvent(models.Model):
    """
    Login history: one row per login attempt, logout, MFA check or password reset.
    Never stores passwords, codes or tokens.
    """

    class Event(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "Login success"
        LOGIN_FAILED = "login_failed", "Login failed"
        LOCKED_OUT = "locked_out", "Locked out"
        LOGOUT = "logout", "Logout"
        MFA_SUCCESS = "mfa_success", "MFA success"
        MFA_FAILED = "mfa_failed", "MFA failed"
        MFA_ENABLED = "mfa_enabled", "MFA enabled"
        BACKUP_CODES_CREATED = "backup_codes_created", "Backup codes created"
        AUTHENTICATOR_REPLACED = "authenticator_replaced", "Authenticator app replaced"
        MFA_RESET = "mfa_reset", "MFA reset by an administrator"
        MFA_SWITCHED_OFF = "mfa_switched_off", "MFA switched off by an administrator"
        MFA_SWITCHED_ON = "mfa_switched_on", "MFA switched on again"
        PASSWORD_RESET_REQUESTED = "password_reset_requested", "Password reset requested"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_events")
    email = models.EmailField(blank=True, help_text="Email that was entered (kept even if no such user exists).")
    event = models.CharField(max_length=40, choices=Event.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event} {self.email}"
