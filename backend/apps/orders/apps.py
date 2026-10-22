from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    verbose_name = "Orders"

    def ready(self):
        from apps.audit.tracking import track

        from apps.inbox.services import message_received

        from apps.customers.signals import customer_anonymised

        from . import feedback
        from .models import Order
        from .notify import on_message_received

        # Yes and No answers on WhatsApp (task 2.3), then star feedback (task 2.7).
        # Both run before the AI assistant (apps.ai is later in TENANT_APPS), which leaves answered messages alone.
        message_received.connect(on_message_received, dispatch_uid="orders.answers")
        message_received.connect(feedback.on_message_received, dispatch_uid="orders.feedback")
        customer_anonymised.connect(feedback.forget_customer, dispatch_uid="orders-forget-feedback")

        # Lines and status changes are audited by the services with clear actions.
        track(Order, exclude={"updated_at", "estimated_total", "total", "gst_total", "due_until"},
              personal={"notes", "delivery_address", "delivery_suburb", "delivery_postcode"})
