# 10. Delivery plan

Last updated: 23 October 2026

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
- First-login setup wizard with per-tenant Google Drive backup connection
- In-app user guide framework (table of contents, search, automatic screenshots) with the "Getting started" chapters

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

Tasks (agreed 22 October 2026; payment at pickup or on delivery, pickup and delivery, English and Nepali — D-117 to D-119):

- 2.1 Pickup and delivery: opening hours, time slots with capacity, closed days, delivery areas and fees, "Out for delivery" status
- 2.2 Stock: track stock per product, check it and take it off when an order is confirmed, put it back when cancelled, low-stock alerts
- 2.3 WhatsApp status messages and final-price acceptance (approved templates; the customer answers Yes or No)
- 2.4 AI order taking on WhatsApp in English and Nepali: AI keys per business, product search, time slots, order summary, the customer confirms, AI log
- 2.5 Quick reorder ("same as last time") and human handover in the inbox
- 2.6 Live order board for the counter and kitchen
- 2.7 Daily owner summary on WhatsApp and star feedback after the order
- 2.8 Custom domains with DNS check and automatic SSL
- 2.9 Website content editor (title, headings, text, SEO) with "Generate with AI"

## Step 3: Enquiry, quote and booking flow

- Enquiry capture (WhatsApp, website form)
- Event details: date, venue, guests, menu, dietary needs, budget
- Quote builder and AI quote drafts (human approves)
- Invoices, deposits and manual bank-transfer reconciliation
- Event calendar, supplier and task checklist, reminders

**Done when:** the catering and events businesses send real quotes and record a paid deposit through the system.

Tasks (agreed 23 October 2026; one shared Events module, bank transfer with payments recorded by staff, quote web page with PDF, per-guest packages plus extras — D-168 to D-171):

- 3.1 Enquiries: a form on the business website and enquiries from WhatsApp chats, with event details (type, date, time, venue, guests, dietary needs, budget), status and an enquiry list
- 3.2 Packages and the quote builder: per-guest packages and extras, quote lines with GST, quote versions
- 3.3 The customer's quote page and PDF: a private link sent on WhatsApp or by email, Accept button, expiry date
- 3.4 AI quote drafts from the enquiry (a person checks and approves before anything is sent)
- 3.5 Invoices and deposits: a deposit invoice when the quote is accepted, a final invoice, bank details and a reference code, payments recorded by staff, what is still owed, payment reminders
- 3.6 Event calendar, supplier and task checklist, reminders before the event, and feedback after it

## Step 4: Learning and jobs flow

- Courses, lessons, embedded YouTube videos, PDFs, quizzes, progress
- Job board, job listings by location, ATS-friendly resume builder, applications, job alerts
- Legal job sources only (see [Industry templates](09-industry-templates.md))

**Done when:** students enrol and complete a lesson, and job seekers build a resume and apply to a posted job.

## Definition of done (every feature)

A feature is done only when its screen, backend, database rules, permission checks, error handling, audit log, automated tests **and user guide page** all work together.

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
