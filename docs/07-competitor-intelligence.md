# 07. Competitor intelligence

Last updated: 21 October 2026

## Goal

Owners can ask the system, or the AI, to check similar businesses in an area of their choice. The system finds competitors, crawls their public websites in the background, compares them with the owner's business, and sends a weekly report. Every search, crawl, result and report is logged and kept as history.

## Workflow

1. **Start.** The owner opens the Competitor page, or asks the AI "check my competitors".
2. **Choose location.** The system asks where to search: suburb, city, or a radius (for example "5 km around Papatoetoe").
3. **Choose business type.** The default is the owner's own industry (for example "butchery"). The owner can change it.
4. **Find competitors.** The system searches a places or search API and shows a list. The owner can add, remove or pin competitors.
5. **Crawl.** Background jobs (Celery) crawl each competitor's public website.
6. **Extract.** The AI pulls out structured facts such as products, prices, offers, opening hours and contact details.
7. **Compare.** The system compares the facts with the owner's own products and prices.
8. **Report.** A report is created, with every fact linked to its source page and date.
9. **Repeat weekly.** A scheduled job runs again each week and highlights what changed.
10. **History.** All runs, raw pages (or hashes), extracted data, AI outputs, errors and reports are saved.

## Weekly report contents

- New or closed competitors in the area
- Price changes on similar products
- New offers or promotions
- Opening hours changes
- Rating and review count changes (if a review source is enabled)
- New products or services
- AI summary: "What changed and what you could consider". The AI suggests and the owner decides.

## Logs and history

| Record | Contents |
|---|---|
| Search run | Who started it, location, radius, business type, time, number of results |
| Competitor | Name, address, website, source, first seen, last seen, pinned or ignored |
| Crawl job | URL, start and end time, status, HTTP status, pages crawled, robots.txt result, error |
| Snapshot | Extracted facts with source URL and capture time; page hash to detect changes |
| AI analysis | Model, prompt version, input references, output, tokens, cost |
| Report | Period, content, delivery channel, delivered time, read status |

## Crawling rules

- Crawl only public pages. Never log in, bypass paywalls or break website rules.
- Respect each site's robots.txt and terms of use.
- Crawl slowly, with rate limits and a clear user agent, so sites are not overloaded.
- Do not collect personal information about individuals.
- Show the source link and date for every fact.
- Respect provider API terms (for example map or search APIs). Some providers do not allow storing their data long term.
- Crawled pages are untrusted input. The AI must ignore any instructions found in them.

## Limits

Crawl limits can depend on the subscription plan (for example the number of competitors and crawls per week). See the open questions.
