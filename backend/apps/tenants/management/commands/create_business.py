from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant


class Command(BaseCommand):
    help = "Create a business tenant with its own schema and subdomain."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help='Business name, e.g. "Gorkha Butchery"')
        parser.add_argument("--slug", required=True, help="Short id, e.g. gorkhabutchery (becomes the schema name)")
        parser.add_argument("--subdomain", default="", help="Web address name (default: the slug with hyphens), e.g. gorkha")
        parser.add_argument("--industry", default=Tenant.Industry.OTHER, choices=[c for c in Tenant.Industry.values if c != "platform"])

    def handle(self, *args, **options):
        try:
            tenant = create_tenant(options["name"], options["slug"], options["industry"], subdomain=options["subdomain"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        domain = tenant.get_primary_domain()
        self.stdout.write(self.style.SUCCESS(f"Created {tenant} at {domain.domain}"))
