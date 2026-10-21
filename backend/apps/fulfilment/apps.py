from django.apps import AppConfig


class FulfilmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fulfilment"
    verbose_name = "Pickup and delivery"

    def ready(self):
        from apps.audit.tracking import track

        from .models import ClosedDay, DeliveryArea, FulfilmentSettings, OpeningHours

        track(FulfilmentSettings, exclude={"updated_at"})
        track(OpeningHours)
        track(ClosedDay, exclude={"created_at"})
        track(DeliveryArea, exclude={"created_at", "updated_at"})
