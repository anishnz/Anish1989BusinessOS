# 02. Decisions

Last updated: 21 October 2026

This document records each decision, the reason for it, and its status. A decision can change later, but the change must be written here.

| ID | Area | Decision | Reason | Status |
|---|---|---|---|---|
| D-001 | Backend | Python, Django + Django REST Framework | Mature, secure defaults, built-in admin, large ecosystem, easy to maintain | Decided |
| D-002 | Frontend | React / Next.js as a separate app that calls the Django API | Rich dashboards and BI charts, flexible later, mobile-friendly | Decided |
| D-003 | Database | PostgreSQL | Safe money maths (decimal), JSON fields, full-text and vector search, scales well | Decided |
| D-004 | Tenancy | One PostgreSQL schema per tenant (django-tenants) | Strong separation between businesses; easy per-tenant backup and export | Decided |
| D-005 | Background jobs | Celery + Redis | Crawling, weekly reports, AI jobs and messaging must not block the website | Proposed |
| D-006 | Live updates | Django Channels | Live order board, unified inbox and status updates | Proposed |
| D-007 | Secrets | Each tenant adds its own keys (AI, messaging, payments) in a Settings page; keys are encrypted and never shown in full | Tenants control their own costs and accounts; the platform is not responsible for their usage | Decided |
| D-008 | Providers | Each provider type sits behind an adapter interface | Swap or add providers later without rewriting modules | Decided |
| D-009 | Messaging channels | WhatsApp Business, Viber, Telegram, email and SMS | Requested channels for customers in Auckland | Decided |
| D-010 | Payments | Manual bank transfer first; Stripe, Windcave and PayPal in a later phase | Matches Master spec v2.0; gateways need accounts and testing | Decided |
| D-011 | AI providers | OpenAI, Anthropic Claude, Google Gemini and local/open models (for example Ollama) | Tenants choose their own provider and cost | Decided |
| D-012 | BI customer response sources | Surveys (NPS, CSAT), reviews and ratings, chat and message replies, campaign and coupon results | Gives a full picture of how customers respond | Decided |
| D-013 | WhatsApp ordering | Customers order through WhatsApp; the website is the central management system | Customers do not need to open a website or fill in a form | Decided |
| D-014 | Competitor intelligence | Owner chooses a location; the system finds similar businesses, crawls public websites, and sends a weekly report; all runs are logged | Helps owners understand their local market | Decided |
| D-015 | Extra features | All 22 suggested features are added to the scope (see Feature catalogue) | Requested on 21 October 2026 | Decided |
| D-016 | Documentation | One shareable document plus Markdown files in this repository | Easy to share and easy to keep with the code | Decided |
| D-017 | Default currency | NZD | From Master spec v2.0 | Decided |
| D-018 | Trial | 30 days, no unannounced charge at the end | From Master spec v2.0 | Decided |
| D-019 | Architecture style | Modular monolith first (one Django project, separate apps per module) | Easier to build and maintain than microservices | Proposed |
| D-020 | Pilot order | 1 shared core, 2 butchery + restaurant, 3 catering + events, 4 education + jobs | Businesses that share a flow are built together; each step reuses the last | Decided (21 Oct 2026) |
| D-021 | Job tools | Job board, ATS resume builder and job listings are a module in the same platform | Reuses users, roles, CRM, AI, BI and website builder | Decided (21 Oct 2026) |
| D-022 | Pilot commercial model | Pilot first, then the business pays a monthly fee | All pilot businesses agreed to pay after the pilot | Decided (21 Oct 2026) |
| D-023 | Working time | Full-time | Stated on 21 Oct 2026 | Decided |
| D-024 | Job listing sources | Only employer-posted jobs, official feeds under their terms, and career pages that allow crawling | Big job sites restrict scraping and reuse of their listings | Decided (21 Oct 2026) |
| D-025 | Pilot agreement | Sign a one-page agreement with each business before its pilot starts | Turns a verbal yes into clear expectations | Decided (21 Oct 2026) |
| D-026 | Domains | Free tenant subdomains first; custom domains with DNS check and automatic SSL next; buying domains later | Subdomains are needed from day one; buying domains needs a registrar account | Decided (21 Oct 2026) |
| D-027 | Website content | Title, headings, text and SEO editable from the backend; AI drafts, a person publishes | Owners can update their site without code; AI never publishes alone | Decided (21 Oct 2026) |
| D-028 | Ticket system | Built-in issue reporting for staff, tenant admins and customers | Requested on 21 Oct 2026 | Decided |
| D-029 | Health check | "Check system" button on each dashboard, plus scheduled checks | Quick way to confirm everything is working | Decided (21 Oct 2026) |
| D-030 | Backups | Every 6 hours, encrypted, primary copy with the host plus off-site copy to Google Drive, monthly restore tests | Requested on 21 Oct 2026; encryption protects personal data | Decided |
| D-031 | Tenant backups | Each business also gets encrypted backups of its own data in its own Google Drive; the IT admin connects it in a first-login wizard | Requested on 21 Oct 2026; the business keeps its own copy | Decided |
| D-032 | User guide | In-app, book-style user guide for every dashboard, with automatic screenshots; a feature is not done until its guide page exists | Requested on 21 Oct 2026 | Decided |
| D-033 | Django version | Django 5.2 LTS | Long-term support until April 2028; best for a stable base | Decided (21 Oct 2026) |
| D-034 | Where users are stored | One users table per schema: platform admins in `public`, each business's users in its own schema; login is by email | Strong isolation: a user of one business cannot log in to another. People who need several businesses (for example affiliates or job seekers) will be handled with a separate design later | Decided (21 Oct 2026) |
| D-035 | Tenant deletion | Schemas are never dropped automatically, and tenants cannot be deleted from the admin | Deletion must go through an audited offboarding process with a data export | Decided (21 Oct 2026) |
| D-036 | Subdomain format | `<slug>.<platform-domain>`; slug uses lowercase letters, numbers and underscores (underscores become hyphens in the subdomain) | The slug is also the PostgreSQL schema name | Decided (21 Oct 2026) |
| D-037 | Container images | App image built by GitHub Actions and published to GitHub Container Registry (ghcr.io), for amd64 and arm64; Python packages locked with hashes; PostgreSQL 16 and Redis 7.4 images pinned | Every laptop runs exactly the same versions, with no Docker Hub login needed | Decided (21 Oct 2026) |

## Why schema per tenant?

- Each business's data lives in its own PostgreSQL schema, so a coding mistake is less likely to show one business's data to another.
- Shared platform data (plans, licences, platform billing) lives in the `public` schema.
- Backups, exports and offboarding can be done per tenant.
- Trade-off: database migrations run once per schema, so migrations must be tested well. With many thousands of tenants we may need to review this choice.

## Why a separate React frontend?

- BI needs many interactive charts and drag-and-drop dashboards.
- The same API can later serve the staff mobile app (PWA) and tenant integrations.
- Trade-off: two codebases to maintain (Django and React).
