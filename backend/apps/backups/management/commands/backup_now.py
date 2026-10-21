"""Make a backup (and/or a restore test) now, from the server, without the worker."""
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, schema_context
from django.utils import timezone

from apps.backups import services
from apps.backups.models import BackupRun
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Make a backup of the platform (default) or one business now, then optionally test restoring it."

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=get_public_schema_name(), help="Business id (default: the platform, every business)")
        parser.add_argument("--restore-test", action="store_true", help="Also test restoring the new backup")
        parser.add_argument("--only-restore-test", action="store_true", help="Only test restoring the newest backup")

    def handle(self, *args, **options):
        schema = options["schema"]
        if not Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(f"No business with the id '{schema}'.")
        kinds = []
        if not options["only_restore_test"]:
            kinds.append(BackupRun.Kind.BACKUP)
        if options["restore_test"] or options["only_restore_test"]:
            kinds.append(BackupRun.Kind.RESTORE_TEST)
        failed = False
        with schema_context(schema):
            if not services.is_set_up():
                raise CommandError("Backups of this business are not set up (Google Drive and a passphrase are needed).")
            for kind in kinds:
                run = BackupRun.objects.create(kind=kind, trigger=BackupRun.Trigger.COMMAND, queued_at=timezone.now())
                services.execute(run)
                style = {"ok": self.style.SUCCESS, "warning": self.style.WARNING}.get(run.status, self.style.ERROR)
                self.stdout.write(style(f"{run.get_kind_display()}: {run.get_status_display()}. {run.message}"))
                if run.file_name:
                    self.stdout.write(f"File: {services.local_dir() / run.file_name}")
                failed = failed or run.status == BackupRun.Status.FAILED
        if failed:
            raise SystemExit(1)
