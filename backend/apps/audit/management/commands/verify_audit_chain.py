from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_tenant_model, schema_context

from apps.audit.services import verify_chain


class Command(BaseCommand):
    help = "Check that no audit event has been changed or removed, in every schema (or one with --schema)."

    def add_arguments(self, parser):
        parser.add_argument("--schema", help="Only check this schema")

    def handle(self, *args, **options):
        schemas = [options["schema"]] if options["schema"] else list(
            get_tenant_model().objects.values_list("schema_name", flat=True)
        )
        failed = False
        for schema in schemas:
            with schema_context(schema):
                ok, problems = verify_chain()
            if ok:
                self.stdout.write(self.style.SUCCESS(f"{schema}: audit log OK"))
            else:
                failed = True
                self.stdout.write(self.style.ERROR(f"{schema}: {len(problems)} problem(s)"))
                for problem in problems[:20]:
                    self.stdout.write(f"  - {problem}")
        if failed:
            raise CommandError("Audit log check failed.")
