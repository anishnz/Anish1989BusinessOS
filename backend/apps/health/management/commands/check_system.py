"""Run the "Check system" checks from the server (the platform, one business, or all)."""
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context

from apps.health import services
from apps.health.models import CheckRun
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Run the system checks and show the results."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=get_public_schema_name(), help="Business id (default: the platform)")
        parser.add_argument("--all", action="store_true", help="Every business, then the platform (like the hourly schedule)")
        parser.add_argument("--no-live", action="store_true", help="Do not test saved connections with the providers")

    def handle(self, *args, **options):
        if options["all"]:
            for schema, status in services.run_everywhere(CheckRun.Trigger.COMMAND).items():
                self.stdout.write(f"{schema}: {status}")
            return
        schema = options["schema"]
        if not Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(f"No business with the id '{schema}'.")
        with schema_context(schema):
            record = services.run(CheckRun.Trigger.COMMAND, live=not options["no_live"])
        for r in record.results:
            self.stdout.write(f"[{r['status'].upper():10}] {r['area']} / {r['label']}: {r['message']}")
        style = self.style.SUCCESS if record.status == "ok" else (self.style.WARNING if record.status == "warning" else self.style.ERROR)
        self.stdout.write(style(f"Overall: {record.status} ({record.seconds} s)"))
        if record.status == "failed":
            raise SystemExit(1)
