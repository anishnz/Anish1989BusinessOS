# Anish1989 Business OS

**From Local Business to Intelligent Business.**

Anish1989 Business OS is a multi-tenant SaaS platform for small and medium businesses in Auckland, New Zealand. It combines ERP, CRM, e-commerce, business intelligence, AI agents, WhatsApp ordering and competitor analysis in one modular system. Each business turns on only the modules it needs.

| Item | Value |
|---|---|
| Owner | Anish Shrestha |
| Stage | Brainstorming and documentation (no code yet) |
| Last updated | 21 October 2026 |
| First pilot target | Gorkha Butchery, Auckland |

## Current stage

We are in **brainstorming and documentation only**. No application code will be written until the documents below are reviewed and the open questions are answered.

## Tech stack (decided)

| Layer | Choice |
|---|---|
| Backend | Python, Django + Django REST Framework |
| Frontend | React / Next.js (separate app that talks to the Django API) |
| Database | PostgreSQL, one schema per tenant (django-tenants) |
| Background jobs | Celery + Redis (crawls, reports, AI jobs, messaging) |
| Live updates | Django Channels |
| Deployment | Docker, private object storage |

## Documents

| # | Document | What it covers |
|---|---|---|
| 01 | [Mind map](docs/01-mind-map.md) | The whole platform on one page |
| 02 | [Decisions](docs/02-decisions.md) | Decisions made so far, and why |
| 03 | [Feature catalogue](docs/03-feature-catalogue.md) | Every module and feature, with phase |
| 04 | [Tenant settings and secret vault](docs/04-tenant-settings-and-secrets.md) | How each tenant manages its own API keys |
| 05 | [WhatsApp AI ordering](docs/05-whatsapp-ai-ordering.md) | Customers order by chatting on WhatsApp |
| 06 | [Business intelligence](docs/06-business-intelligence.md) | Charts, customer response and analytics |
| 07 | [Competitor intelligence](docs/07-competitor-intelligence.md) | Crawl competitors and weekly reports |
| 08 | [Open questions](docs/08-open-questions.md) | Questions still to answer |

### Reference specifications

The original specifications that shaped this project are kept in [`docs/reference`](docs/reference):

1. [Master prompt v1](docs/reference/01-master-prompt-v1.md): universal AI ERP/CRM platform
2. [Commercial extension](docs/reference/02-commercial-extension.md): subscriptions, e-commerce, referrals
3. [Master specification v2.0](docs/reference/03-master-spec-v2.0.md): the latest full requirements (FR-001 to FR-048, NFR-001 to NFR-052)
4. [Business brainstorm](docs/reference/04-business-brainstorm.md): the Anish1989 growth ecosystem idea
5. [Business blueprint v1.0](docs/reference/05-business-blueprint-v1.0.md): the MVP, pilot and 12-week plan
6. [Referral and rewards engine](docs/reference/06-referral-rewards-engine.md)

When documents disagree, **Master specification v2.0** and the **Decisions** document take priority.
