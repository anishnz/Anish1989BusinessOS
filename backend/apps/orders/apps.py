from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    verbose_name = "Orders"

    def ready(self):
        from apps.audit.tracking import track

        from apps.inbox.services import message_received

        from .models import Order
        from .notify import on_message_received

        # Yes and No answers on WhatsApp (task 2.3).
        message_received.connect(on_message_received, dispatch_uid="orders.answers")

        # Lines and status changes are audited by the services with clear actions.
        track(Order, exclude={"updated_at", "estimated_total", "total", "gst_total", "due_until"},
              personal={"notes", "delivery_address", "delivery_suburb", "delivery_postcode"})
