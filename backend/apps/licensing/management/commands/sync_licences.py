from django.core.management.base import BaseCommand

from apps.licensing.services import create_licence
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Give every business that has no licence yet a trial licence and its industry's modules. Safe to run many times."

    def handle(self, *args, **options):
        created = 0
        for tenant in Tenant.objects.exclude(schema_name="public").filter(licence__isnull=True):
            create_licence(tenant)
            created += 1
            self.stdout.write(f"{tenant.schema_name}: trial licence created")
        self.stdout.write(self.style.SUCCESS(f"Done. {created} licence(s) created."))
