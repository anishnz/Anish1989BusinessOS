from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import tenant_context

from apps.tenants.models import Tenant
from apps.vault import mail


class Command(BaseCommand):
    help = "Send one test email through the saved email connection (Gmail or SMTP)."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Address that receives the test email")
        parser.add_argument("--schema", default="public", help="Business id to test (default: the platform)")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(schema_name=options["schema"]).first()
        if tenant is None:
            raise CommandError(f"No business with the id '{options['schema']}'.")
        with tenant_context(tenant):
            smtp = mail.resolve()
            via = f"{smtp.from_address} (connection {smtp.connection_id} in {smtp.schema})" if smtp else "the fallback backend (no email connection saved)"
            self.stdout.write(f"Sending through {via}...")
            try:
                send_mail(
                    subject="Test email from Anish1989 Business OS",
                    message=f"This is a test email for {tenant.name}. If you can read this, email sending works.",
                    from_email=None,
                    recipient_list=[options["to"]],
                )
            except Exception as exc:  # noqa: BLE001 - show a short reason, never secrets
                raise CommandError(f"Sending failed: {type(exc).__name__}. Check the email connection and run Test connection.") from None
        self.stdout.write(self.style.SUCCESS(f"Test email sent to {options['to']}."))
