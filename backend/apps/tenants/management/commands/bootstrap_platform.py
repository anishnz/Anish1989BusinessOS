from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenants.services import create_public_tenant


class Command(BaseCommand):
    help = "Create the platform (public schema) tenant and its domain. Safe to run many times."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default=settings.PLATFORM_DOMAIN, help="Platform domain (default: PLATFORM_DOMAIN)")

    def handle(self, *args, **options):
        tenant = create_public_tenant(options["domain"])
        self.stdout.write(self.style.SUCCESS(f"Platform tenant ready: {tenant} at {options['domain']}"))
