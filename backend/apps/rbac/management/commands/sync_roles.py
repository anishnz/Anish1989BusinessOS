from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, schema_context

from apps.rbac.services import sync_default_roles


class Command(BaseCommand):
    help = "Create missing default roles in every schema. Existing roles and admins' changes are kept."

    def handle(self, *args, **options):
        for schema in get_tenant_model().objects.values_list("schema_name", flat=True):
            with schema_context(schema):
                created = sync_default_roles(schema)
            self.stdout.write(f"{schema}: {created} role(s) created")
