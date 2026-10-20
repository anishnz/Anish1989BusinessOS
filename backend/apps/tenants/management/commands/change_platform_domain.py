"""
Move the platform to a new address, for example from a laptop (localhost)
to the real domain. Every business subdomain moves with it:

    gorkhabutchery.localhost  ->  gorkhabutchery.example.co.nz

Shows the changes first. Nothing changes without --apply.
Afterwards set PLATFORM_DOMAIN, DJANGO_ALLOWED_HOSTS and
DJANGO_CSRF_TRUSTED_ORIGINS in .env to the new address and restart.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.tenants import domains


class Command(BaseCommand):
    help = "Move the platform address and every business subdomain to a new platform domain."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="old", required=True, help="Current platform address, e.g. localhost")
        parser.add_argument("--to", dest="new", required=True, help="New platform address, e.g. example.co.nz")
        parser.add_argument("--apply", action="store_true", help="Make the changes (without it, only show them)")

    def handle(self, *args, **options):
        old, new = options["old"].strip().lower().rstrip("."), options["new"].strip().lower().rstrip(".")
        if not new or new == old or " " in new or "/" in new or ":" in new:
            raise CommandError("Give a new address without http://, a port or a path, for example example.co.nz")
        changes = domains.platform_domain_changes(old, new)
        if not changes:
            raise CommandError(f"No addresses use {old}.")
        for domain, target in changes:
            self.stdout.write(f"  {domain.domain}  ->  {target}")
        if not options["apply"]:
            self.stdout.write(self.style.WARNING(f"{len(changes)} address(es) would change. Run again with --apply to change them."))
            return
        try:
            domains.change_platform_domain(old, new)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Moved {len(changes)} address(es) to {new}. Now set PLATFORM_DOMAIN={new} (and the allowed hosts) in .env and restart."
        ))
