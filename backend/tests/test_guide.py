"""
In-app user guide (task 1.17): the Markdown reader (and that it never lets a
chapter add HTML or scripts), contents, chapters, search, images, the Help
link, and who can open the guide.
"""
import pytest

from apps.guide import markdown, services
from tests.conftest import PASSWORD, make_user
from tests.test_rbac import verified_staff_client


@pytest.fixture
def chapters(settings, tmp_path):
    folder = tmp_path / "guide"
    (folder / "images").mkdir(parents=True)
    (folder / "00-getting-started.md").write_text(
        "# Getting started\n\nWelcome. See [backups](12-backups.md#12-1-open).\n\n## First day\n\n1. Log in\n2. Set up **backups**\n", encoding="utf-8")
    (folder / "12-backups.md").write_text(
        "# 12. Backups\n\n## 12.1 Open\n\nClick **Backups**. ![page](images/backups-page.png)\n\n## 12.2 Passphrase\n\nThe passphrase locks every backup.\n", encoding="utf-8")
    (folder / "99-extra.md").write_text("# Extra notes\n\nSomething else.\n", encoding="utf-8")
    (folder / "README.txt").write_text("not a chapter", encoding="utf-8")
    (folder / "images" / "backups-page.png").write_bytes(b"\x89PNG fake")
    settings.GUIDE_DIR = folder
    return folder


class TestMarkdown:
    def test_blocks(self):
        r = markdown.render("# Title\n\nText with **bold**, *italics* and `code`.\n\n## Part one\n\n- a\n- b\n  - b1\n\n1. one\n2. two\n\n"
                            "| A | B |\n|---|---|\n| 1 | 2 |\n\n> **Note:** careful\n\n```\nraw <b>\n```\n")
        assert r.title == "Title" and [h.anchor for h in r.headings] == ["part-one"]
        for piece in ("<strong>bold</strong>", "<em>italics</em>", "<code>code</code>", '<h2 id="part-one">', "<ul>", "<li>b1</li>",
                      "<ol>", "<th>A</th>", "<td>2</td>", "<blockquote>", "<pre><code>raw &lt;b&gt;</code></pre>"):
            assert piece in r.html, piece

    def test_no_html_or_scripts_from_chapters(self):
        r = markdown.render('Hi <script>alert(1)</script> <img src=x onerror=alert(1)>\n\n[x](javascript:alert(1)) '
                            '[y](data:text/html,hi) ![z](javascript:alert(2)) [ok](https://example.com) [mail](mailto:a@b.test)')
        assert "<script" not in r.html and "<img src=x" not in r.html and "javascript:" not in r.html and "data:" not in r.html
        assert '&lt;script&gt;' in r.html
        assert 'href="https://example.com" target="_blank" rel="noopener noreferrer"' in r.html and 'href="mailto:a@b.test"' in r.html

    def test_attribute_breakout_is_escaped(self):
        r = markdown.render('[a](https://x.test/"onmouseover="alert(1))')
        assert 'onmouseover="alert' not in r.html

    def test_a_list_can_follow_a_sentence(self):
        r = markdown.render("Rules:\n- one\n- two\n\nSteps:\n1. first\n2. second\n\nThe year 2026. was good.\n")
        assert "<p>Rules:</p>\n<ul><li>one</li><li>two</li></ul>" in r.html.replace("\n<li>", "<li>").replace("\n</ul>", "</ul>").replace("<ul>\n", "<ul>")
        assert "<p>Steps:</p>" in r.html and "<ol>" in r.html and "<p>The year 2026. was good.</p>" in r.html

    def test_same_heading_twice_gets_two_anchors(self):
        r = markdown.render("## Steps\n\n## Steps\n")
        assert [h.anchor for h in r.headings] == ["steps", "steps-2"]

    def test_every_real_chapter_renders(self, settings):
        from pathlib import Path

        folder = Path(settings.BASE_DIR).parent / "docs" / "user-guide"
        files = sorted(folder.glob("*.md"))
        assert len(files) >= 15
        for f in files:
            r = markdown.render(f.read_text(encoding="utf-8"))
            assert r.title and "<h1>" in r.html and "**" not in r.html.replace("<code>**</code>", ""), f.name


@pytest.mark.django_db
class TestPages:
    def test_contents_and_order(self, chapters, client_for, tenant_a):
        groups = services.contents()
        assert groups[0][0] == "Getting started" and groups[0][1][0].slug == "00-getting-started"
        assert groups[-1][0] == "More" and groups[-1][1][0].slug == "99-extra"
        assert "README" not in str([c.slug for _, items in groups for c in items])
        page = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin").get("/guide/").content.decode()
        assert "Getting started" in page and "Extra notes" in page and "Search the guide" in page

    def test_chapter_links_images_and_pager(self, chapters, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        page = client.get("/guide/00-getting-started/").content.decode()
        assert 'href="/guide/12-backups/#12-1-open"' in page and "12. Backups →" in page
        page = client.get("/guide/12-backups/").content.decode()
        assert 'src="/guide/images/backups-page.png"' in page and "← Getting started" in page
        image = client.get("/guide/images/backups-page.png")
        assert image.status_code == 200 and image["Content-Type"] == "image/png"
        for bad in ("/guide/images/..%2Fsecret.png", "/guide/images/missing.png", "/guide/images/x.svg", "/guide/nope/", "/guide/README/"):
            assert client.get(bad).status_code == 404, bad

    def test_search(self, chapters, client_for, tenant_a):
        results = services.search("passphrase locks")
        assert [r["anchor"] for r in results] == ["12-2-passphrase"] and "<mark>passphrase</mark>" in results[0]["snippet"]
        assert services.search("") == [] and services.search("x") == [] and services.search("zebra") == []
        assert services.search("passphrase zebra") == []  # every word must be found
        page = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin").get("/guide/search/", {"q": "<b>backups</b>"}).content.decode()
        assert "&lt;b&gt;backups&lt;/b&gt;" in page and "<b>backups</b>" not in page

    def test_snippet_escapes_text(self):
        assert services.snippet("a <tag> & amp here", ["amp"]) == "a &lt;tag&gt; &amp; <mark>amp</mark> here"

    def test_staff_app_users_can_read_it_too(self, chapters, client_for, tenant_a):
        make_user("tenant_a", "counter@a.test")  # not staff: uses the staff app only
        client = client_for(tenant_a)
        assert client.post("/api/auth/login/", {"email": "counter@a.test", "password": PASSWORD}).status_code == 200
        page = client.get("/guide/").content.decode()
        assert "Back to the staff app" in page

    def test_login_needed(self, chapters, client_for, tenant_a, public_tenant):
        for tenant in (tenant_a, public_tenant):
            response = client_for(tenant).get("/guide/12-backups/")
            assert response.status_code == 302 and "login" in response["Location"]
            assert client_for(tenant).get("/guide/images/backups-page.png").status_code == 302

    def test_chapters_reload_when_changed(self, chapters):
        assert services.chapter("99-extra").title == "Extra notes"
        import os

        path = chapters / "99-extra.md"
        path.write_text("# Changed title\n", encoding="utf-8")
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10**9))
        assert services.chapter("99-extra").title == "Changed title"


@pytest.mark.django_db
class TestHelpLink:
    def test_help_for_pages(self, chapters):
        assert services.help_for("/backups/") == "/guide/12-backups/"
        assert services.help_for("/backups/tool/") == "/guide/12-backups/"
        assert services.help_for("/admin/orders/order/") == "/guide/"  # chapter 06 is not in this test folder
        assert services.help_for("/somewhere/") == "/guide/"

    def test_header_has_help_for_this_page(self, client_for, tenant_a):
        client = verified_staff_client(client_for, tenant_a, "it@a.test", "it_admin")
        assert 'href="/guide/12-backups/">Help</a>' in client.get("/backups/").content.decode()
        assert 'href="/guide/13-tickets/">Help</a>' in client.get("/tickets/").content.decode()
