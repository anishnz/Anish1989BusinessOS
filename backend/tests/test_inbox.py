"""WhatsApp webhook, sending and the unified inbox (task 1.8)."""
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
import requests
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.customers.models import ConsentRecord, Customer
from apps.customers.services import anonymise, set_marketing_consent
from apps.inbox import services, whatsapp
from apps.inbox.models import Conversation, Message, WebhookDelivery
from apps.vault import services as vault
from tests.test_catalog import user_client
from tests.test_rbac import verified_staff_client

APP_SECRET = "meta-app-secret-123"
TOKEN = "EAAG-access-token-SECRET"
PHONE_ID = "1098765"
WA_ID = "64211234567"


def connect_whatsapp(schema="tenant_a", phone_number_id=PHONE_ID, app_secret=APP_SECRET):
    with schema_context(schema):
        return vault.create_connection(
            provider_code="whatsapp_cloud", label="Shop WhatsApp",
            config={"phone_number_id": phone_number_id, "webhook_verify_token": "verify-me"},
            secrets={"access_token": TOKEN, "app_secret": app_secret},
        )


def incoming(text="1 kg goat please", wa_id=WA_ID, msg_id="wamid.1", phone_number_id=PHONE_ID, name="Sita", kind="text", extra=None):
    message = {"from": wa_id, "id": msg_id, "timestamp": str(int(time.time())), "type": kind}
    message.update(extra or {"text": {"body": text}})
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "6490000000", "phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": name}, "wa_id": wa_id}], "messages": [message],
    }}]}]}


def status_payload(msg_id, status, phone_number_id=PHONE_ID, errors=None):
    item = {"id": msg_id, "status": status, "timestamp": str(int(time.time())), "recipient_id": WA_ID}
    if errors:
        item["errors"] = errors
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": phone_number_id}, "statuses": [item]}}]}]}


def post_webhook(client, payload, secret=APP_SECRET, signature=None):
    body = json.dumps(payload).encode()
    if signature is None:
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp/", body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature)


class FakeGraph:
    def __init__(self, status=200, body=None, raise_exc=None):
        self.calls, self.status, self.body, self.raise_exc = [], status, body, raise_exc

    def __call__(self, url, json=None, headers=None, **kwargs):
        self.calls.append({"url": url, "json": json, "headers": headers, **kwargs})
        if self.raise_exc:
            raise self.raise_exc

        class R:
            status_code = self.status

            def json(inner):
                return self.body if self.body is not None else {"messages": [{"id": f"wamid.out.{len(self.calls)}"}]}

        return R()


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(whatsapp.requests, "post", fake)
    return fake


@pytest.fixture
def wa(tenant_a, client_for):
    connect_whatsapp()
    return client_for(tenant_a)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWebhook:
    def test_meta_verification(self, wa):
        ok = wa.get("/webhooks/whatsapp/", {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
        assert ok.status_code == 200 and ok.content == b"12345" and ok["Content-Type"].startswith("text/plain")
        assert wa.get("/webhooks/whatsapp/", {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}).status_code == 403

    def test_incoming_message_creates_customer_and_conversation(self, wa):
        assert post_webhook(wa, incoming()).status_code == 200
        with schema_context("tenant_a"):
            conversation = Conversation.objects.get()
            customer = conversation.customer
            assert (customer.name, customer.phone, customer.source) == ("Sita", "+64211234567", "whatsapp")
            message = conversation.messages.get()
            assert (message.direction, message.text, message.status) == ("in", "1 kg goat please", "received")
            assert conversation.unread_count == 1 and conversation.last_inbound_at
            assert WebhookDelivery.objects.get().messages == 1

    def test_existing_customer_is_linked(self, wa):
        with schema_context("tenant_a"):
            existing = Customer.objects.create(name="Sita Sharma", phone="+64211234567")
        post_webhook(wa, incoming(name="Someone else"))
        with schema_context("tenant_a"):
            assert Conversation.objects.get().customer == existing
            assert Customer.objects.count() == 1 and Customer.objects.get().name == "Sita Sharma"

    def test_same_message_twice_is_stored_once(self, wa):
        post_webhook(wa, incoming())
        post_webhook(wa, incoming())
        with schema_context("tenant_a"):
            assert Message.objects.count() == 1 and Conversation.objects.get().unread_count == 1

    @pytest.mark.parametrize("signature", ["", "sha256=0000", "sha1=abc"])
    def test_bad_signature_is_refused(self, wa, signature):
        assert post_webhook(wa, incoming(), signature=signature).status_code == 403
        with schema_context("tenant_a"):
            assert not Message.objects.exists()
            assert WebhookDelivery.objects.get().ok is False

    def test_signed_with_another_app_secret_is_refused(self, wa):
        assert post_webhook(wa, incoming(), secret="someone-elses-secret").status_code == 403

    def test_messages_for_another_phone_number_are_ignored(self, wa):
        assert post_webhook(wa, incoming(phone_number_id="999")).status_code == 200
        with schema_context("tenant_a"):
            assert not Message.objects.exists()
            assert "another phone number" in WebhookDelivery.objects.get().note

    def test_business_without_whatsapp_has_no_webhook(self, client_for, tenant_b):
        assert post_webhook(client_for(tenant_b), incoming()).status_code == 404

    def test_platform_site_has_no_webhook(self, client_for, public_tenant):
        assert post_webhook(client_for(public_tenant), incoming()).status_code == 404

    def test_each_business_only_gets_its_own_messages(self, client_for, tenant_a, tenant_b):
        connect_whatsapp("tenant_a")
        connect_whatsapp("tenant_b", phone_number_id="2222", app_secret="b-secret")
        # A message signed for business A but sent to business B's address is refused.
        assert post_webhook(client_for(tenant_b), incoming()).status_code == 403
        assert post_webhook(client_for(tenant_b), incoming(phone_number_id="2222"), secret="b-secret").status_code == 200
        with schema_context("tenant_a"):
            assert not Message.objects.exists()
        with schema_context("tenant_b"):
            assert Message.objects.count() == 1

    @pytest.mark.parametrize(
        "kind,extra,text,media",
        [
            ("image", {"image": {"id": "MEDIA1", "caption": "this cut"}}, "this cut", "MEDIA1"),
            ("interactive", {"interactive": {"button_reply": {"id": "yes", "title": "Confirm"}}}, "Confirm", ""),
            ("location", {"location": {"latitude": -36.85, "longitude": 174.76, "name": "Home"}}, "Location: Home -36.85,174.76", ""),
            ("sticker_pack", {}, "", ""),
        ],
    )
    def test_other_message_types(self, wa, kind, extra, text, media):
        post_webhook(wa, incoming(kind=kind, extra=extra))
        with schema_context("tenant_a"):
            message = Message.objects.get()
            assert message.text == text and message.media_id == media
            assert message.kind == (kind if kind != "sticker_pack" else "unsupported")

    def test_stop_opts_the_customer_out(self, wa):
        with schema_context("tenant_a"):
            customer = Customer.objects.create(name="Sita", phone="+64211234567")
            set_marketing_consent(customer, True, source="staff")
        post_webhook(wa, incoming(text="  stop "))
        with schema_context("tenant_a"):
            customer.refresh_from_db()
            assert customer.marketing_consent is False
            record = customer.consent_records.first()
            assert (record.source, record.channel, record.given) == (ConsentRecord.Source.STOP, "whatsapp", False)

    def test_broken_json_and_wrong_method(self, wa):
        body = b"{not json"
        signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert wa.post("/webhooks/whatsapp/", body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=signature).status_code == 400
        assert wa.put("/webhooks/whatsapp/").status_code == 405

    def test_simulate_command_uses_the_real_webhook(self, tenant_a, capsys):
        connect_whatsapp()
        call_command("whatsapp_simulate", "--schema", "tenant_a", "--from", "021 123 4567", "--text", "hello", "--name", "Sita")
        assert "delivered" in capsys.readouterr().out
        with schema_context("tenant_a"):
            assert Message.objects.get().text == "hello"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def conversation_with_message(client):
    post_webhook(client, incoming())
    with schema_context("tenant_a"):
        return Conversation.objects.get()


@pytest.mark.django_db
class TestSending:
    def test_reply_within_24_hours(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            message = services.send_text(conversation, "Yes, ready at 5pm")
        assert message.status == "sent" and message.provider_message_id == "wamid.out.1"
        call = graph.calls[0]
        assert call["url"] == f"https://graph.facebook.com/v25.0/{PHONE_ID}/messages"
        assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert call["json"] == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": WA_ID, "type": "text", "text": {"preview_url": False, "body": "Yes, ready at 5pm"}}
        assert call["timeout"] == 10 and call["allow_redirects"] is False

    def test_no_free_reply_after_24_hours(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            Conversation.objects.filter(pk=conversation.pk).update(last_inbound_at=timezone.now() - timedelta(hours=25))
            conversation.refresh_from_db()
            with pytest.raises(ValidationError, match="24 hours"):
                services.send_text(conversation, "hello")
            message = services.send_template(conversation, name="order_ready", language="en", params=["Sita", "#1001"])
        assert message.status == "sent" and graph.calls[0]["json"]["template"] == {
            "name": "order_ready", "language": {"code": "en"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "Sita"}, {"type": "text", "text": "#1001"}]}],
        }

    def test_marketing_templates_need_consent(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="marketing"):
                services.send_template(conversation, name="weekly_specials", category="marketing")
            set_marketing_consent(conversation.customer, True, source="staff")
            conversation.refresh_from_db()
            assert services.send_template(conversation, name="weekly_specials", category="marketing").status == "sent"

    @pytest.mark.parametrize("name,language", [("Order Ready", "en"), ("ok", "english"), ("../x", "en")])
    def test_template_names_are_checked(self, wa, graph, name, language):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"), pytest.raises(ValidationError):
            services.send_template(conversation, name=name, language=language)
        assert graph.calls == []

    def test_provider_errors_are_saved_without_the_token(self, wa, monkeypatch):
        conversation = conversation_with_message(wa)
        monkeypatch.setattr(whatsapp.requests, "post", FakeGraph(status=401, body={"error": {"code": 190, "message": f"Invalid token {TOKEN}"}}))
        with schema_context("tenant_a"):
            message = services.send_text(conversation, "hi")
        assert message.status == "failed" and "access token" in message.error and TOKEN not in message.error
        monkeypatch.setattr(whatsapp.requests, "post", FakeGraph(raise_exc=requests.ConnectionError(f"https://x?access_token={TOKEN}")))
        with schema_context("tenant_a"):
            message = services.send_text(conversation, "hi")
        assert TOKEN not in message.error
        with schema_context("tenant_a"):
            assert not AuditEvent.objects.filter(metadata__icontains=TOKEN).exists()

    def test_status_updates_move_forward_only(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            sent = services.send_text(conversation, "hi")
        for status in ("delivered", "read", "delivered", "sent"):
            post_webhook(wa, status_payload(sent.provider_message_id, status))
        with schema_context("tenant_a"):
            sent.refresh_from_db()
        assert sent.status == "read"
        post_webhook(wa, status_payload(sent.provider_message_id, "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]))
        with schema_context("tenant_a"):
            sent.refresh_from_db()
        assert sent.status == "failed" and sent.error == "131026 Message undeliverable"

    def test_not_connected(self, tenant_a):
        with schema_context("tenant_a"):
            customer = Customer.objects.create(name="X", phone="+64211234567")
            conversation = services.conversation_for_customer(customer)
            Conversation.objects.filter(pk=conversation.pk).update(last_inbound_at=timezone.now())
            conversation.refresh_from_db()
            with pytest.raises(ValidationError, match="not connected"):
                services.send_text(conversation, "hi")


# ---------------------------------------------------------------------------
# API, permissions, privacy
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInboxApi:
    def test_counter_staff_read_and_reply(self, wa, graph, client_for, tenant_a):
        conversation = conversation_with_message(wa)
        staff = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        listed = staff.get("/api/inbox/conversations/?unread=true").json()
        assert listed["count"] == 1 and listed["results"][0]["customer_name"] == "Sita" and listed["results"][0]["can_reply_freely"]
        detail = staff.get(f"/api/inbox/conversations/{conversation.pk}/").json()
        assert [m["text"] for m in detail["messages"]] == ["1 kg goat please"]
        assert staff.post(f"/api/inbox/conversations/{conversation.pk}/read/").json()["unread_count"] == 0
        body = staff.post(f"/api/inbox/conversations/{conversation.pk}/reply/", {"text": "Ready at 5"}, content_type="application/json").json()
        assert body["messages"][-1]["text"] == "Ready at 5" and body["messages"][-1]["sent_by_email"] == "counter@a.test"
        assert staff.post(f"/api/inbox/conversations/{conversation.pk}/close/", {"closed": True}, content_type="application/json").json()["status"] == "closed"
        # Shop staff cannot assign conversations (crm.assign).
        assert staff.post(f"/api/inbox/conversations/{conversation.pk}/assign/", {"user": None}, content_type="application/json").status_code == 403

    def test_new_message_reopens_a_closed_conversation(self, wa):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            services.set_closed(conversation, True)
        post_webhook(wa, incoming(msg_id="wamid.2", text="are you open?"))
        with schema_context("tenant_a"):
            conversation.refresh_from_db()
        assert conversation.status == "open" and conversation.unread_count == 1

    def test_assign_and_filter_mine(self, wa, client_for, tenant_a):
        conversation = conversation_with_message(wa)
        manager = user_client(client_for, tenant_a, "boss@a.test", "sales_manager")
        with schema_context("tenant_a"):
            from apps.accounts.models import User

            staff = User.objects.create_user("helper@a.test", "x-long-password-123", is_staff=True)
        assert manager.post(f"/api/inbox/conversations/{conversation.pk}/assign/", {"user": staff.pk}, content_type="application/json").json()["assigned_to_email"] == "helper@a.test"
        assert manager.get("/api/inbox/conversations/?mine=true").json()["count"] == 0

    def test_start_conversation_with_template(self, tenant_a, client_for, graph):
        connect_whatsapp()
        with schema_context("tenant_a"):
            customer = Customer.objects.create(name="Hari", phone="+6493791234")
        staff = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        response = staff.post("/api/inbox/start/", {"customer": customer.pk, "name": "order_ready", "params": ["Hari"]}, content_type="application/json")
        assert response.status_code == 201 and response.json()["messages"][0]["template_name"] == "order_ready"
        assert graph.calls[0]["json"]["to"] == "6493791234"

    def test_permissions_and_isolation(self, wa, client_for, tenant_a, tenant_b):
        conversation = conversation_with_message(wa)
        hr = user_client(client_for, tenant_a, "hr@a.test", "hr_staff")
        assert hr.get("/api/inbox/conversations/").status_code == 403
        agent = user_client(client_for, tenant_a, "agent@a.test", "support_agent")  # crm.view only
        assert agent.get(f"/api/inbox/conversations/{conversation.pk}/").status_code == 200
        assert agent.post(f"/api/inbox/conversations/{conversation.pk}/reply/", {"text": "x"}, content_type="application/json").status_code == 403
        other = user_client(client_for, tenant_b, "counter@b.test", "shop_staff")
        assert other.get("/api/inbox/conversations/").json()["count"] == 0
        assert other.get(f"/api/inbox/conversations/{conversation.pk}/").status_code == 404

    def test_removing_customer_data_deletes_their_messages(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            services.send_text(conversation, "Your order is ready")
            anonymise(conversation.customer)
            conversation.refresh_from_db()
            assert conversation.messages.count() == 0 and conversation.external_id == "" and conversation.status == "closed"
        # A new message from the same number starts a fresh conversation and customer.
        post_webhook(wa, incoming(msg_id="wamid.new"))
        with schema_context("tenant_a"):
            assert Conversation.objects.exclude(external_id="").get().customer.is_anonymised is False

    def test_message_text_never_reaches_the_audit_log(self, wa, graph):
        conversation = conversation_with_message(wa)
        with schema_context("tenant_a"):
            services.send_text(conversation, "Secret pickup code 4455")
            text = " ".join(json.dumps([e.changes, e.metadata, e.target_repr]) for e in AuditEvent.objects.all())
        assert "4455" not in text and "goat please" not in text


@pytest.mark.django_db
class TestInboxAdmin:
    def test_chat_page_reply_and_window_notice(self, wa, graph, client_for, tenant_a):
        conversation = conversation_with_message(wa)
        client = verified_staff_client(client_for, tenant_a, "counter@a.test", "shop_staff")
        page = client.get(f"/admin/inbox/conversation/{conversation.pk}/change/").content.decode()
        assert "1 kg goat please" in page and "Send reply" in page
        response = client.post(f"/admin/inbox/conversation/{conversation.pk}/change/", {"text": "On it", "reply": "1"}, follow=True)
        assert "Sent." in response.content.decode() and "On it" in response.content.decode()
        with schema_context("tenant_a"):
            Conversation.objects.filter(pk=conversation.pk).update(last_inbound_at=timezone.now() - timedelta(hours=30))
        page = client.get(f"/admin/inbox/conversation/{conversation.pk}/change/").content.decode()
        assert "only allows an approved template" in page and "Send reply" not in page

    def test_view_only_staff_cannot_send(self, wa, client_for, tenant_a):
        conversation = conversation_with_message(wa)
        client = verified_staff_client(client_for, tenant_a, "agent@a.test", "support_agent")
        page = client.get(f"/admin/inbox/conversation/{conversation.pk}/change/").content.decode()
        assert "1 kg goat please" in page and "Send reply" not in page
        assert client.post(f"/admin/inbox/conversation/{conversation.pk}/change/", {"text": "x", "reply": "1"}).status_code == 403

    def test_integrations_page_shows_webhook_details(self, client_for, tenant_a):
        connect_whatsapp()
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        page = client.get("/settings/integrations/").content.decode()
        assert "/webhooks/whatsapp/" in page and "verify-me" in page and TOKEN not in page and APP_SECRET not in page
