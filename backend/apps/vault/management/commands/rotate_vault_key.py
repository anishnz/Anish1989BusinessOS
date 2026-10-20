from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, schema_context

from apps.vault import crypto
from apps.vault.services import rotate_master_key


class Command(BaseCommand):
    help = (
        "Re-encrypt every saved key's data key with the newest master key (the first in VAULT_MASTER_KEYS). "
        "Steps: 1) put the new key first in VAULT_MASTER_KEYS and keep the old one after it, "
        "2) restart, 3) run this command, 4) remove the old key."
    )

    def handle(self, *args, **options):
        kid = crypto.master_keys()[0][0]
        total = 0
        for schema in get_tenant_model().objects.values_list("schema_name", flat=True):
            with schema_context(schema):
                count = rotate_master_key()
            total += count
            self.stdout.write(f"{schema}: {count} connection(s) re-wrapped")
        self.stdout.write(self.style.SUCCESS(f"Done. {total} connection(s) now use key '{kid}'."))
