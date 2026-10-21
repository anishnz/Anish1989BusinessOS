from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.demo import services


class Command(BaseCommand):
    help = "Delete every test business (made by install_test_data) and the platform test accounts. Real businesses are never touched."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Do it without asking.")

    def handle(self, *args, **options):
        names = [t.name for t in services.test_businesses()]
        if not options["yes"]:
            answer = input(f"Delete these test businesses: {', '.join(names) or 'none'}? Type DELETE: ")
            if answer.strip() != "DELETE":
                raise CommandError("Nothing deleted.")
        try:
            for line in services.remove(actor_email="command line"):
                self.stdout.write(line)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
