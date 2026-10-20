from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.licensing.services import invite_system_admin
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Create a business's System Admin and email them a link to set their password."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Business id (slug), e.g. gorkhabutchery")
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(schema_name=options["schema"]).first()
        if tenant is None or tenant.schema_name == "public":
            raise CommandError(f"No business with the id '{options['schema']}'.")
        try:
            invite_system_admin(tenant, options["email"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(f"Invitation sent to {options['email']} for {tenant.name}."))
