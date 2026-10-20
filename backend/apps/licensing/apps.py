from django.apps import AppConfig


class LicensingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.licensing"
    verbose_name = "Licences and modules"

    def ready(self):
        from apps.audit.tracking import track

        from . import signals  # noqa: F401
        from .models import Licence, TenantModule

        track(Licence)
        track(TenantModule)
