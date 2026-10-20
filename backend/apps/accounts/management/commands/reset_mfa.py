from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import tenant_context

from apps.accounts import security
from apps.accounts.models import User
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Reset someone's two-step verification (for example a Super Admin who lost their phone). They set it up again at the next login."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--schema", default="public", help="Business id; leave out for platform (Super Admin) accounts")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(schema_name=options["schema"]).first()
        if tenant is None:
            raise CommandError(f"No business with the id '{options['schema']}'.")
        with tenant_context(tenant):
            user = User.objects.filter(email__iexact=options["email"].strip()).first()
            if user is None:
                raise CommandError(f"No user with the email {options['email']} in {tenant.name}.")
            security.reset_mfa(user, by_email="server command (reset_mfa)")
        self.stdout.write(self.style.SUCCESS(f"Two-step verification reset for {user.email}. They will set it up again at the next login."))
