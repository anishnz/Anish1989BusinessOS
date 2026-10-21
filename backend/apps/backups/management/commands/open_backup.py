"""
Open (decrypt and unpack) a backup file into a folder, for a real restore.

Platform backups open with BACKUP_ENCRYPTION_KEYS from .env. Business backups
ask for the passphrase (it is typed, never given on the command line).
Afterwards load the database with pg_restore (see the user guide, chapter 12).
"""
import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.backups import keys
from apps.backups.fileformat import BackupFileError, extract_archive, read_header


class Command(BaseCommand):
    help = "Decrypt a .a1989backup file into a folder (manifest.json, database.dump, media/)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("folder", help="Empty folder to unpack into (created if missing)")

    def handle(self, *args, **options):
        try:
            with open(options["file"], "rb") as fh:
                header, _ = read_header(fh)
                fh.seek(0)
                if header["key"]["type"] == "passphrase":
                    opened = extract_archive(fh, options["folder"], passphrase=getpass.getpass("Backup passphrase: "))
                else:
                    opened = extract_archive(fh, options["folder"], keys=keys.platform_keys())
        except (OSError, BackupFileError) as exc:
            raise CommandError(str(exc)) from None
        tables = opened.get("tables", {})
        self.stdout.write(self.style.SUCCESS(f"Opened into {options['folder']}"))
        self.stdout.write(f"Made {opened.get('created_at')} · {opened.get('site_name')} · {len(tables)} tables, {sum(tables.values())} rows")
        self.stdout.write("Load it into an EMPTY database with: pg_restore --no-owner --no-privileges -d <database> database.dump")
