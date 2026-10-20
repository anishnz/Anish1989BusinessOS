from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Audit log"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django_otp.plugins.otp_static.models import StaticDevice
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from .tracking import track

        # Records whose changes are always audited. Secrets are never stored.
        track(get_user_model(), exclude={"last_login"})
        track(TOTPDevice, exclude={"key", "last_t", "drift", "throttling_failure_timestamp", "throttling_failure_count", "last_used_at", "created_at"})
        track(StaticDevice, exclude={"throttling_failure_timestamp", "throttling_failure_count", "last_used_at", "created_at"})
