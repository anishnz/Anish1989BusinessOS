# Progress

Last updated: 21 October 2026

This file shows where the project is, so any new session can continue from the right place.

## How to continue

Open a new chat in the ERP CRM project and type:

> Continue building Anish1989 Business OS. Read PROGRESS.md in the GitHub repo anishnz/Anish1989BusinessOS and start the next unchecked task.

## Current stage

**Step 1 (shared core) in progress.** Tasks 1.1 to 1.13 are done. Next: **1.14 Backups every 6 hours to Google Drive (encrypted) and restore test**. See [docs/10-delivery-plan.md](docs/10-delivery-plan.md) and [docs/13-developer-setup.md](docs/13-developer-setup.md).

## Documentation

- [x] Mind map, decisions, feature catalogue
- [x] Tenant settings and secret vault
- [x] WhatsApp AI ordering
- [x] Business intelligence
- [x] Competitor intelligence
- [x] Industry templates and job module
- [x] Delivery plan and pilot order
- [x] Platform operations (domains, content editor, tickets, health checks, backups)
- [x] Per-tenant Google Drive backups and in-app user guide
- [ ] Answer the remaining open questions (docs/08-open-questions.md)
- [ ] Pilot agreement template

## Step 1: Shared core

- [x] 1.1 Project setup: Django, PostgreSQL, django-tenants, Docker, settings per environment (done 21 Oct 2026)
  - Django 5.2 LTS, django-tenants 4.0, DRF, Celery + Redis, settings from environment variables
  - Apps: `tenants` (Tenant, Domain), `accounts` (email-login User, one table per schema), `core` (health endpoint)
  - Commands: `bootstrap_platform`, `create_business`
  - Docker: Dockerfile, docker-entrypoint.sh, docker-compose.yml (db, redis, web, worker, scheduler)
  - 40 tests pass against real PostgreSQL 16 and Redis (isolation, routing, login, admin access, health), with both development and production settings
  - GitHub Actions CI is green: tests + Docker image build
  - Same versions everywhere: locked Python packages with hashes, pinned PostgreSQL/Redis images, app image published to ghcr.io by CI (amd64 + arm64)
  - One-command start: `start.cmd` / `start.ps1` (Windows) and `start.sh` (macOS/Linux)
  - Verified on Anish's Windows laptop (21 Oct 2026): image pulled from ghcr.io, all 5 containers started, platform healthy
  - Follow-up for later tasks: tenant-aware Celery tasks (run each job in the right schema) when the first tenant job is added
- [x] 1.2 Login, MFA for admins, user model (done 21 Oct 2026)
  - Email login per business, Argon2 hashing, lockout (5 tries / 15 min, per email per business)
  - Authenticator-app MFA required for staff/admins, 10 backup codes, setup and verify pages, JSON auth API
  - MFA cannot be bypassed with a password alone (tested); authenticator secrets hidden from admin; "Reset two-step verification" admin action
  - Login history (read-only), password reset by email (link to the business's own site, 1 hour)
  - User guide chapter: docs/user-guide/01-logging-in-and-two-step-verification.md
  - 83 tests pass (development and CI settings)
- [x] 1.3 Roles, permissions and audit log (done 21 Oct 2026)
  - Permission catalogue (module + 17 actions), 25 default business roles (Shop Staff added in 1.6) and 4 platform roles, custom roles
  - Deny-by-default policy checked on the server (user active → business active → module → role); admin pages follow roles
  - Escalation protection: grant only what you have, not your own roles, full access only from full admins
  - Tamper-proof audit log: hash chain + database trigger; secrets redacted; logins, user/role/MFA changes and denied requests recorded; `verify_audit_chain`
  - Roles API for the React frontend; role editor in the admin
  - User guide chapter: docs/user-guide/02-roles-permissions-and-audit-log.md
  - 133 tests pass
  - Later: department/branch scopes (with the departments module), module entitlements (1.4)
- [x] 1.4 Tenants, licences and module on/off (done 21 Oct 2026)
  - Licence per business (30-day trial, grace period, limits); states trial/active/grace/expired/suspended/cancelled
  - Blocked businesses stopped on every page and API with a clear message; grace warning header
  - Modules: entitled by the platform, switched on/off by the business; industry templates; permission policy checks them
  - Active-user limit enforced; usage shown in the licence API
  - Super Admin: create business with System Admin invitation, edit licence and modules, suspend (reason), reactivate, extend trial, mark paid; all audited
  - User guide chapter: docs/user-guide/03-businesses-licences-and-modules.md
  - 170 tests pass
- [x] 1.5 Settings and secret vault (done 21 Oct 2026)
  - Each business saves its own keys for AI (OpenAI, Anthropic, Gemini, Ollama), messaging (WhatsApp Cloud, Viber, Telegram), email (SMTP), SMS (Twilio), Google Places and bank transfer details
  - AES-256-GCM envelope encryption, bound to business and connection; master key in `.env` (start scripts create it); `rotate_vault_key`
  - Keys never shown again (last 4 only), never in API answers, audit log or error messages
  - "Test connection" button with clear status; backup connection used when the main one fails
  - Private-network (SSRF) guard, no redirects, 10-second timeout
  - Permissions: view / configure / manage integrations
  - Settings page `/settings/integrations/` and API `/api/integrations/`
  - User guide chapter: docs/user-guide/04-integrations-and-api-keys.md
  - 221 tests pass
- [x] 1.6 Products and customers (done 21 Oct 2026)
  - System emails (invitations, password resets) sent through Gmail with an app password; business Gmail first, then the platform's; `send_test_email`
  - Products: categories, kg/each/pack, NZ$ prices incl. GST, cost price (editors only), min quantity and steps, other names for search and the AI, available/archived
  - Customers: NZ and overseas phone numbers saved as +64..., no duplicate phone or email, tags, staff notes, marketing consent history (NZ law)
  - Privacy: personal data never copied into the audit log; "remove personal data" keeps the record for orders and reports
  - CSV import (check first, all-or-nothing) and export (formula-safe, audited) for products and customers
  - APIs `/api/products/` and `/api/customers/`; admin pages; business-only (hidden on the platform site)
  - User guide chapter: docs/user-guide/05-products-and-customers.md (and Gmail in chapter 4)
  - New default role **Shop Staff** for counter staff (products view, customers view/add/change, orders, tickets)
  - 306 tests pass
- [x] 1.7 Basic orders (done 21 Oct 2026)
  - Orders #1001 onwards per business, with product lines that keep the price of the moment; prices only from products
  - Amount rules (minimum and steps, e.g. 0.5 kg), unavailable products and removed customers refused
  - Status flow from the WhatsApp plan: draft, awaiting confirmation, confirmed, being prepared, final price sent/accepted, ready, completed, cancelled (reason), expired
  - Real weights entered while preparing; the customer accepts a changed price before "ready"
  - Totals with GST; paid / not paid with method; paid orders must be refunded before cancelling
  - Order history (who, when, why) and audit log; notes kept out of the audit log
  - API `/api/orders/`, admin pages (add with lines, weights, "Status and payment"), CSV export, `expire_orders` command
  - User guide chapter: docs/user-guide/06-orders.md
  - 345 tests pass
- [x] 1.8 WhatsApp adapter and unified inbox (done 21 Oct 2026)
  - Each business connects its own WhatsApp Business number (official Cloud API, Graph API v25.0)
  - Webhook per business: verify token, signature check with the app secret, own phone number only, duplicates ignored
  - Incoming messages create or link customers; text, images, buttons, locations; STOP opts out (consent history)
  - Inbox: conversations with unread counts, chat page, reply within 24 hours, approved templates (marketing only with consent), assign, close/reopen
  - Delivery status: sent, delivered, read, failed (with reason)
  - Messages kept out of the audit log and deleted when a customer's data is removed
  - Webhook URL and verify token shown on the Integrations page; `whatsapp_simulate` for laptop tests
  - Operations Manager default role now also sees products and customers
  - User guide chapter: docs/user-guide/07-whatsapp-and-inbox.md
  - 385 tests pass
  - Still to do for the Step 1 "done" check: a real WhatsApp message from Meta (needs a public https address: a server, or the Cloudflare tunnel in guide 7.7)
- [x] Extra (21 Oct 2026): MFA tools and Super Admin user control
  - 16-character backup codes with print/download; "My two-step verification" page: new backup codes and new phone (QR), both need the password
  - `reset_mfa` command for locked-out accounts
  - Super Admin "Businesses and users": every business and its users, roles, MFA status; change roles, reset MFA, switch MFA off (reason) / on, lock / unlock; audited in both logs
  - Fixed: deleting a platform user failed
  - User guide: chapter 1 (1.4, 1.5) and chapter 3 (3.7)
  - 410 tests pass
- [x] 1.9 Simple dashboard (done 21 Oct 2026)
  - Sales today (completed orders, incl. GST) compared with the same day last week; orders confirmed; average sale; completed but not paid; unread WhatsApp chats
  - Sales for the last 7 days (bar chart with hover values and a table), top 5 products, orders needing attention, pickups due today
  - Choose another day; days follow New Zealand time
  - Page `/dashboard/` (header link) and API `/api/reports/dashboard/`; needs Reports – View
  - User guide chapter: docs/user-guide/08-dashboard.md
  - 422 tests pass
- [x] 1.10 Tenant isolation and permission tests (done 21 Oct 2026)
  - Security sweep tests that find every page and API by themselves: not logged in, no role, MFA not finished, business B vs business A (every API and admin page), platform pages, module off, suspended business
  - CSRF and cookie tests; Django production checks in CI
  - Fixed 4 bugs found by the sweeps (a crashing roles API, a crashing view-only role page, a crashing tenant page on business sites, CSRF token not readable by the future React app)
  - 440 tests pass
- [x] 1.11 React staff app (done 21 Oct 2026)
  - React app at `/app/` on each business address: login with two-step code, menu that shows only what your role and modules allow, light/dark theme, works on phones
  - Screens: Dashboard, Orders (list, new order, order page with weights, next step, cancel, payment, history), Inbox (read and reply, 24-hour rule), Products and Customers (search)
  - Built by Vite; served by Django (no separate server); built inside the Docker image; CI job for type check, tests and build
  - Fixed: phone layout (menu drawer, no sideways scrolling, order lines as blocks); no 403 error in the browser before login
  - User guide chapter: docs/user-guide/09-staff-app.md
- [x] 1.12 Tenant subdomains (done 21 Oct 2026)
  - Each business: up to 5 web addresses on the platform domain, one main address; the others send visitors to it (302), while the API, webhooks and health checks work on every address
  - Web address name can be chosen when creating a business (`--subdomain` in `create_business`)
  - Super Admin page "Web addresses" (add, make main, remove), with rules (reserved names, format, unique) and both audit logs; Domain admin is now read-only
  - Friendly "No business at this address" page; host names matched without case
  - `change_platform_domain` moves the platform and every business address (laptop to real domain); `bootstrap_platform` no longer adds a second platform address
  - Licence API lists the business's addresses; invitation links use the main address
  - Server DNS and HTTPS steps documented (wildcard record and certificate; depends on the hosting choice)
  - User guide chapter: docs/user-guide/10-web-addresses.md
  - 509 tests pass
- [x] 1.13 "Check system" health check button (done 21 Oct 2026)
  - Business checks: database and updates, cache, background worker, scheduled jobs (heartbeat), licence, web address, every saved connection tested live (in parallel), email sending, WhatsApp webhook, staff two-step verification, audit log, backups (not set up yet)
  - Platform checks: also every business's database, disk space, licences needing attention, businesses with failed connections or checks, vault master key, production security settings
  - Results OK / Needs attention / Failed / Not set up, with plain messages (no secrets or error details); history of runs (last 500); button limited to once a minute
  - Runs every hour by itself (Celery beat); email to admins when a scheduled check turns red; `check_system` command
  - Page `/system-check/` and API `/api/system-check/`; "Check system" link in the admin header
  - User guide chapter: docs/user-guide/11-check-system.md
  - 546 tests pass
- [ ] 1.14 Backups every 6 hours to Google Drive (encrypted) and restore test
- [ ] 1.15 Basic ticket system
- [ ] 1.16 First-login setup wizard with per-tenant Google Drive backup connection
- [ ] 1.17 In-app user guide framework and "Getting started" chapters

## Step 2: Ordering flow

Not started.

## Step 3: Enquiry, quote and booking flow

Not started.

## Step 4: Learning and jobs flow

Not started.
