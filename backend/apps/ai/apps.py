from django.apps import AppConfig


class AIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "AI assistant"

    def ready(self):
        from apps.customers.signals import customer_anonymised
        from apps.inbox.services import message_received

        from .agent import forget_customer, on_message_received

        # Connected after the orders app (TENANT_APPS order), so a Yes/No answer to an
        # order question is handled first and the AI leaves it alone (task 2.4).
        message_received.connect(on_message_received, dispatch_uid="ai.answer")
        customer_anonymised.connect(forget_customer, dispatch_uid="ai-forget-customer")
