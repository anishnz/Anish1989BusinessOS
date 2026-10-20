"""
Pretend a customer sent a WhatsApp message, without Meta (for testing on a laptop).

The message goes through the real webhook: signature check, phone number
check, customer lookup and the inbox.

    python manage.py whatsapp_simulate --schema gorkhabutchery --from "021 123 4567" --text "1 kg goat please" --name "Sita"
"""
import hashlib
import hmac
import json
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django_tenants.utils import tenant_context

from apps.customers.services import normalise_phone
from apps.tenants.models import Tenant
from apps.vault import services as vault
from apps.vault.models import Connection


class Command(BaseCommand):
    help = "Send a pretend incoming WhatsApp message through the real webhook (testing only)."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Business id, e.g. gorkhabutchery")
        parser.add_argument("--from", dest="sender", required=True, help="Customer phone, e.g. 021 123 4567")
        parser.add_argument("--text", required=True)
        parser.add_argument("--name", default="Test customer", help="WhatsApp profile name")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(schema_name=options["schema"]).exclude(schema_name="public").first()
        if tenant is None:
            raise CommandError(f"No business with the id '{options['schema']}'.")
        with tenant_context(tenant):
            conn = Connection.objects.filter(provider="whatsapp_cloud").exclude(status=Connection.Status.DISABLED).first()
            if conn is None:
                raise CommandError("This business has no WhatsApp connection. Add one on the Integrations page (test values are fine).")
            app_secret = vault.read_secrets(conn).get("app_secret", "")
            phone_number_id = conn.config["phone_number_id"]
        try:
            wa_id = normalise_phone(options["sender"]).lstrip("+")
        except Exception as exc:
            raise CommandError(str(exc)) from None
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{"id": "0", "changes": [{"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "0", "phone_number_id": phone_number_id},
                "contacts": [{"profile": {"name": options["name"]}, "wa_id": wa_id}],
                "messages": [{"from": wa_id, "id": f"wamid.SIMULATED.{uuid.uuid4().hex}", "timestamp": str(int(time.time())), "type": "text", "text": {"body": options["text"]}}],
            }}]}],
        }
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        client = Client(HTTP_HOST=tenant.get_primary_domain().domain)
        response = client.post("/webhooks/whatsapp/", body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature, secure=True)
        if response.status_code != 200:
            raise CommandError(f"The webhook answered {response.status_code}.")
        self.stdout.write(self.style.SUCCESS(f"Message from +{wa_id} delivered to {tenant.name}'s inbox."))
