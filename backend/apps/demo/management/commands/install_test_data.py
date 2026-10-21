from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.demo import services


class Command(BaseCommand):
    help = "Make the six test businesses with made-up data (needs DEMO_PASSWORD in .env). Existing test businesses are left as they are."

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="*", help="Schema names, for example test_butchery")

    def handle(self, *args, **options):
        try:
            for line in services.install(actor_email="command line", only=options.get("only") or None):
                self.stdout.write(line)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
