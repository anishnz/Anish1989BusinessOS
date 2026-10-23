"""
Enquiries (task 3.1, D-172 to D-176): the public form and its spam checks,
the rules for the details, statuses and notes, the staff API and its
permissions, "Make enquiry" in the inbox, the AI's save_enquiry tool, the
staff email, and removing personal data.

tenant_b is a catering business (Catering and events is on); tenant_a is a
butchery (it is off).
"""
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
import requests
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.ai import agent, tools
from apps.ai.models import AIChat
from apps.audit.models import AuditEvent
from apps.customers import services as customer_services
from apps.customers.models import ConsentRecord, Customer
from apps.events import services, spam, tasks
from apps.events.models import Enquiry, EnquiryActivity, EnquirySettings
from apps.inbox.models import Conversation
from apps.vault import providers as vault_providers
from apps.vault import services as vault
from apps.vault.models import Connection
from tests.conftest import make_user
from tests.test_rbac import api_client, give_role, make_role

FUTURE = (timezone.localdate() + timedelta(days=60)).isoformat()
SECRET_DIET = "Grandma has a sesame allergy"
SECRET_MESSAGE = "Please call after 5, my phone is private"


@pytest.fixture(autouse=True)
def no_email_task(monkeypatch):
    """The staff email job is recorded instead of queued."""
    sent = []
    monkeypatch.setattr(tasks.staff_email_task, "delay", lambda schema, pk: sent.append((schema, pk)))
    monkeypatch.setattr(services.transaction, "on_commit", lambda fn, *a, **k: fn())
    return sent


def stamp(age=10, schema="tenant_b"):
    with schema_context(schema):
        return spam.stamp(now=time.time() - age)


def form(**changes):
    data = {"started": stamp(), "contact_name": "Sita Gurung", "contact_phone": "021 555 0101", "contact_email": "sita@example.com",
            "event_type": "wedding", "event_date": FUTURE, "start_time": "18:30", "guests": "120", "venue": "Mt Roskill hall",
            "menu": "Momo, goat curry", "dietary_needs": SECRET_DIET, "budget": "$4,500", "message": SECRET_MESSAGE}
    data.update(changes)
    return {k: v for k, v in data.items() if v is not None}


def enquiries():
    with schema_context("tenant_b"):
        return list(Enquiry.objects.select_related("customer").order_by("id"))


@pytest.fixture
def site_b(tenant_b, client_for):
    return client_for(tenant_b)


def post(client, data, **extra):
    return client.post("/enquiry/", data, REMOTE_ADDR=extra.pop("ip", "203.0.113.5"), **extra)


# ---------------------------------------------------------------------------
# The public form
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestForm:
    def test_shows_the_form_without_cookies_or_scripts(self, site_b):
        response = site_b.get("/enquiry/")
        html = response.content.decode()
        assert response.status_code == 200
        assert "Ask for a quote" in html and 'name="started"' in html and f'name="{spam.HONEYPOT}"' in html
        assert "script-src 'none'" in response["Content-Security-Policy"] and "form-action 'self'" in response["Content-Security-Policy"]
        assert "challenges.cloudflare.com" not in html
        assert not response.cookies
        assert "no-cache" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]

    def test_no_form_when_events_are_off_or_the_form_is_switched_off(self, tenant_a, client_for, site_b):
        assert client_for(tenant_a).get("/enquiry/").status_code == 404
        assert client_for(tenant_a).get("/enquiry/thanks/").status_code == 404
        with schema_context("tenant_b"):
            EnquirySettings.objects.update_or_create(pk=1, defaults={"form_enabled": False})
        assert site_b.get("/enquiry/").status_code == 404
        assert post(site_b, form()).status_code == 404
        assert enquiries() == []

    def test_a_good_enquiry_is_saved_with_a_new_customer(self, site_b, no_email_task):
        response = post(site_b, form())
        assert response.status_code == 302 and response["Location"] == "/enquiry/thanks/"
        [e] = enquiries()
        assert (e.source, e.status, e.contact_name, e.contact_phone, e.contact_email) == ("website", "new", "Sita Gurung", "+64215550101", "sita@example.com")
        assert (e.event_type, e.event_date.isoformat(), e.start_time.strftime("%H:%M"), e.guests, e.budget) == ("wedding", FUTURE, "18:30", 120, Decimal("4500.00"))
        assert e.dietary_needs == SECRET_DIET and e.customer.source == "website" and e.customer.name == "Sita Gurung"
        assert no_email_task == [("tenant_b", e.pk)]
        with schema_context("tenant_b"):
            assert list(EnquiryActivity.objects.filter(enquiry=e).values_list("kind", "text")) == [("created", "Website form")]
            event = AuditEvent.objects.get(action="events.enquiry_create")
            text = str(event.metadata) + str(event.changes) + event.target_repr
            assert "website" in text and "Sita" not in text and "sesame" not in text and "5550101" not in text
            assert not ConsentRecord.objects.exists()  # marketing not ticked
        thanks = site_b.get("/enquiry/thanks/")
        assert thanks.status_code == 200 and "We have your enquiry" in thanks.content.decode() and "public" in thanks["Cache-Control"]

    def test_an_existing_customer_is_used_not_copied(self, site_b):
        with schema_context("tenant_b"):
            known = Customer.objects.create(name="Sita G (regular)", phone="+64215550101")
        post(site_b, form(contact_email=""))
        [e] = enquiries()
        assert e.customer_id == known.pk and e.contact_name == "Sita Gurung"
        with schema_context("tenant_b"):
            assert Customer.objects.count() == 1 and Customer.objects.get().name == "Sita G (regular)"

    def test_an_email_is_added_to_a_customer_who_had_none(self, site_b):
        with schema_context("tenant_b"):
            known = Customer.objects.create(name="Sita", phone="+64215550101")
        post(site_b, form())
        with schema_context("tenant_b"):
            known.refresh_from_db()
            assert known.email == "sita@example.com"

    def test_marketing_consent_is_recorded_when_ticked(self, site_b):
        post(site_b, form(marketing="yes"))
        with schema_context("tenant_b"):
            c = Customer.objects.get()
            assert c.marketing_consent and ConsentRecord.objects.get(customer=c).source == "website"

    @pytest.mark.parametrize("changes, field, message", [
        ({"contact_name": ""}, "contact_name", "Please give your name."),
        ({"contact_phone": "", "contact_email": ""}, "contact_phone", "so we can reply"),
        ({"event_date": ""}, "event_date", "Please give the date"),
        ({"guests": ""}, "guests", "number of guests"),
        ({"guests": "0"}, "guests", "whole number from 1"),
        ({"guests": "2.5"}, "guests", "whole number from 1"),
        ({"guests": "lots"}, "guests", "Use a number of guests"),
        ({"event_date": "2020-01-01"}, "event_date", "already passed"),
        ({"event_date": "12/12/2026"}, "event_date", "Use a date like"),
        ({"contact_phone": "12"}, "contact_phone", "not a valid phone number"),
        ({"contact_email": "no-at-sign"}, "contact_email", "not a valid email"),
        ({"budget": "a lot"}, "budget", "Use an amount"),
        ({"budget": "-5"}, "budget", "from 0"),
        ({"event_type": "rave"}, "event_type", "Choose a type"),
        ({"start_time": "25:99"}, "start_time", "Use a time like"),
        ({"venue": "x" * 301}, "venue", "at most 300"),
    ])
    def test_mistakes_are_shown_and_nothing_is_saved(self, site_b, changes, field, message):
        response = post(site_b, form(**changes))
        html = response.content.decode()
        assert response.status_code == 400 and message in html and "Please check the fields" in html
        assert 'value="Sita Gurung"' in html or field == "contact_name"  # what was typed stays
        assert enquiries() == []

    def test_several_mistakes_are_shown_together(self, site_b):
        html = post(site_b, form(contact_name="", contact_phone="", contact_email="")).content.decode()
        assert "Please give your name." in html and "so we can reply" in html

    def test_a_website_enquiry_always_needs_a_way_to_reply(self, tenant_b):
        with schema_context("tenant_b"):
            with pytest.raises(Exception, match="phone number or an email address"):
                services.create({"contact_name": "No contact"}, source="website")
            assert not Enquiry.objects.exists()

    def test_end_time_must_differ_from_start_time(self, site_b):
        response = post(site_b, form(end_time="18:30"))
        assert response.status_code == 302  # the form has no end time field: ignored
        with schema_context("tenant_b"):
            with pytest.raises(Exception, match="same as the start time"):
                services.create({"event_date": FUTURE, "start_time": "18:30", "end_time": "18:30"}, source="staff")


@pytest.mark.django_db
class TestSpam:
    def test_hidden_field_looks_fine_but_saves_nothing(self, site_b, no_email_task):
        response = post(site_b, form(**{spam.HONEYPOT: "http://spam.example"}))
        assert response.status_code == 302 and response["Location"] == "/enquiry/thanks/"
        assert enquiries() == [] and no_email_task == []

    @pytest.mark.parametrize("started", [lambda: stamp(age=1), lambda: stamp(age=3 * 3600), lambda: "forged", lambda: "",
                                         lambda: stamp(schema="tenant_a")])
    def test_too_fast_too_old_forged_or_from_another_business(self, site_b, started):
        response = post(site_b, form(started=started()))
        assert response.status_code == 400 and "too quickly or is too old" in response.content.decode()
        assert enquiries() == []

    def test_the_stamp_limits_are_inclusive(self, tenant_b):
        with schema_context("tenant_b"):
            now = int(time.time())
            assert spam.stamp_ok(spam.stamp(now=now - spam.MIN_SECONDS), now=now)
            assert spam.stamp_ok(spam.stamp(now=now - spam.MAX_SECONDS), now=now)
            assert not spam.stamp_ok(spam.stamp(now=now - spam.MAX_SECONDS - 1), now=now)

    def test_five_an_hour_from_one_address(self, site_b):
        for n in range(spam.PER_ADDRESS_PER_HOUR):
            assert post(site_b, form(contact_email=f"p{n}@example.com", contact_phone="")).status_code == 302
        refused = post(site_b, form(contact_email="six@example.com", contact_phone=""))
        assert refused.status_code == 429 and "Too many enquiries" in refused.content.decode()
        assert post(site_b, form(contact_email="other@example.com", contact_phone=""), ip="198.51.100.7").status_code == 302
        assert len(enquiries()) == spam.PER_ADDRESS_PER_HOUR + 1

    def test_a_limit_per_business_per_day(self, site_b):
        with schema_context("tenant_b"):
            cache.set("events:form:day:tenant_b", spam.PER_BUSINESS_PER_DAY, 86400)
        assert post(site_b, form()).status_code == 429
        assert enquiries() == []

    def test_the_counter_recovers_when_its_key_expired(self, tenant_b, monkeypatch):
        calls = []

        def incr(key):
            calls.append(key)
            if len(calls) == 1:
                raise ValueError("gone")
            return 1

        monkeypatch.setattr(cache, "incr", incr)
        monkeypatch.setattr(cache, "add", lambda *a, **k: True)
        with schema_context("tenant_b"):
            assert spam.over_limit("203.0.113.9") is False


def connect_turnstile(status=Connection.Status.CONNECTED):
    with schema_context("tenant_b"):
        conn = vault.create_connection(provider_code="turnstile", label="Turnstile", config={"site_key": "0xSITEKEY"},
                                       secrets={"secret_key": "0xSECRET"})
        Connection.objects.filter(pk=conn.pk).update(status=status)
        return conn


class FakeResponse:
    def __init__(self, body, ok=True, status_code=200):
        self.body, self.ok, self.status_code = body, ok, status_code

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.mark.django_db
class TestTurnstile:
    def test_the_widget_shows_only_with_a_working_connection(self, site_b):
        connect_turnstile(status=Connection.Status.FAILED)
        assert "cf-turnstile" not in site_b.get("/enquiry/").content.decode()
        with schema_context("tenant_b"):
            Connection.objects.update(status=Connection.Status.CONNECTED)
        response = site_b.get("/enquiry/")
        html = response.content.decode()
        assert 'data-sitekey="0xSITEKEY"' in html and spam.TURNSTILE_SCRIPT in html and "0xSECRET" not in html
        assert "script-src https://challenges.cloudflare.com" in response["Content-Security-Policy"]
        assert "frame-src https://challenges.cloudflare.com" in response["Content-Security-Policy"]

    def test_cloudflare_is_asked_and_must_agree(self, site_b, monkeypatch):
        connect_turnstile()
        asked = []

        def fake_post(url, data, timeout, allow_redirects):
            asked.append((url, data))
            return FakeResponse({"success": True, "hostname": site_b.defaults["HTTP_HOST"].split(":")[0]})

        monkeypatch.setattr(requests, "post", fake_post)
        assert post(site_b, form(**{"cf-turnstile-response": "tok-123"})).status_code == 302
        assert asked == [(vault_providers.TURNSTILE_VERIFY_URL, {"secret": "0xSECRET", "response": "tok-123", "remoteip": "203.0.113.5"})]
        assert len(enquiries()) == 1

    @pytest.mark.parametrize("token, answer", [
        ("", {"success": True}),
        ("x" * 2049, {"success": True}),
        ("tok", {"success": False, "error-codes": ["timeout-or-duplicate"]}),
        ("tok", {"success": True, "hostname": "another-site.example"}),
        ("tok", requests.ConnectionError("down")),
        ("tok", FakeResponse({}, ok=False, status_code=500)),
        ("tok", FakeResponse(ValueError("not json"))),
    ])
    def test_refused(self, site_b, monkeypatch, token, answer):
        connect_turnstile()

        def fake_post(*args, **kwargs):
            if isinstance(answer, Exception):
                raise answer
            return answer if isinstance(answer, FakeResponse) else FakeResponse(answer)

        monkeypatch.setattr(requests, "post", fake_post)
        response = post(site_b, form(**{"cf-turnstile-response": token}))
        assert response.status_code == 400 and "spam check did not pass" in response.content.decode()
        assert enquiries() == []

    def test_no_hostname_in_the_answer_is_accepted(self, tenant_b, monkeypatch):
        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse({"success": True}))
        assert spam.check_turnstile(spam.Turnstile("s", "k"), "tok", address=None, host="x.example") == (True, "")

    def test_a_broken_vault_entry_means_no_widget(self, tenant_b, monkeypatch):
        connect_turnstile()
        monkeypatch.setattr(vault, "read_secrets", lambda conn: (_ for _ in ()).throw(RuntimeError("broken")))
        with schema_context("tenant_b"):
            assert spam.turnstile() is None

    @pytest.mark.parametrize("answer, ok, words", [
        (FakeResponse({"success": False, "error-codes": ["invalid-input-response"]}), True, "secret key works"),
        (FakeResponse({"success": False, "error-codes": ["invalid-input-secret"]}), False, "does not know this secret key"),
        (FakeResponse({}, ok=False, status_code=503), False, "error (503)"),
        (requests.Timeout("slow"), False, "did not answer"),
    ])
    def test_the_connection_test(self, monkeypatch, answer, ok, words):
        def fake_post(*args, **kwargs):
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(requests, "post", fake_post)
        result = vault_providers.test_turnstile({"secret_key": "0xSECRET"}, {"site_key": "0xSITE"})
        assert result.ok is ok and words in result.message


@pytest.mark.django_db
class TestWebsiteLink:
    def test_the_website_links_to_the_form(self, site_b, tenant_a, client_for):
        html = site_b.get("/").content.decode()
        assert 'href="/enquiry/"' in html and "Ask for a quote" in html
        assert "/enquiry/" in site_b.get("/sitemap.xml").content.decode()
        with schema_context("tenant_b"):
            EnquirySettings.objects.update_or_create(pk=1, defaults={"form_enabled": False})
        assert "/enquiry/" not in site_b.get("/").content.decode()
        assert "/enquiry/" not in site_b.get("/sitemap.xml").content.decode()
        assert "/enquiry/" not in client_for(tenant_a).get("/").content.decode()  # butchery: events off


# ---------------------------------------------------------------------------
# Rules, statuses and notes
# ---------------------------------------------------------------------------
@pytest.fixture
def one(tenant_b):
    with schema_context("tenant_b"):
        customer = Customer.objects.create(name="Ram Thapa", phone="+64215550202", email="ram@example.com")
        return services.create({"event_type": "birthday", "event_date": FUTURE, "guests": 40, "dietary_needs": SECRET_DIET,
                                "message": SECRET_MESSAGE}, source="staff", customer=customer)


@pytest.mark.django_db
class TestRules:
    def test_staff_enquiries_take_the_customers_details_and_send_no_email(self, one, no_email_task):
        assert (one.contact_name, one.contact_phone, one.contact_email) == ("Ram Thapa", "+64215550202", "ram@example.com")
        assert no_email_task == []

    def test_changes_are_listed_and_audited_by_field_name(self, one):
        with schema_context("tenant_b"):
            assert services.update(one, {"guests": "45", "venue": "Hall", "status": "won", "customer": 99}) == ["Venue", "Guests"]
            assert services.update(one, {"guests": 45}) == []
            one.refresh_from_db()
            assert one.status == "new" and one.guests == 45
            event = AuditEvent.objects.get(action="events.enquiry_update")
            assert event.metadata == {"fields": ["venue", "guests"]}
            assert EnquiryActivity.objects.filter(enquiry=one, kind="changed").get().text == "Venue, Guests"

    def test_a_past_date_can_stay_but_not_be_set(self, one):
        with schema_context("tenant_b"):
            Enquiry.objects.filter(pk=one.pk).update(event_date=date(2020, 5, 1))
            one.refresh_from_db()
            assert services.update(one, {"event_date": "2020-05-01", "guests": 50}) == ["Guests"]
            with pytest.raises(Exception, match="already passed"):
                services.update(one, {"event_date": "2020-05-02"})
            with pytest.raises(Exception, match="more than 3 years"):
                services.update(one, {"event_date": (timezone.localdate() + timedelta(days=3 * 365 + 1)).isoformat()})
            services.update(one, {"event_date": (timezone.localdate() + timedelta(days=3 * 365)).isoformat()})
            services.update(one, {"event_date": timezone.localdate().isoformat()})  # today is fine

    def test_limits(self, one):
        with schema_context("tenant_b"):
            services.update(one, {"guests": services.MAX_GUESTS, "budget": "1000000"})
            with pytest.raises(Exception, match="whole number"):
                services.update(one, {"guests": services.MAX_GUESTS + 1})
            with pytest.raises(Exception, match="from 0"):
                services.update(one, {"budget": "1000000.01"})
            with pytest.raises(Exception, match="Use an amount"):
                services.update(one, {"budget": "NaN"})
            services.update(one, {"budget": "NZ$ 0", "guests": 1})
            one.refresh_from_db()
            assert one.budget == Decimal("0.00") and one.guests == 1

    def test_statuses(self, one):
        with schema_context("tenant_b"):
            with pytest.raises(Exception, match="already New"):
                services.set_status(one, "new")
            with pytest.raises(Exception, match="Unknown status"):
                services.set_status(one, "maybe")
            with pytest.raises(Exception, match="short reason"):
                services.set_status(one, "lost", reason="  ")
            with pytest.raises(Exception, match="At most 200"):
                services.set_status(one, "lost", reason="x" * 201)
            services.set_status(one, "lost", reason="Booked another caterer")
            one.refresh_from_db()
            assert one.status == "lost" and one.lost_reason == "Booked another caterer"
            services.set_status(one, "contacted", reason="ignored")
            one.refresh_from_db()
            assert one.lost_reason == ""
            texts = list(EnquiryActivity.objects.filter(enquiry=one, kind="status").values_list("text", flat=True))
            assert texts == ["Lost: Booked another caterer", "Contacted"]
            assert AuditEvent.objects.filter(action="events.enquiry_status").order_by("id").last().changes == {"status": ["lost", "contacted"]}

    def test_notes(self, one):
        with schema_context("tenant_b"):
            with pytest.raises(Exception, match="Write a note"):
                services.add_note(one, " ")
            with pytest.raises(Exception, match="At most 2000"):
                services.add_note(one, "x" * 2001)
            before = Enquiry.objects.get(pk=one.pk).updated_at
            services.add_note(one, "Called, quote tomorrow")
            assert EnquiryActivity.objects.get(enquiry=one, kind="note").text == "Called, quote tomorrow"
            assert Enquiry.objects.get(pk=one.pk).updated_at > before

    def test_what_a_quote_still_needs(self, one):
        with schema_context("tenant_b"):
            assert services.missing(one) == ["start time", "venue", "food and drinks"]

    def test_no_enquiries_when_the_module_is_off(self, tenant_a):
        with schema_context("tenant_a"):
            with pytest.raises(Exception, match="switched off"):
                services.create({}, source="staff")
            with pytest.raises(Exception, match="Unknown source"):
                services.create({}, source="fax")

    def test_an_anonymised_customer_cannot_get_a_new_enquiry(self, one):
        with schema_context("tenant_b"):
            customer = one.customer
            customer_services.anonymise(customer)
            with pytest.raises(Exception, match="personal data was removed"):
                services.create({}, source="staff", customer=Customer.objects.get(pk=customer.pk))

    def test_removing_personal_data_removes_it_from_enquiries(self, one):
        with schema_context("tenant_b"):
            services.add_note(one, "Ram's daughter is vegan")
            services.set_status(one, "lost", reason="Ram went with his cousin")
            services.update(one, {"venue": "12 Private Road", "menu": "Daal bhat"})
            customer_services.anonymise(one.customer)
            one.refresh_from_db()
            assert (one.contact_name, one.contact_phone, one.contact_email, one.venue, one.menu, one.dietary_needs, one.message, one.lost_reason) == ("",) * 8
            assert one.guests == 40 and one.status == "lost"  # numbers stay for reports
            texts = " ".join(EnquiryActivity.objects.filter(enquiry=one).values_list("text", flat=True))
            assert "Ram" not in texts and "vegan" not in texts
            assert list(EnquiryActivity.objects.filter(enquiry=one, kind="status").values_list("text", flat=True)) == ["Lost"]


@pytest.mark.django_db
class TestStaffEmail:
    def test_goes_to_people_who_may_edit_enquiries_without_private_details(self, one, tenant_b):
        editor = make_user("tenant_b", "events@b.test", staff=True)
        give_role("tenant_b", editor, "operations_manager")
        make_user("tenant_b", "noevents@b.test", staff=True)
        make_user("tenant_b", "notstaff@b.test")
        mail.outbox.clear()
        with schema_context("tenant_b"):
            assert services.send_staff_email(one) is True
        [email] = mail.outbox
        assert email.to == ["events@b.test"] and f"New enquiry #{one.pk}" in email.subject
        assert "Ram Thapa" in email.body and "40 guests" in email.body and "Birthday" in email.body and f"/app/enquiries/{one.pk}" in email.body
        assert "sesame" not in email.body and "private" not in email.body

    def test_nobody_to_tell(self, one):
        with schema_context("tenant_b"):
            assert services.send_staff_email(one) is False

    def test_a_broken_mail_server_is_not_a_problem(self, one, monkeypatch):
        editor = make_user("tenant_b", "events@b.test", staff=True)
        give_role("tenant_b", editor, "operations_manager")
        import django.core.mail

        monkeypatch.setattr(django.core.mail, "send_mail", lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")))
        with schema_context("tenant_b"):
            assert services.send_staff_email(one) is False

    def test_switched_off(self, site_b, no_email_task):
        with schema_context("tenant_b"):
            EnquirySettings.objects.update_or_create(pk=1, defaults={"email_staff": False})
        post(site_b, form())
        assert len(enquiries()) == 1 and no_email_task == []

    def test_the_job_finds_the_enquiry(self, one, monkeypatch):
        sent = []
        monkeypatch.setattr(services, "send_staff_email", lambda e: sent.append(e.pk))
        tasks.staff_email_task.run("tenant_b", one.pk)
        tasks.staff_email_task.run("tenant_b", 999999)
        assert sent == [one.pk]


# ---------------------------------------------------------------------------
# The staff API
# ---------------------------------------------------------------------------
def staff(client_for, tenant_b, email, codes):
    user = make_user("tenant_b", email)
    role = make_role("tenant_b", email.split("@")[0], codes)
    with schema_context("tenant_b"):
        from apps.rbac.models import UserRole

        UserRole.objects.create(user=user, role=role)
    return api_client(client_for, tenant_b, email)


@pytest.fixture
def editor(client_for, tenant_b):
    return staff(client_for, tenant_b, "editor@b.test", ["events.view", "events.create", "events.edit", "crm.view"])


@pytest.fixture
def viewer(client_for, tenant_b):
    return staff(client_for, tenant_b, "viewer@b.test", ["events.view"])


@pytest.mark.django_db
class TestAPI:
    def test_list_counts_filters_and_search(self, editor, one, site_b):
        post(site_b, form())
        with schema_context("tenant_b"):
            services.set_status(one, "won")
        data = editor.get("/api/events/enquiries/?status=open").json()
        assert data["count"] == 1 and data["counts"] == {"new": 1, "contacted": 0, "quoted": 0, "won": 1, "lost": 0}
        assert [r["name"] for r in data["results"]] == ["Sita Gurung"]
        everything = editor.get("/api/events/enquiries/").json()
        assert everything["count"] == 2
        assert editor.get("/api/events/enquiries/?status=won").json()["results"][0]["id"] == one.pk
        assert editor.get("/api/events/enquiries/?status=maybe").status_code == 400
        assert editor.get(f"/api/events/enquiries/?status=&q=%23{one.pk}").json()["count"] == 1
        assert editor.get("/api/events/enquiries/?status=&q=sita").json()["count"] == 1
        assert editor.get("/api/events/enquiries/?status=&q=0215550202").json()["count"] == 1
        assert editor.get("/api/events/enquiries/?status=&q=021").json()["count"] == 0  # too few digits for a phone search
        row = everything["results"][0]
        assert "dietary_needs" not in row and "message" not in row  # only in the detail
        assert {"value": "lost", "label": "Lost"} in everything["statuses"]

    def test_detail_and_changes(self, editor, one):
        detail = editor.get(f"/api/events/enquiries/{one.pk}/").json()
        assert detail["dietary_needs"] == SECRET_DIET and detail["missing"] == ["start time", "venue", "food and drinks"]
        assert [a["kind"] for a in detail["activities"]] == ["created"]
        changed = editor.patch(f"/api/events/enquiries/{one.pk}/", {"start_time": "17:00", "venue": "Hall"}, content_type="application/json")
        assert changed.status_code == 200 and changed.json()["missing"] == ["food and drinks"]
        bad = editor.patch(f"/api/events/enquiries/{one.pk}/", {"guests": "-1", "contact_email": "x"}, content_type="application/json")
        assert bad.status_code == 400 and set(bad.json()["fields"]) == {"guests", "contact_email"}
        assert editor.get("/api/events/enquiries/999999/").status_code == 404

    def test_status_and_notes(self, editor, one):
        lost = editor.post(f"/api/events/enquiries/{one.pk}/status/", {"status": "lost"}, content_type="application/json")
        assert lost.status_code == 400 and "reason" in lost.json()["fields"]
        ok = editor.post(f"/api/events/enquiries/{one.pk}/status/", {"status": "lost", "reason": "Too far"}, content_type="application/json")
        assert ok.status_code == 200 and ok.json()["status"] == "lost" and ok.json()["lost_reason"] == "Too far"
        note = editor.post(f"/api/events/enquiries/{one.pk}/notes/", {"text": "Rang back"}, content_type="application/json")
        assert note.status_code == 201 and note.json()["activities"][-1]["text"] == "Rang back"
        assert note.json()["activities"][-1]["by_email"] == "editor@b.test"
        assert editor.post(f"/api/events/enquiries/{one.pk}/notes/", {"text": ""}, content_type="application/json").status_code == 400

    def test_staff_add_an_enquiry(self, editor, one):
        made = editor.post("/api/events/enquiries/", {"guests": 30, "customer": one.customer_id}, content_type="application/json")
        assert made.status_code == 201 and made.json()["source"] == "staff" and made.json()["name"] == "Ram Thapa"
        blank = editor.post("/api/events/enquiries/", {}, content_type="application/json")
        assert blank.status_code == 201 and blank.json()["customer"] is None
        assert editor.post("/api/events/enquiries/", {"customer": 999999}, content_type="application/json").status_code == 400
        with schema_context("tenant_b"):
            customer_services.anonymise(one.customer)
        assert editor.post("/api/events/enquiries/", {"customer": one.customer_id}, content_type="application/json").status_code == 400
        assert editor.post("/api/events/enquiries/", {"guests": "many"}, content_type="application/json").status_code == 400

    def test_viewers_cannot_change_anything(self, viewer, one):
        assert viewer.get(f"/api/events/enquiries/{one.pk}/").status_code == 200
        assert viewer.patch(f"/api/events/enquiries/{one.pk}/", {"guests": 2}, content_type="application/json").status_code == 403
        assert viewer.post(f"/api/events/enquiries/{one.pk}/status/", {"status": "won"}, content_type="application/json").status_code == 403
        assert viewer.post(f"/api/events/enquiries/{one.pk}/notes/", {"text": "x"}, content_type="application/json").status_code == 403
        assert viewer.post("/api/events/enquiries/", {}, content_type="application/json").status_code == 403

    def test_no_access_without_the_permission_or_the_module(self, client_for, tenant_b, tenant_a, one):
        other = staff(client_for, tenant_b, "orders@b.test", ["orders.view", "crm.view"])
        assert other.get("/api/events/enquiries/").status_code == 403
        assert other.get(f"/api/events/enquiries/{one.pk}/").status_code == 403
        boss_a = make_user("tenant_a", "boss@a.test", staff=True, superuser=True)
        assert boss_a
        client_a = api_client(client_for, tenant_a, "boss@a.test")
        assert client_a.get("/api/events/enquiries/").status_code == 403  # events are off for the butchery
        assert client_a.get(f"/api/events/enquiries/{one.pk}/").status_code == 403

    def test_make_enquiry_from_a_chat(self, editor, one, client_for, tenant_b, no_email_task):
        with schema_context("tenant_b"):
            chat = Conversation.objects.create(external_id="64215550202", customer=one.customer)
            empty = Conversation.objects.create(external_id="64215550999")
        made = editor.post("/api/events/enquiries/from-chat/", {"conversation": chat.pk}, content_type="application/json")
        assert made.status_code == 201
        body = made.json()
        assert (body["source"], body["conversation"], body["customer"], body["name"]) == ("whatsapp", chat.pk, one.customer_id, "Ram Thapa")
        assert no_email_task == []  # staff made it themselves
        assert editor.post("/api/events/enquiries/from-chat/", {"conversation": empty.pk}, content_type="application/json").status_code == 400
        assert editor.post("/api/events/enquiries/from-chat/", {"conversation": 999999}, content_type="application/json").status_code == 404
        no_inbox = staff(client_for, tenant_b, "noinbox@b.test", ["events.view", "events.create"])
        assert no_inbox.post("/api/events/enquiries/from-chat/", {"conversation": chat.pk}, content_type="application/json").status_code == 403


# ---------------------------------------------------------------------------
# The AI on WhatsApp
# ---------------------------------------------------------------------------
@pytest.fixture
def chat(tenant_b):
    with schema_context("tenant_b"):
        customer = Customer.objects.create(name="Gita", phone="+64215550303", source="whatsapp")
        conversation = Conversation.objects.create(external_id="64215550303", customer=customer)
        return AIChat.objects.create(conversation=conversation)


def ctx(chat):
    return tools.Context(chat=chat, customer=chat.conversation.customer)


@pytest.mark.django_db
class TestAI:
    def test_the_tool_is_offered_only_with_events_on(self, chat, tenant_a):
        with schema_context("tenant_b"):
            assert "save_enquiry" in [s["name"] for s in tools.specs()]
            assert "Events and catering" in agent.system_prompt(chat, agent.current_settings())
        with schema_context("tenant_a"):
            assert "save_enquiry" not in [s["name"] for s in tools.specs()]
            assert agent.enquiry_rules(chat) == ""
            assert tools.run(ctx(chat), "save_enquiry", {"guests": 5}) == {"error": "This business does not take event enquiries."}

    def test_the_ai_builds_one_enquiry_for_the_chat(self, chat, no_email_task):
        with schema_context("tenant_b"):
            first = tools.run(ctx(chat), "save_enquiry", {"event_type": "religious", "guests": 60, "contact_phone": "+6421999999",
                                                           "contact_name": "Somebody else"})
            assert first["created"] is True and "date" in first["still_missing"] and "Ask for what is missing" in first["note"]
            e = Enquiry.objects.get()
            assert (e.source, e.conversation_id, e.customer.name, e.contact_phone, e.contact_name) == ("whatsapp", chat.conversation_id, "Gita", "+64215550303", "Gita")
            assert no_email_task == [("tenant_b", e.pk)]
            rules = agent.enquiry_rules(chat)
            assert f"#{e.pk}" in rules and "still missing: date" in rules
            second = tools.run(ctx(chat), "save_enquiry", {"event_date": FUTURE, "start_time": "11:00", "venue": "Temple hall", "menu": "Puri, aloo"})
            assert second == {"enquiry_number": e.pk, "created": False, "still_missing": [],
                              "note": "Everything for a quote is there. Tell the customer that a staff member will send a quote."}
            assert Enquiry.objects.count() == 1 and len(no_email_task) == 1
            assert "still missing: nothing" in agent.enquiry_rules(chat)

    def test_mistakes_come_back_as_errors(self, chat):
        with schema_context("tenant_b"):
            assert "already passed" in tools.run(ctx(chat), "save_enquiry", {"event_date": "2020-01-01"})["error"]
            assert Enquiry.objects.count() == 0

    def test_a_new_enquiry_after_staff_took_it_or_after_two_weeks(self, chat):
        with schema_context("tenant_b"):
            tools.run(ctx(chat), "save_enquiry", {"guests": 10})
            first = Enquiry.objects.get()
            services.set_status(first, "contacted")
            tools.run(ctx(chat), "save_enquiry", {"guests": 20})
            assert Enquiry.objects.count() == 2
            second = Enquiry.objects.exclude(pk=first.pk).get()
            Enquiry.objects.filter(pk=second.pk).update(created_at=timezone.now() - timedelta(days=services.AI_ENQUIRY_DAYS, minutes=1))
            tools.run(ctx(chat), "save_enquiry", {"guests": 30})
            assert Enquiry.objects.count() == 3
            Enquiry.objects.update(created_at=timezone.now() - timedelta(days=services.AI_ENQUIRY_DAYS - 1))
            assert services.open_for_chat(chat.conversation).guests == 30

    def test_no_enquiry_for_a_chat_without_a_customer(self, chat):
        with schema_context("tenant_b"):
            chat.conversation.customer = None
            assert tools.run(tools.Context(chat=chat, customer=None), "save_enquiry", {"guests": 5}) == {"error": "This chat has no customer."}
