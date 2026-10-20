from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, tenant_context

from apps.orders.services import expire_unconfirmed


class Command(BaseCommand):
    help = "Mark orders that waited too long for the customer's confirmation as Expired (every business)."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=60, help="How long to wait for confirmation (default 60)")

    def handle(self, *args, **options):
        total = 0
        for tenant in get_tenant_model().objects.exclude(schema_name="public"):
            with tenant_context(tenant):
                count = expire_unconfirmed(minutes=options["minutes"])
            if count:
                self.stdout.write(f"{tenant.schema_name}: {count} order(s) expired")
            total += count
        self.stdout.write(self.style.SUCCESS(f"Done: {total} order(s) expired."))
