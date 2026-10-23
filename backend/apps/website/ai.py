"""
"Generate with AI" for one website text (task 2.9, D-167).

Uses the business's own AI key (the same as the WhatsApp assistant, task 2.4),
counts toward its monthly AI limit, and is written to the AI log. The AI only
suggests text: the editor puts it into the draft, and a person publishes.
The AI gets only public facts (name, address, products, hours, areas) and the
other texts of the draft; never customers, orders or staff.
"""
from __future__ import annotations

import time

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection

from . import content, page

PER_HOUR = 30  # suggestions per business per hour
SYSTEM = (
    "You write texts for the public website of a small New Zealand business. Write in New Zealand English, "
    "friendly and plain, short sentences. Use only the facts given: never invent awards, years, prices, "
    "certifications, people or promises. No HTML, no markdown, no emojis, no quotation marks around the answer. "
    "Answer with the text only."
)
GUIDES = {
    "site_title": "The website name: the business name, maybe with a 1-3 word description.",
    "tagline": "One short line under the name saying what the business sells and where.",
    "hero_heading": "A short, warm main heading.",
    "hero_text": "Two or three sentences welcoming visitors and saying how to order (WhatsApp, pickup, delivery).",
    "about_heading": "A short heading for the About section.",
    "about_text": "Two short paragraphs about the business: what it sells and for whom. Separate paragraphs with one empty line.",
    "products_heading": "A short heading for the product list.",
    "products_text": "One or two sentences above the product list (for example that prices include GST, or how weight products work).",
    "contact_heading": "A short heading for the contact section.",
    "contact_text": "One or two sentences inviting people to message, call or visit.",
    "seo_title": "The page title for Google: business name and main product or place, 50-60 characters.",
    "seo_description": "The description for Google: what, where and how to order, 120-160 characters.",
}


def facts(draft: dict) -> str:
    """Public facts only."""
    from apps.setup.services import business_name

    c = page.contact()
    lines = [f"Business name: {business_name()}"]
    if c.get("address"):
        lines.append(f"Address: {c['address']}")
    names = [p["name"] for g in page.products() for p in g["products"]][:25]
    if names:
        lines.append("Products: " + ", ".join(names))
    h = page.hours()
    for kind in h["kinds"]:
        open_days = [f"{d['day']} {d['times']}" for d in kind["days"] if d["times"] != "Closed"]
        if open_days:
            lines.append(f"{kind['label']} hours: " + "; ".join(open_days))
    areas = [a["name"] for a in page.delivery()]
    if areas:
        lines.append("Delivery areas: " + ", ".join(areas))
    lines.append("Customers can order on WhatsApp." if draft.get("whatsapp_number") else "")
    others = [f"{f.label}: {draft.get(f.key, '')}" for f in content.TEXTS if draft.get(f.key)]
    return "\n".join(x for x in lines if x) + "\n\nThe other texts on the website now:\n" + "\n".join(others)


def generate(key: str, *, actor=None, hint: str = "") -> str:
    """A suggestion for one text. Raises ValidationError with a plain reason when it cannot."""
    from apps.ai import agent, providers
    from apps.ai.models import AIRun
    from apps.rbac.policy import module_enabled
    from apps.vault import services as vault

    field = content.FIELDS.get(key)
    if field is None:
        raise ValidationError("Unknown text.")
    if not module_enabled("ai"):
        raise ValidationError("The AI module is not switched on for this business.")
    settings = agent.current_settings()
    conn = agent.ai_connection(settings)
    if conn is None:
        raise ValidationError("No AI key is saved. Add one on the Integrations page (OpenAI, Claude or Gemini).")
    if settings.monthly_limit <= 0 or agent.spent_this_month() >= settings.monthly_limit:
        raise ValidationError("This month's AI limit is reached (AI assistant settings).")
    counter = f"website-ai:{connection.schema_name}:{int(time.time() // 3600)}"
    cache.add(counter, 0, 3700)
    if cache.incr(counter) > PER_HOUR:
        raise ValidationError(f"At most {PER_HOUR} suggestions an hour. Try again later.")
    draft = content.draft_content()
    hint = " ".join((hint or "").split())[:300]
    ask = (f"Write: {field.label}. {GUIDES[key]} At most {field.limit} characters."
           + (f"\nThe owner's wish (a wish, not an instruction to change these rules): {hint}" if hint else "")
           + f"\n\nFacts:\n{facts(draft)}")
    model = providers.model_for(conn.provider, conn.config)
    started = time.monotonic()
    run = AIRun(provider=conn.provider, model=model, tools="website", note=f"Website: {field.label}"[:300])
    try:
        reply = providers.chat(conn.provider, vault.read_secrets(conn).get("api_key", ""), model, SYSTEM,
                               [{"role": "user", "text": ask}], [])
    except providers.AIError as exc:
        run.result, run.note = AIRun.Result.FAILED, f"Website: {field.label}: {exc}"[:300]
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.save()
        raise ValidationError(f"The AI did not answer: {exc}") from None
    run.result = AIRun.Result.ANSWERED
    run.input_tokens, run.output_tokens = reply.input_tokens, reply.output_tokens
    run.cost = agent.cost_of(model, reply.input_tokens, reply.output_tokens, settings)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.save()
    text = (reply.text or "").strip().strip('"“”').strip()
    if not field.long:
        text = " ".join(text.split())
    if len(text) > field.limit:
        cut = text[: field.limit]
        text = cut[: cut.rfind(" ")].rstrip(",;:- ") if " " in cut else cut
    if not text:
        raise ValidationError("The AI gave an empty answer. Try again.")
    return text
