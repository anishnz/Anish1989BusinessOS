"""
The one-page website and its editor (task 2.9, D-164 to D-167): what the
public page shows (and never shows), drafts, publishing and history, the
text rules, the preview, permissions, "Generate with AI", and the AI layer
without tools.
"""
from decimal import Decimal

import pytest
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.ai import providers
from apps.ai.models import AIRun, AISettings
from apps.audit.models import AuditEvent
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.fulfilment.models import ClosedDay
from apps.website import content
from apps.website.models import WebsiteDraft, WebsiteVersion
from tests.conftest import make_user
from tests.test_ai import KEY, Script, connect_ai, text
from tests.test_catalog import make_product, user_client
from tests.test_fulfilment import shop  # noqa: F401 (fixture: pickup 9-12, delivery 16-18, area Central)
from tests.test_rbac import api_client, give_role, make_role

D = Decimal


@pytest.fixture
def site(tenant_a, shop, client_for):  # noqa: F811
    from apps.setup.models import BusinessProfile

    with schema_context("tenant_a"):
        BusinessProfile.objects.update_or_create(pk=1, defaults={
            "trading_name": "Gorkha Butchery", "phone": "+6421555010", "email": "shop@example.com",
            "address": "2 White Street", "suburb": "Auckland City", "city": "Auckland", "postcode": "1010"})
    make_product(name="Goat curry cut", sku="GOAT", unit="kg", price=D("23.00"), description="Fresh goat")
    make_product(name="Samosa pack", sku="SAM", unit="pack", price=D("15.00"))
    make_product(name="Old product", sku="OLD", unit="each", price=D("1.00"), is_archived=True)
    make_product(name="Not today", sku="NOT", unit="each", price=D("2.00"), is_available=False)
    with schema_context("tenant_a"):
        Customer.objects.create(name="Secret Customer", phone="+64211230000")
    return client_for(tenant_a)


def page(client, path="/"):
    response = client.get(path)
    return response, response.content.decode()


def publish(**texts):
    with schema_context("tenant_a"):
        content.save_draft({**content.draft_content(), **texts})
        return content.publish()


# ---------------------------------------------------------------------------
# The public page
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPublicPage:
    def test_works_before_anything_is_published(self, site):
        response, html = page(site)
        assert response.status_code == 200
        assert "<title>Gorkha Butchery – Auckland City, Auckland</title>" in html and "Welcome to Gorkha Butchery" in html
        assert "Goat curry cut" in html and "$23.00" in html and "per kg" in html and "Samosa pack" in html
        assert "Old product" not in html and "Not today" not in html  # archived or not available
        assert "Pickup hours" in html and "9 am – 12 pm" in html and "Delivery areas" in html and "Central" in html and "$8.00 delivery" in html
        assert "2 White Street, Auckland City, Auckland, 1010" in html and "https://wa.me/6421555010" in html
        assert "Secret Customer" not in html and "+64211230000" not in html  # never customers

    def test_shows_the_published_version_not_the_draft(self, site):
        publish(hero_heading="Fresh goat every day")
        with schema_context("tenant_a"):
            content.save_draft({**content.draft_content(), "hero_heading": "Draft only"})
        html = page(site)[1]
        assert "Fresh goat every day" in html and "Draft only" not in html

    def test_switches_hide_sections(self, site):
        publish(show_products=False, show_hours=False, show_delivery=False, show_whatsapp=False)
        html = page(site)[1]
        assert "Goat curry cut" not in html and "Pickup hours" not in html and "Delivery areas" not in html and "wa.me" not in html

    def test_sold_out_and_closed_days(self, site):
        with schema_context("tenant_a"):
            Product.objects.filter(sku="SAM").update(track_stock=True, stock_quantity=D("0"))
            ClosedDay.objects.create(date=timezone.localdate(), reason="Diwali")
        html = page(site)[1]
        assert "Sold out" in html and "Diwali" in html

    def test_texts_are_never_html(self, site):
        publish(about_text='<script>alert(1)</script>\n\nSecond "para"', seo_description="</script><b>x</b>")
        html = page(site)[1]
        assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<p>Second &quot;para&quot;</p>" in html
        ld = html.split('<script type="application/ld+json">')[1].split("</script>")[0]
        assert "\\u003c/script>" in ld and "<" not in ld  # the facts block cannot be closed early

    def test_safe_headers_and_no_cookies(self, site):
        response = site.get("/")
        assert "script-src 'none'" in response["Content-Security-Policy"] and response["Cache-Control"] == "public, max-age=300"
        assert not response.cookies and response["X-Frame-Options"] == "DENY"
        assert site.head("/").status_code == 200
        assert '<link rel="canonical" href="https://tenant-a.localhost/">' in response.content.decode()

    def test_robots_and_sitemap(self, site):
        assert "Sitemap: https://tenant-a.localhost/sitemap.xml" in site.get("/robots.txt").content.decode()
        assert "Disallow: /admin/" in site.get("/robots.txt").content.decode()
        assert "<loc>https://tenant-a.localhost/</loc>" in site.get("/sitemap.xml").content.decode()
        publish()
        assert f"<lastmod>{timezone.localdate():%Y-%m-%d}</lastmod>" in site.get("/sitemap.xml").content.decode()

    def test_no_website_without_the_module_or_on_the_platform(self, site, tenant_a, public_tenant, client_for):
        from apps.licensing.services import set_module_enabled

        set_module_enabled(tenant_a, "websites", False)
        try:
            assert site.get("/").status_code == 404 and site.get("/robots.txt").status_code == 404
        finally:
            set_module_enabled(tenant_a, "websites", True)
        assert client_for(public_tenant).get("/").status_code == 404


# ---------------------------------------------------------------------------
# Texts, drafts, publishing and history
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDraftsAndRules:
    def test_text_rules(self, site):
        from django.core.exceptions import ValidationError

        with schema_context("tenant_a"):
            clean = content.clean({"site_title": "  My   shop\t ", "about_text": "One\r\n\n\n\nTwo\x07", "unknown": "x", "show_hours": 0,
                                   "whatsapp_number": "021 555 0101"})
            assert (clean["site_title"], clean["about_text"], clean["show_hours"], clean["whatsapp_number"]) == ("My shop", "One\n\nTwo", False, "+64215550101")
            assert "unknown" not in clean
            for bad, key in (({"site_title": ""}, "site_title"), ({"seo_title": "x" * 61}, "seo_title"), ({"hero_text": 5}, "hero_text"),
                             ({"whatsapp_number": "12"}, "whatsapp_number")):
                with pytest.raises(ValidationError) as caught:
                    content.clean(bad)
                assert key in caught.value.message_dict
            with pytest.raises(ValidationError):
                content.clean(["not", "an", "object"])

    def test_publish_keeps_twenty_versions_and_restore(self, site):
        with schema_context("tenant_a"):
            assert content.unpublished_changes()
        for n in range(22):
            publish(hero_heading=f"Heading {n}")
        with schema_context("tenant_a"):
            assert list(WebsiteVersion.objects.values_list("number", flat=True))[:1] == [22] and WebsiteVersion.objects.count() == 20
            assert not content.unpublished_changes()
            content.restore(5)
            assert content.draft_content()["hero_heading"] == "Heading 4" and content.unpublished_changes()
            assert content.live_content()["hero_heading"] == "Heading 21"  # live until published
            with pytest.raises(Exception, match="no longer kept"):
                content.restore(1)
            # Publishing checks the texts again (rules may change after a draft was saved).
            WebsiteDraft.objects.filter(pk=1).update(content={**content.draft_content(), "tagline": "x" * 500})
            with pytest.raises(Exception, match="At most 120"):
                content.publish()
            assert AuditEvent.objects.filter(action="website.published").count() == 22
            assert AuditEvent.objects.filter(action="website.restored").count() == 1


# ---------------------------------------------------------------------------
# Editor API, preview and permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEditor:
    def test_edit_preview_and_publish(self, site, client_for, tenant_a):
        editor = user_client(client_for, tenant_a, "web@a.test", "content_manager")
        state = editor.get("/api/website/").json()
        assert state["can_edit"] and state["can_publish"] and state["live"] is None and len(state["fields"]) == 12
        draft = {**state["content"], "hero_heading": "Hello Auckland"}
        saved = editor.put("/api/website/draft/", {"content": draft}, content_type="application/json").json()
        assert saved["content"]["hero_heading"] == "Hello Auckland" and saved["unpublished_changes"] and saved["saved_by"] == "web@a.test"
        preview = editor.get("/website/preview/")
        assert preview.status_code == 200 and "Hello Auckland" in preview.content.decode() and "noindex" in preview.content.decode()
        assert preview["X-Frame-Options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in preview["Content-Security-Policy"]
        assert "Hello Auckland" not in site.get("/").content.decode()
        live = editor.post("/api/website/publish/").json()
        assert live["live"]["number"] == 1 and not live["unpublished_changes"] and "Hello Auckland" in site.get("/").content.decode()
        assert editor.get("/api/website/versions/").json()["results"][0]["published_by"] == "web@a.test"
        restored = editor.post("/api/website/versions/1/restore/").json()
        assert restored["content"]["hero_heading"] == "Hello Auckland"

    def test_bad_texts_come_back_per_field(self, site, client_for, tenant_a):
        editor = user_client(client_for, tenant_a, "web@a.test", "content_manager")
        response = editor.put("/api/website/draft/", {"content": {"site_title": "", "tagline": "x" * 200}}, content_type="application/json")
        assert response.status_code == 400 and set(response.json()["fields"]) == {"site_title", "tagline"}

    def test_permissions(self, site, client_for, tenant_a):
        make_role("tenant_a", "web_writer", ["websites.view", "websites.edit"])
        writer = make_user("tenant_a", "writer@a.test")
        give_role("tenant_a", writer, "web_writer")
        client = api_client(client_for, tenant_a, "writer@a.test")
        state = client.get("/api/website/").json()
        assert state["can_edit"] and not state["can_publish"]
        assert client.put("/api/website/draft/", {"content": state["content"]}, content_type="application/json").status_code == 200
        assert client.post("/api/website/publish/").status_code == 403
        make_role("tenant_a", "web_reader", ["websites.view"])
        give_role("tenant_a", make_user("tenant_a", "reader@a.test"), "web_reader")
        reader = api_client(client_for, tenant_a, "reader@a.test")
        assert reader.get("/api/website/").json()["can_edit"] is False
        assert reader.put("/api/website/draft/", {"content": state["content"]}, content_type="application/json").status_code == 403
        assert reader.post("/api/website/versions/1/restore/").status_code == 403
        counter = user_client(client_for, tenant_a, "counter@a.test", "shop_staff")  # no website permission
        assert counter.get("/api/website/").status_code == 403 and counter.get("/website/preview/").status_code == 403
        assert counter.post("/api/website/generate/", {"field": "hero_text"}).status_code == 403
        assert site.get("/website/preview/").status_code == 403  # not logged in


# ---------------------------------------------------------------------------
# Generate with AI
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGenerate:
    def editor(self, client_for, tenant_a):
        return user_client(client_for, tenant_a, "web@a.test", "content_manager")

    def test_no_key(self, site, client_for, tenant_a):
        response = self.editor(client_for, tenant_a).post("/api/website/generate/", {"field": "hero_text"})
        assert response.status_code == 400 and "No AI key is saved" in response.json()["detail"]

    def test_a_suggestion_from_public_facts_only(self, site, client_for, tenant_a, monkeypatch):
        connect_ai()
        ai = Script(monkeypatch, [text('"Fresh goat, cut the way you like it.\n Order on WhatsApp."', tokens=(900, 40))])
        response = self.editor(client_for, tenant_a).post("/api/website/generate/", {"field": "tagline", "hint": "mention halal"})
        assert response.status_code == 200 and response.json()["text"] == "Fresh goat, cut the way you like it. Order on WhatsApp."
        asked = ai.asked[0]
        prompt = asked["turns"][0]["text"]
        assert asked["key"] == KEY and asked["tools"] == [] and "Never invent" in asked["system"].replace("never invent", "Never invent")
        assert "Goat curry cut" in prompt and "Gorkha Butchery" in prompt and "mention halal" in prompt and "At most 120 characters" in prompt
        assert "Secret Customer" not in prompt and "+64211230000" not in prompt
        with schema_context("tenant_a"):
            run = AIRun.objects.get()
            assert (run.tools, run.result, run.input_tokens, run.note) == ("website", "answered", 900, "Website: Short line under the name")
            assert run.cost > 0
            assert "Fresh goat" not in content.live_content()["tagline"]  # only a suggestion: nothing is saved

    def test_too_long_answers_are_cut_at_a_word(self, site, client_for, tenant_a, monkeypatch):
        connect_ai()
        Script(monkeypatch, [text("word " * 40)])
        result = self.editor(client_for, tenant_a).post("/api/website/generate/", {"field": "hero_heading"}).json()["text"]
        assert len(result) <= 80 and result.endswith("word")

    def test_limits_and_errors(self, site, client_for, tenant_a, monkeypatch):
        connect_ai()
        editor = self.editor(client_for, tenant_a)
        assert editor.post("/api/website/generate/", {"field": "nope"}).json()["detail"] == "Unknown text."
        Script(monkeypatch, [providers.AIError("The key was refused"), text("")])
        failed = editor.post("/api/website/generate/", {"field": "hero_text"}).json()["detail"]
        assert failed == "The AI did not answer: The key was refused"
        assert "empty answer" in editor.post("/api/website/generate/", {"field": "hero_text"}).json()["detail"]
        with schema_context("tenant_a"):
            assert AIRun.objects.filter(result="failed").count() == 1
            AISettings.objects.update_or_create(pk=1, defaults={"monthly_limit": D("0")})
        assert "limit is reached" in editor.post("/api/website/generate/", {"field": "hero_text"}).json()["detail"]
        from apps.licensing.services import set_module_enabled

        set_module_enabled(tenant_a, "ai", False)
        try:
            assert "AI module is not switched on" in editor.post("/api/website/generate/", {"field": "hero_text"}).json()["detail"]
        finally:
            set_module_enabled(tenant_a, "ai", True)

    def test_at_most_thirty_an_hour(self, site, client_for, tenant_a, monkeypatch):
        from apps.website import ai as website_ai

        connect_ai()
        monkeypatch.setattr(website_ai, "PER_HOUR", 2)
        Script(monkeypatch, [text("One"), text("Two")])
        editor = self.editor(client_for, tenant_a)
        assert [editor.post("/api/website/generate/", {"field": "hero_heading"}).status_code for _ in range(3)] == [200, 200, 400]


@pytest.mark.django_db
class TestProvidersWithoutTools:
    @pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
    def test_no_tools_part_when_there_are_none(self, provider, monkeypatch):
        sent = {}

        def fake_post(url, body, headers, label):
            sent.update(body)
            return {"choices": [{"message": {"content": "Hi"}}], "content": [{"type": "text", "text": "Hi"}],
                    "candidates": [{"content": {"parts": [{"text": "Hi"}]}}], "usage": {}, "usageMetadata": {}}

        monkeypatch.setattr(providers, "_post", fake_post)
        providers.chat(provider, "k", providers.DEFAULT_MODELS[provider], "system", [{"role": "user", "text": "Hello"}], [])
        assert "tools" not in sent
        providers.chat(provider, "k", providers.DEFAULT_MODELS[provider], "system", [{"role": "user", "text": "Hello"}],
                       [{"name": "x", "description": "y", "parameters": {"type": "object", "properties": {}}}])
        assert "tools" in sent
