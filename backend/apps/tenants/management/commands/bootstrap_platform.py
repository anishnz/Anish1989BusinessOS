from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant
from apps.tenants.services import create_public_tenant


class Command(BaseCommand):
    help = "Create the platform (public schema) tenant and its domain. Safe to run many times."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default=settings.PLATFORM_DOMAIN, help="Platform domain (default: PLATFORM_DOMAIN)")

    def handle(self, *args, **options):
        wanted = options["domain"].strip().lower().rstrip(".")
        existing = Tenant.objects.filter(schema_name=settings.PUBLIC_SCHEMA_NAME).first()
        current = existing.get_primary_domain() if existing else None
        if current is not None and current.domain != wanted:
            # Do not add a second platform address: every business address would still use the old one.
            self.stdout.write(self.style.WARNING(
                f"The platform address is {current.domain}, but PLATFORM_DOMAIN is {wanted}. Nothing changed.\n"
                f"To move the platform and every business address, run:\n"
                f"  python manage.py change_platform_domain --from {current.domain} --to {wanted} --apply"
            ))
            return
        tenant = create_public_tenant(wanted)
        self.stdout.write(self.style.SUCCESS(f"Platform tenant ready: {tenant} at {wanted}"))
