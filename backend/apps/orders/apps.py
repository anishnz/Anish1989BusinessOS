from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    verbose_name = "Orders"

    def ready(self):
        from apps.audit.tracking import track

        from .models import Order

        # Lines and status changes are audited by the services with clear actions.
        track(Order, exclude={"updated_at", "estimated_total", "total", "gst_total"}, personal={"notes"})
