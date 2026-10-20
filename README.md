# Anish1989 Business OS

**From Local Business to Intelligent Business.**

Anish1989 Business OS is a multi-tenant SaaS platform for small and medium businesses in Auckland, New Zealand. It combines ERP, CRM, e-commerce, business intelligence, AI agents, WhatsApp ordering and competitor analysis in one modular system. Each business turns on only the modules it needs.

| Item | Value |
|---|---|
| Owner | Anish Shrestha |
| Stage | Documentation complete; Step 1 (shared core) next |
| Last updated | 21 October 2026 |
| First pilot target | Gorkha Butchery, Auckland |

## Current stage

**Brainstorming and documentation is complete.** The next step is Step 1, the shared core. See [PROGRESS.md](PROGRESS.md) for the live task list and how to continue in a new session.

Pilot businesses (all agreed to pay after the pilot): Gorkha Butchery, a restaurant, a catering business, an events business, an education platform and a job platform.

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
| 09 | [Industry templates](docs/09-industry-templates.md) | Businesses the system serves, and the jobs module |
| 10 | [Delivery plan](docs/10-delivery-plan.md) | Pilot order, steps, estimates and pilot agreement |
| 11 | [Platform operations](docs/11-platform-operations.md) | Domains, website content with AI, tickets, health checks, backups |

### Reference specifications

The original specifications that shaped this project are kept in [`docs/reference`](docs/reference):

1. [Master prompt v1](docs/reference/01-master-prompt-v1.md): universal AI ERP/CRM platform
2. [Commercial extension](docs/reference/02-commercial-extension.md): subscriptions, e-commerce, referrals
3. [Master specification v2.0](docs/reference/03-master-spec-v2.0.md): the latest full requirements (FR-001 to FR-048, NFR-001 to NFR-052)
4. [Business brainstorm](docs/reference/04-business-brainstorm.md): the Anish1989 growth ecosystem idea
5. [Business blueprint v1.0](docs/reference/05-business-blueprint-v1.0.md): the MVP, pilot and 12-week plan
6. [Referral and rewards engine](docs/reference/06-referral-rewards-engine.md)
7. [Businesses that can use the system](docs/reference/07-businesses-that-can-use-the-system.md)

When documents disagree, **Master specification v2.0** and the **Decisions** document take priority.
