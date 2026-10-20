from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inbox"
    verbose_name = "Inbox"

    def ready(self):
        from apps.customers.signals import customer_anonymised

        from .services import forget_customer

        customer_anonymised.connect(forget_customer, dispatch_uid="inbox-forget-customer")
