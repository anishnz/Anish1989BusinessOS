"""
The user guide inside the app (task 1.17).

The chapters are the Markdown files in docs/user-guide/ (one source for the
GitHub copy and the in-app guide). GUIDE_DIR points to them: the repository
folder on a laptop, /opt/guide in the Docker image. Images live in
GUIDE_DIR/images/ and are made by tools/guide_screenshots.py.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from . import markdown

# Chapters in reading order, by group. Files not listed here appear under "More".
GROUPS = [
    ("Getting started", ["00-getting-started", "01-logging-in-and-two-step-verification", "14-first-login-setup", "09-staff-app", "13-tickets"]),
    ("Daily work", ["05-products-and-customers", "06-orders", "19-order-board", "15-pickup-and-delivery", "07-whatsapp-and-inbox", "17-whatsapp-order-messages", "18-ai-assistant", "20-daily-summary-and-feedback", "22-website", "23-enquiries", "08-dashboard"]),
    ("Admin and settings", ["02-roles-permissions-and-audit-log", "04-integrations-and-api-keys", "21-your-own-domain", "11-check-system", "12-backups"]),
    ("Platform (Super Admin)", ["03-businesses-licences-and-modules", "10-web-addresses", "16-test-data-and-log-in-as"]),
]

# Which chapter explains which page (the "Help" link in the header). Longest match wins.
PAGE_HELP = {
    "/backups/": "12-backups", "/system-check/": "11-check-system", "/tickets/": "13-tickets", "/setup/": "14-first-login-setup",
    "/settings/integrations/": "04-integrations-and-api-keys", "/dashboard/": "08-dashboard", "/admin/orders/": "06-orders", "/admin/orders/customermessagesettings/": "17-whatsapp-order-messages", "/admin/ai/": "18-ai-assistant",
    "/admin/reports/": "20-daily-summary-and-feedback", "/settings/web-addresses/": "21-your-own-domain", "/admin/orders/orderfeedback/": "20-daily-summary-and-feedback",
    "/admin/fulfilment/": "15-pickup-and-delivery", "/admin/catalog/": "05-products-and-customers", "/admin/customers/": "05-products-and-customers", "/admin/inbox/": "07-whatsapp-and-inbox",
    "/admin/rbac/": "02-roles-permissions-and-audit-log", "/admin/audit/": "02-roles-permissions-and-audit-log",
    "/admin/accounts/": "02-roles-permissions-and-audit-log", "/account/mfa/": "01-logging-in-and-two-step-verification",
    "/admin/tenants/": "03-businesses-licences-and-modules", "/admin/licensing/": "03-businesses-licences-and-modules",
    "/platform/businesses/": "10-web-addresses", "/platform/test-data/": "16-test-data-and-log-in-as", "/platform/people/": "02-roles-permissions-and-audit-log",
}
SLUG = re.compile(r"^[0-9]{2}-[a-z0-9-]+$")
IMAGE = re.compile(r"^[a-z0-9-]+\.(png|jpg|webp)$")


@dataclass
class Section:
    heading: str
    anchor: str
    text: str


@dataclass
class Chapter:
    slug: str
    title: str
    html: str
    headings: list
    sections: list
    group: str

    @property
    def title_html(self) -> str:
        """The chapter's <h1> (shown above "On this page")."""
        end = self.html.find("</h1>")
        return self.html[: end + 5] if self.html.startswith("<h1>") and end >= 0 else ""

    @property
    def body_html(self) -> str:
        return self.html[len(self.title_html):]


def guide_dir() -> Path:
    return Path(settings.GUIDE_DIR)


def _fix_link(url: str, image: bool = False) -> str:
    """Links between chapters (12-backups.md) and to images (images/x.png) inside the app."""
    if image and url.startswith("images/"):
        return "/guide/" + url
    m = re.match(r"^(?:\./)?([0-9]{2}-[a-z0-9-]+)\.md(#[\w-]+)?$", url)
    if m:
        return f"/guide/{m.group(1)}/" + (m.group(2) or "")
    return url


def _sections(source: str) -> list[Section]:
    """Split a chapter at its ## and ### headings, for search."""
    parts, heading, anchor, buf = [], "", "", []
    used: set[str] = set()
    for line in source.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            parts.append(Section(heading, anchor, markdown.plain_text("\n".join(buf))))
            heading = re.sub(r"[`*]", "", m.group(2)).strip()
            anchor = base = markdown.slugify(heading)
            n = 2
            while anchor in used:
                anchor, n = f"{base}-{n}", n + 1
            used.add(anchor)
            buf = []
        else:
            buf.append(line)
    parts.append(Section(heading, anchor, markdown.plain_text("\n".join(buf))))
    return [p for p in parts if p.text]


def _signature() -> tuple:
    folder = guide_dir()
    if not folder.is_dir():
        return ()
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in folder.glob("*.md")))


@lru_cache(maxsize=4)
def _load(signature: tuple) -> dict[str, Chapter]:
    group_of = {slug: group for group, slugs in GROUPS for slug in slugs}
    chapters = {}
    for name, _ in signature:
        slug = name[:-3]
        if not SLUG.match(slug):
            continue
        source = (guide_dir() / name).read_text(encoding="utf-8")
        rendered = markdown.render(source, link_fixer=_fix_link)
        chapters[slug] = Chapter(slug, rendered.title or slug, rendered.html, rendered.headings, _sections(source), group_of.get(slug, "More"))
    return chapters


def chapters() -> dict[str, Chapter]:
    return _load(_signature())


def contents() -> list[tuple[str, list[Chapter]]]:
    all_chapters = chapters()
    groups = [(name, [all_chapters[s] for s in slugs if s in all_chapters]) for name, slugs in GROUPS]
    listed = {s for _, slugs in GROUPS for s in slugs}
    more = [c for s, c in sorted(all_chapters.items()) if s not in listed]
    if more:
        groups.append(("More", more))
    return [(name, items) for name, items in groups if items]


def reading_order() -> list[Chapter]:
    return [c for _, items in contents() for c in items]


def chapter(slug: str) -> Chapter | None:
    return chapters().get(slug) if SLUG.match(slug or "") else None


def neighbours(slug: str) -> tuple[Chapter | None, Chapter | None]:
    order = reading_order()
    index = next((i for i, c in enumerate(order) if c.slug == slug), None)
    if index is None:
        return None, None
    return (order[index - 1] if index > 0 else None, order[index + 1] if index + 1 < len(order) else None)


def help_for(path: str) -> str:
    """The guide address that explains the page at `path`."""
    best = max((p for p in PAGE_HELP if path.startswith(p)), key=len, default=None)
    slug = PAGE_HELP.get(best) if best else None
    return f"/guide/{slug}/" if slug and slug in chapters() else "/guide/"


def image_path(name: str) -> Path | None:
    if not IMAGE.match(name or ""):
        return None
    path = guide_dir() / "images" / name
    return path if path.is_file() else None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[\w'-]+", (query or "").lower()) if len(t) >= 2][:8]


def search(query: str, limit: int = 20) -> list[dict]:
    """Sections that contain every word of the query, best first. Snippets are HTML-escaped with <mark>."""
    terms = _terms(query)
    if not terms:
        return []
    found = []
    for c in reading_order():
        for s in c.sections:
            hay = f"{c.title} {s.heading} {s.text}".lower()
            if not all(t in hay for t in terms):
                continue
            score = sum(hay.count(t) for t in terms) + sum(5 for t in terms if t in s.heading.lower() or t in c.title.lower())
            found.append({"chapter": c, "heading": s.heading or c.title, "anchor": s.anchor, "score": score,
                          "snippet": snippet(s.text, terms)})
    found.sort(key=lambda r: -r["score"])
    return found[:limit]


def snippet(text: str, terms: list[str], width: int = 220) -> str:
    low = text.lower()
    first = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, first - width // 3)
    piece = text[start:start + width]
    pattern = re.compile("|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True)), re.I)
    parts, last = [], 0
    for m in pattern.finditer(piece):  # escape the text between matches, so <mark> never splits an HTML entity
        parts.append(html.escape(piece[last:m.start()]))
        parts.append(f"<mark>{html.escape(m.group(0))}</mark>")
        last = m.end()
    parts.append(html.escape(piece[last:]))
    return ("… " if start else "") + "".join(parts) + (" …" if start + width < len(text) else "")
