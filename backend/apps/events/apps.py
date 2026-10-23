from django.apps import AppConfig


class EventsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    verbose_name = "Catering and events"

    def ready(self):
        from apps.customers.signals import customer_anonymised

        from . import services

        customer_anonymised.connect(services.forget_customer, dispatch_uid="events.forget_customer")
