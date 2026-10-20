# 10. Delivery plan

Last updated: 21 October 2026

Agreed on 21 October 2026. Work is full-time. All pilot businesses have said they will pay after the pilot.

## Pilot order

| Step | What we build | Who it serves | Estimated time (full-time) |
|---|---|---|---|
| 1 | Shared core | Everyone | 4 to 6 weeks |
| 2 | Ordering flow (template group A) | Gorkha Butchery + restaurant | 2 to 3 weeks |
| 3 | Enquiry, quote and booking flow (group B) | Catering + events | 3 to 4 weeks |
| 4 | Learning and jobs flow (group C) | Education platform + job platform | 4 to 6 weeks |

**Total estimate: about 13 to 19 weeks** (about 3 to 5 months). These are planning estimates, not promises. Real pilots usually find extra work, and outside steps such as Meta WhatsApp business verification can add waiting time.

## Step 1: Shared core

- Django project, PostgreSQL with schema per tenant, Docker setup
- Login, MFA for admins, roles and permissions, audit log
- Tenant creation, licence and module on/off
- Settings and secret vault (own keys, test connection, masked display)
- Products, customers, basic orders
- WhatsApp adapter (official WhatsApp Business Platform) and a simple unified inbox
- Simple dashboard: today's sales, orders, top products
- Automated tests for login, permissions and tenant isolation
- React/Next.js frontend shell
- Tenant subdomains
- "Check system" health check button (core checks)
- Backups every 6 hours, encrypted, with an off-site copy to Google Drive and a first restore test
- Basic ticket system (report an issue, assign, status)

**Done when:** two test tenants exist, neither can see the other's data (proved by tests), and a WhatsApp test message reaches the inbox.

## Step 2: Ordering flow

- AI order taking with confirmation before recording
- Weight-based final price, stock check, quick reorder
- Order states, status messages, pickup slots, human handover
- Live order board for staff
- Daily owner summary on WhatsApp
- Post-order star feedback
- Custom domains with DNS check and automatic SSL
- Website content editor (title, headings, text, SEO) with "Generate with AI"

**Done when:** Gorkha Butchery and the restaurant take real orders through WhatsApp for one week without staff re-typing orders.

## Step 3: Enquiry, quote and booking flow

- Enquiry capture (WhatsApp, website form)
- Event details: date, venue, guests, menu, dietary needs, budget
- Quote builder and AI quote drafts (human approves)
- Invoices, deposits and manual bank-transfer reconciliation
- Event calendar, supplier and task checklist, reminders

**Done when:** the catering and events businesses send real quotes and record a paid deposit through the system.

## Step 4: Learning and jobs flow

- Courses, lessons, embedded YouTube videos, PDFs, quizzes, progress
- Job board, job listings by location, ATS-friendly resume builder, applications, job alerts
- Legal job sources only (see [Industry templates](09-industry-templates.md))

**Done when:** students enrol and complete a lesson, and job seekers build a resume and apply to a posted job.

## Before each pilot starts

Sign a one-page pilot agreement covering:

- What the business gets, and by when
- What the business gives: data access, time for meetings, feedback
- Pilot length and the price after the pilot
- Who owns the data (the business owns its data)
- How to stop the pilot

Have an NZ accountant or lawyer check the agreement template once.

## How work continues between sessions

The build is split into small tasks. After each task, the work is committed to GitHub and [PROGRESS.md](../PROGRESS.md) is updated. If a session stops (for example, when usage limits are reached), a new session reads `PROGRESS.md` and continues from the next unchecked task. No work is lost except the task in progress at that moment.
