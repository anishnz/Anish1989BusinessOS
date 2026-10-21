"""
A small Markdown-to-HTML converter for the user guide (task 1.17).

It understands what the guide chapters use: headings, paragraphs, bullet and
numbered lists (nested by indentation), tables, quotes, code, bold, italics,
links and images. All text is HTML-escaped first, so a chapter can never add
its own HTML or scripts. Links may only be relative, http(s) or mailto.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
FENCE = re.compile(r"^\s*```")
HR = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")
SAFE_URL = re.compile(r"^(https?://|mailto:|#|/|\.{0,2}/?[\w.-])", re.I)


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


@dataclass
class Rendered:
    html: str
    title: str = ""
    headings: list[Heading] = field(default_factory=list)


def slugify(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\s.-]", "", text)
    return re.sub(r"[\s.]+", "-", text).strip("-") or "section"


def _safe_url(url: str) -> str:
    url = url.strip()
    if url.lower().startswith(("javascript:", "data:", "vbscript:")) or not SAFE_URL.match(url):
        return "#"
    return url


def inline(text: str, link_fixer=None) -> str:
    """Escape, then add code, images, links, bold and italics."""
    codes: list[str] = []

    def keep_code(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", keep_code, text)
    text = html.escape(text, quote=True)

    def image(m):
        src = _safe_url(html.unescape(m.group(2)))
        src = link_fixer(src, image=True) if link_fixer else src
        return f'<img src="{html.escape(src)}" alt="{m.group(1)}" loading="lazy">'

    def link(m):
        href = _safe_url(html.unescape(m.group(2)))
        href = link_fixer(href) if link_fixer else href
        external = href.startswith(("http://", "https://"))
        extra = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a href="{html.escape(href)}"{extra}>{m.group(1)}</a>'

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", image, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def render(source: str, *, link_fixer=None) -> Rendered:
    lines = source.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    headings: list[Heading] = []
    used: set[str] = set()
    title = ""
    i = 0

    def para(buf):
        if buf:
            out.append("<p>" + inline(" ".join(s.strip() for s in buf), link_fixer) + "</p>")

    buf: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            para(buf); buf = []
            i += 1
            continue
        if FENCE.match(line):
            para(buf); buf = []
            code = []
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                code.append(lines[i]); i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i += 1
            continue
        m = HEADING.match(line)
        if m:
            para(buf); buf = []
            level, text = len(m.group(1)), m.group(2)
            rendered = inline(text, link_fixer)
            plain = re.sub(r"<[^>]+>", "", html.unescape(rendered))
            if level == 1 and not title:
                title = plain
                out.append(f"<h1>{rendered}</h1>")
            else:
                anchor = base = slugify(plain)
                n = 2
                while anchor in used:
                    anchor, n = f"{base}-{n}", n + 1
                used.add(anchor)
                headings.append(Heading(level, plain, anchor))
                out.append(f'<h{level} id="{anchor}">{rendered} <a class="anchor" href="#{anchor}" aria-label="Link to this section">#</a></h{level}>')
            i += 1
            continue
        if HR.match(line) and not buf:
            out.append("<hr>")
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            para(buf); buf = []
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i])); i += 1
            parts = ['<div class="table"><table><thead><tr>']
            parts += [f"<th>{inline(c, link_fixer)}</th>" for c in head]
            parts.append("</tr></thead><tbody>")
            for row in rows:
                row = (row + [""] * len(head))[: len(head)]
                parts.append("<tr>" + "".join(f"<td>{inline(c, link_fixer)}</td>" for c in row) + "</tr>")
            parts.append("</tbody></table></div>")
            out.append("".join(parts))
            continue
        if line.lstrip().startswith(">"):
            para(buf); buf = []
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append("<blockquote>" + render("\n".join(quote), link_fixer=link_fixer).html + "</blockquote>")
            continue
        item = LIST_ITEM.match(line)
        # Like GitHub: a list may start right after a sentence (a bullet, or a numbered list starting at 1).
        if item and (not buf or (not item.group(1) and (item.group(2)[0] in "-*+" or item.group(2)[:-1] == "1"))):
            para(buf); buf = []
            i = _list(lines, i, out, link_fixer)
            continue
        buf.append(line)
        i += 1
    para(buf)
    return Rendered("\n".join(out), title, headings)


def _list(lines: list[str], i: int, out: list[str], link_fixer) -> int:
    """A list, with deeper-indented items and indented paragraphs nested inside."""
    first = LIST_ITEM.match(lines[i])
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>")
    item: list[str] = []
    nested: list[str] = []

    def close_item():
        if item or nested:
            out.append("<li>" + inline(" ".join(s.strip() for s in item), link_fixer) + "".join(nested) + "</li>")

    def same_list(match) -> bool:
        """An item at this level that belongs to this list (a numbered list does not continue a bullet list)."""
        return bool(match) and len(match.group(1)) == indent and match.group(2)[0].isdigit() == ordered

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            # A blank line ends the list unless the next line continues it (indented, or another item).
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt.strip() and (len(nxt) - len(nxt.lstrip()) > indent or same_list(LIST_ITEM.match(nxt))):
                i += 1
                continue
            break
        m = LIST_ITEM.match(line)
        line_indent = len(line) - len(line.lstrip())
        if m and len(m.group(1)) == indent and not same_list(m):
            break
        if m and len(m.group(1)) == indent:
            close_item()
            item, nested = [m.group(3)], []
            i += 1
        elif m and len(m.group(1)) > indent:
            sub: list[str] = []
            i = _list(lines, i, sub, link_fixer)
            nested.append("".join(sub))
        elif line_indent > indent:
            if nested or (i > 0 and not lines[i - 1].strip()):
                # An indented block after a blank line: its own paragraph, table or quote inside the item.
                block = []
                while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent) and not (
                        LIST_ITEM.match(lines[i]) and len(LIST_ITEM.match(lines[i]).group(1)) <= indent):
                    block.append(lines[i][indent + 2:] if len(lines[i]) > indent + 2 else lines[i].strip())
                    i += 1
                    if i < len(lines) and not lines[i].strip() and (i + 1 >= len(lines) or len(lines[i + 1]) - len(lines[i + 1].lstrip()) <= indent):
                        break
                nested.append(render("\n".join(block), link_fixer=link_fixer).html)
            else:
                item.append(line)
                i += 1
        else:
            break
    close_item()
    out.append(f"</{tag}>")
    return i


def plain_text(source: str) -> str:
    """Text without Markdown marks (for search)."""
    text = re.sub(r"```.*?```", " ", source, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s*([-*+]|\d+[.)])\s+", "", text)  # list markers
    text = re.sub(r"[#>*`|]", " ", text)
    text = re.sub(r"-{3,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()
