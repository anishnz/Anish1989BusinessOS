from django.apps import AppConfig

PERSONAL_FIELDS = {"name", "phone", "email", "address", "notes"}


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.customers"
    verbose_name = "Customers"

    def ready(self):
        from apps.audit.tracking import track

        from .models import Customer

        # Personal details are never copied into the audit log (it cannot be
        # edited), so they can be removed when a customer asks.
        track(Customer, exclude={"updated_at"}, personal=PERSONAL_FIELDS)
