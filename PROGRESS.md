# Progress

Last updated: 23 October 2026

This file shows where the project is, so any new session can continue from the right place.

## How to continue

Open a new chat in the ERP CRM project and type:

> Continue building Anish1989 Business OS. Read PROGRESS.md in the GitHub repo anishnz/Anish1989BusinessOS and start the next unchecked task.

## Current stage

**Step 1 (shared core) is complete** (tasks 1.1 to 1.17, 22 October 2026). Still open for the Step 1 "done" check: a real WhatsApp test message through Meta (guide 7.8). Now: **Step 2, ordering flow**. Tasks 2.1 (pickup and delivery), 2.2 (stock), 2.3 (WhatsApp messages about orders) 2.4 (AI order taking on WhatsApp), 2.5 (quick reorder and hand-over), 2.6 (live order board), 2.7 (daily owner summary and star feedback), 2.8 (own domains with DNS check and HTTPS) and 2.9 (website and editor), and the extra task 1.18 (test data, Log in as, safer deleting) are done. Still open for the Step 2 "done" check: real pilot orders through WhatsApp for one week. Now: **Step 3, enquiry, quote and booking flow** (tasks 3.1 to 3.6 agreed 23 October 2026). Task 3.1 (enquiries) is done. Next task: 3.2 (packages and the quote builder). See [docs/10-delivery-plan.md](docs/10-delivery-plan.md) and [docs/13-developer-setup.md](docs/13-developer-setup.md).

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
  - Still to do for the Step 1 "done" check: a real WhatsApp message from Meta (needs a public https address: a server, or the Cloudflare tunnel in guide 7.8)
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
- [x] 1.14 Backups every 6 hours to Google Drive (encrypted) and restore test (done 21 Oct 2026)
  - Platform: the whole database (every business) and uploaded files every 6 hours, encrypted with `BACKUP_ENCRYPTION_KEYS` (start scripts create it), kept on the server (Docker volume) and copied to Google Drive when connected
  - Business: its own data only, encrypted with its own passphrase (shown once), copied to its own Google Drive
  - Own encrypted file format (AES-256-GCM in chunks; changes and cut-off files detected) and a stand-alone tool to open a backup anywhere
  - "Connect Google Drive" with Google sign-in (drive.file permission only, PKCE, one return address on the platform domain, finish only in the same session); access stored in the vault; password needed again
  - Restore test every 7 days and with a button: newest backup (from Google Drive when there is a copy) loaded into a temporary database, every table's row count compared
  - Keeps every backup 7 days, then daily to 30 days, then monthly for 12 months; failures email the admins once; removed Google access pauses copies until reconnected
  - Backups page `/backups/`, API `/api/backups/`, Check system lines, `backup_now` and `open_backup` commands; Docker image now has the PostgreSQL 16 tools
  - First restore test passed in the sandbox on 21 Oct 2026 (92 tables, all row counts matched)
  - Still to do by Anish: create the Google sign-in app in Google Cloud (user guide 12.6), save the `BACKUP_ENCRYPTION_KEYS` line from `.env` in a password manager
  - User guide chapter: docs/user-guide/12-backups.md
  - 618 tests pass
- [x] 1.15 Basic ticket system (done 21 Oct 2026)
  - "Report a problem" on every admin page (page path, browser and time added; no secrets), "Tickets" list with tabs and numbers (open, new, overdue, average first answer)
  - Staff see their own tickets; Tickets – Edit sees all and writes internal notes; Tickets – Assign assigns and sends to platform support
  - Statuses New / In progress / Waiting for reply / Resolved / Closed; first-answer targets by priority (1 h, 4 h, 24 h, 3 days)
  - Platform support: a copy in the platform, answers shown on the business's ticket, replies both ways, emails to the right people
  - Automatic tickets for failed scheduled checks and backups (one open ticket per problem); "Create ticket" buttons on Check system and Backups
  - API for the staff app; IT Admins get the Tickets permissions in new businesses
  - Not yet: file uploads (screenshots), in-app notifications, customer tickets from WhatsApp or the website
  - User guide chapter: docs/user-guide/13-tickets.md
  - 640 tests pass
- [x] 1.16 First-login setup wizard with per-tenant Google Drive backup connection (done 21 Oct 2026)
  - Opens on the admin home page for System Admins and IT Admins of a business that has not finished setup; "Later" closes it for that sign-in
  - Steps: business details (trading name, phone, email, address, GST number, website; checked), backups (passphrase, Google Drive, test backup "Backup working"), connections (email, WhatsApp, AI), done
  - Comes back to the wizard after the passphrase page and the Google sign-in (only `/setup/` addresses accepted)
  - Yellow reminder on every admin page until backups are set up; "Set up your business" link in the header
  - User guide chapter: docs/user-guide/14-first-login-setup.md
  - 666 tests pass
- [x] 1.17 In-app user guide framework and "Getting started" chapters (done 22 Oct 2026)
  - The chapters in docs/user-guide/ are shown inside the app at `/guide/`: contents by group, chapter pages with "On this page" and previous/next, search with highlighted results
  - Safe built-in Markdown reader (no HTML or scripts from chapters, safe links only); no new package
  - "Help" link on every admin page opens the chapter about that page; "Help" in the staff app
  - Automatic screenshots: `tools/guide_screenshots.py` + `docs/user-guide/screenshots.json` (8 pictures added to the chapters)
  - New "Getting started" chapter; "Getting started" group: getting started, logging in, first-login setup, staff app, tickets
  - The Docker image carries the guide (`/opt/guide`)
  - 682 tests pass; 44 of 45 deliberate breaks in tasks 1.14 to 1.17 are caught by tests (the 45th, a platform check on /setup/, cannot be reached)
- [x] 1.18 Test data, Log in as and safer deleting (added on request, done 22 Oct 2026)
  - Decisions D-126 to D-129
  - Platform page **Test data** (Super Admin only): **Install test data** makes six test businesses with Nepali names at 2 White Street, Auckland City, Auckland 1010 (butchery, restaurant, catering, events, education consultancy, jobs), each with a user for every role (`roleas<role>@anish1989.com.np`), business details, pickup and delivery, products, customers, orders in every step, conversations and tickets; **Remove test data** deletes only test businesses
  - The shared test password is `DEMO_PASSWORD` in `.env` (never in the code); test accounts in test businesses skip two-step verification; platform test accounts keep it; no test Super Admin
  - **Log in as** (Super Admin only) from Test data and Businesses and users: one-time 60-second link, 60-minute session, red bar with **Back to Super Admin** (admin pages and staff app), reason for real businesses, both audit logs
  - Safer deleting: every delete in the admin pages and the Remove buttons need a small sum, a 5-second wait and a last "Are you sure?" (checked by the server)
  - Commands: `install_test_data`, `remove_test_data`
  - User guide chapter: docs/user-guide/16-test-data-and-log-in-as.md

## Step 2: Ordering flow

- [x] 2.1 Pickup and delivery: opening hours, time slots with capacity, closed days, delivery areas and fees, "Out for delivery" status (done 22 Oct 2026)
  - Decisions D-117 to D-125: pay at pickup or on delivery, pickup and delivery, English and Nepali, slot rules, strict for customers and warnings for staff, delivery areas and fees, "Out for delivery", Orders – Configure, the due time
  - New app `apps.fulfilment`: settings (slot lengths, orders per slot, preparation time, days ahead, GST in fees), opening hours per weekday (pickup and delivery), closed days, delivery areas (postcodes, suburbs, fee, minimum order, free delivery from)
  - Slots in New Zealand time (clocks going forward handled); a slot counts orders from "Awaiting customer confirmation" on
  - Orders: pickup or delivery, due time and slot end, delivery address, area (found from postcode or suburb) and fee (part of the total, kept when fees change later); "Ready for pickup" / "Ready for delivery", "Out for delivery"
  - Staff app: pickup or delivery, address with the area and fee, day and slot buttons (taken, full, too soon), another time; warnings on the order; change on the order page
  - Admin: settings page with "Times customers can choose now", closed days, delivery areas; order list and form with pickup or delivery
  - Check system: "Pickup and delivery" warns when customers cannot choose a time
  - User guide chapter: docs/user-guide/15-pickup-and-delivery.md (chapters 0, 6, 8 and 9 updated)
  - 735 tests pass (51 new for pickup and delivery) and 8 staff app tests; all 41 deliberate breaks in task 2.1 are caught by tests (4 tests were added or made stronger to catch them)
- [x] 2.2 Stock: track stock per product, check it and take it off when an order is confirmed, put it back when cancelled, low-stock alerts (done 22 Oct 2026)
  - Decisions D-130 to D-134
  - Products: **Count stock** (off by default), **Warn at**, stock in kg, packs or items; states In stock, Low, Out of stock, Below zero
  - Orders: confirming takes the ordered amount off, the real weight changes it by the difference, cancelling a confirmed order puts it back; drafts and orders waiting for the customer hold no stock
  - Not enough stock: customers (WhatsApp AI and website, coming next) cannot confirm; staff can, and see a warning on the order
  - Changes by hand (Products – Edit): Received, Counted, Waste, Correction (waste and corrections need a note); the stock history cannot be changed or deleted
  - Staff app: **In stock** column, **Stock** button with the form and history, **Only low or out of stock**, **Low stock** card on the dashboard, stock shown when adding an order
  - Admin: **In stock** column and filter, **Adjust stock** / **Stock history** page; CSV columns `count_stock`, `warn_at`, `stock`
  - Test data: the butchery, restaurant, catering and events test businesses now have stock (one product low and one out of stock each)
  - User guide: chapter 5.5 (with a picture), chapters 6 and 8 updated
  - 826 tests pass (56 new for stock, 1 more in the test data tests) and 8 staff app tests; 59 of 60 deliberate breaks in task 2.2 are caught by tests (4 tests were added to catch them); the 60th (stock_quantity listed as read-only in the API) changes nothing, because the field cannot be edited anyway
- [x] 2.3 WhatsApp status messages and final-price acceptance (approved templates; the customer answers Yes or No) (done 22 Oct 2026)
  - Decisions D-135 to D-139 (all messages on by default, "No" goes back to staff, staff can send orders to confirm, English for now)
  - Messages: please confirm (Yes/No), confirmed, final price (Yes/No), ready, out for delivery, cancelled by the shop; each can be switched off
  - Sent by the worker: normal messages with reply buttons within 24 hours of the customer's last message, approved templates after that
  - Answers by button or typed (yes, ok, ho / no, hoina); Yes to confirm follows the customer rules (slots, areas, stock); No goes back to Draft or Being prepared with a warning for staff
  - Order pages (staff app and admin) list the messages with Sent / Delivered / Read / answered / Not sent and why; settings page with the template texts for Meta; Check system item "WhatsApp messages about orders"
  - Test data: made-up messages on the test orders (never sent)
  - User guide: new chapter 17 (with 2 pictures); chapters 0, 6, 7, 11 and 16 updated
  - 871 tests pass (44 new for WhatsApp messages, 1 more in the test data tests) and 8 staff app tests; 53 of 56 deliberate breaks in task 2.3 are caught by tests (7 tests were added or made stronger to catch them); the other 3 are extra safety checks that cannot change anything today
- [x] 2.4 AI order taking on WhatsApp in English and Nepali: AI keys per business, product search, time slots, order summary, the customer confirms, AI log (done 22 Oct 2026)
  - Decisions D-140 to D-146 (all three AI providers, always on unless staff took over, monthly NZ$ limit, simple shop questions allowed)
  - New app `apps.ai`: OpenAI, Claude and Gemini with tools; the AI searches products, tells shop facts and free times, checks delivery addresses, builds the order and sends the Yes/No summary; only the customer's Yes confirms (with every customer rule)
  - Quiet in chats staff handle (assigned, staff replied in 12 hours, handed over); hands over for complaints, refunds, photos, errors and limits, and tells the customer once
  - Monthly NZ$ limit (default NZ$20) and 40 answers per chat per day; AI log with tokens, estimated cost, tools and steps; Check system item
  - Staff app: AI bar in each chat ("I will answer" / "Let the AI answer again"), AI messages marked; admin settings page and AI log
  - Test data: AI settings and two made-up AI chats per business (no AI key, so the AI never answers there)
  - User guide: new chapter 18 (with 2 pictures); chapters 0, 7, 11 and 16 updated
  - 916 tests pass (44 new for the AI, 1 more in the test data tests) and 8 staff app tests; 54 of 56 deliberate breaks in task 2.4 are caught by tests (7 tests were added to catch them); of the other 2, one was a repeated check (removed) and one is an extra safety check that cannot change anything today
- [x] 2.5 Quick reorder ("same as last time") and human handover in the inbox (done 22 Oct 2026)
  - Decisions D-147 to D-150 (the AI offers the last 3 orders; inbox filter, menu badge, dashboard card and email; "Order again" for staff; "I will answer" assigns the chat)
  - Order again: a new draft with the same products, amounts, notes and address at today's prices, without the time; products that cannot be ordered are left out and named. Staff button on the order page and next to the customer's last order; the AI tools `past_orders` and `reorder`
  - Chats waiting for staff: "Needs staff" filter and labels in the inbox, a red count in the menu, a dashboard card, and one email per AI hand-over to staff with Customers – Assign (name, reason and link; never the messages; can be switched off)
  - Test data: a made-up "same as last time" AI chat and a chat waiting for staff
  - User guide: chapters 6.7, 7.4 and 18.5–18.6 (chapter 7 sections renumbered)
  - 929 tests pass (13 new) and 8 staff app tests; 28 of 30 deliberate breaks in task 2.5 are caught by tests (1 test was made stronger); of the other 2, one was a repeated check (removed) and one cannot change anything (people who are switched off have no permissions)
- [x] 2.6 Live order board for the counter and kitchen (done 23 Oct 2026)
  - Decisions D-151 to D-154 (staff app page with TV mode, one tap to the next step, a chime for new orders, today and late orders)
  - New **Board** page in the staff app: To prepare, Being prepared, Ready, Out for delivery; today's, late and no-time orders ("Show tomorrow" adds tomorrow's); updates every 10 seconds; late orders first with a red edge
  - One button per card for the next step (the normal status rules and WhatsApp messages); a note when weights must be entered or the customer must answer; a second tap to complete an order that is not paid
  - TV mode (full screen, bigger text, clock), a browser-made chime with Sound on/off, a clear "login has ended" note
  - Privacy: short names and suburbs only, never street addresses or phone numbers
  - API `GET /api/orders/board/` (Orders – View)
  - Test data: four open orders due today, two of them late
  - User guide: new chapter 19 (with 2 pictures); chapters 0, 6, 9 and 16 updated
  - 940 tests pass (10 new for the board, 1 more in the test data tests) and 11 staff app tests (3 new); all 24 deliberate breaks of the board code and all 6 of the board helpers in the staff app are caught by tests (2 tests were made stronger)
- [x] 2.7 Daily owner summary on WhatsApp and star feedback after the order (done 23 Oct 2026)
  - Decisions D-155 to D-158 (WhatsApp and email, owner chooses the time with 20:00 by default, ask 1 hour after completed, low ratings ask why and go to staff)
  - Daily summary: today's sales and completed orders (with last week), orders confirmed, top 3 products, open orders, low stock, feedback and chats waiting for staff; WhatsApp template to the owner's numbers and email (default: owners); once a day, not on a closed day without orders; "Send a test now"; list of sent summaries
  - Star feedback: 1 hour after an order is completed, a 5-choice list (or a template with 5 buttons after 24 hours); skipped for walk-ins, customers who never wrote on WhatsApp, STOP, and more than once a week; 1-2 stars ask what went wrong, go to Needs staff and keep the comment
  - Shown on the order (staff app and admin), a Customer feedback list, a dashboard card (last 7 days) and the summary
  - New scheduled jobs (every 5 and 10 minutes) for every business, skipping suspended businesses and switched-off modules
  - Test data: made-up feedback (one low with a comment) and yesterday's summary; the summary email is off and no WhatsApp numbers in test businesses
  - User guide: new chapter 20 (with 2 pictures); chapters 8, 16 and 17 updated
  - 973 tests pass (32 new for feedback and the summary, 1 more in the test data tests) and 11 staff app tests; 40 of 41 deliberate breaks in task 2.7 are caught by tests (8 tests were made stronger, and a clash where "not run" and "skipped" looked the same was fixed); the 41st was a repeated permission check (removed)
- [x] 2.8 Custom domains with DNS check and automatic SSL (done 23 Oct 2026)
  - Decisions D-159 to D-163 (Caddy on-demand HTTPS, TXT code plus pointing, business admins add domains, warn then fall back after 3 days)
  - Settings → Web addresses for the business: add up to 3 own domains, the exact DNS records to add, Check now, make main, remove (with the safety check); System Admin and IT Admin change, the Business Owner sees
  - DNS check (dnspython): hourly while waiting (daily after a week), daily when live, hourly when broken; live → Domain row; broken → email at once, after 3 days the platform address is the main address again
  - Routing: live own domains pass the host check without a settings change; www.<name> works too; Caddy's certificate question answered only for real addresses
  - Server: `deploy/Caddyfile` and a `caddy` service (`docker compose --profile server up -d`); `.env` gets ACME_EMAIL and PLATFORM_SERVER_IPS
  - Super Admin sees and can remove each business's own domains; Check system item "Own domains"
  - Test data: a made-up `.example` domain per test business (never live)
  - User guide: new chapter 21 (with a picture); chapters 10 and 11 updated
  - 1016 tests pass (42 new for own domains, 1 more in the test data tests) and 11 staff app tests; 43 of 45 deliberate breaks in task 2.8 are caught by tests (6 tests were made stronger); the other 2 were checks that could never fire (removed)
- [x] 2.9 Website content editor (title, headings, text, SEO) with "Generate with AI" (done 23 Oct 2026)
  - Decisions D-164 to D-167 (one-page site, staff app editor with preview, draft / publish / history, AI per field into the draft)
  - Public page at the business's main address: texts, WhatsApp button, products and prices (Sold out), pickup and delivery hours, delivery areas, closed days, contact; robots.txt, sitemap.xml, search-engine facts; no cookies or scripts
  - Staff app **Website** page: 12 texts with limits, 4 switches, WhatsApp number; saves the draft by itself; live preview; Publish; history of 20 versions with restore
  - "Generate with AI" per text with the business's AI key (public facts only, monthly limit, AI log, 30 an hour); the person uses or discards it
  - Test data: a published website and a draft change per test business
  - User guide: new chapter 22 (with 2 pictures); chapters 9 and 16 updated
  - 1038 tests pass (21 new for the website, 1 more in the test data tests) and 14 staff app tests (3 new); 38 of 39 deliberate breaks in task 2.9 are caught by tests (3 tests were made stronger), the 39th was a check that could never fire (removed); all 4 breaks of the editor helpers are caught

## Step 3: Enquiry, quote and booking flow

Tasks agreed 23 October 2026 (decisions D-168 to D-171: one shared Events module, bank transfer with payments recorded by staff, quote web page with PDF, per-guest packages plus extras). **Done when:** the catering and events businesses send real quotes and record a paid deposit through the system.

- [x] 3.1 Enquiries: a form on the business website and enquiries from WhatsApp chats, with event details (type, date, time, venue, guests, dietary needs, budget), status and an enquiry list (done 23 Oct 2026)
  - Decisions D-172 to D-176: own form page at /enquiry/ with an "Ask for a quote" button; spam checks (hidden field, signed time stamp, limits) plus each business's own Cloudflare Turnstile keys; the AI asks the event questions on WhatsApp, and staff can always click "Make enquiry"; statuses New, Contacted, Quoted, Won, Lost (Lost needs a reason); privacy rules for enquiry data
  - New app `apps.events`: enquiry settings, enquiries and their history; the public form; API `/api/events/enquiries/`; AI tool `save_enquiry`; staff email for new enquiries; personal data removed with the customer's
  - Vault: new provider Cloudflare Turnstile (group "Website protection") with a connection test
  - Staff app: **Enquiries** list with tabs and counts, one enquiry page (details, status, notes, history), **Make enquiry** in a chat
  - Test data: six made-up enquiries per test business, one per status; no email is sent
  - User guide: new chapter 23 (with 3 pictures); chapters 4, 9, 18 and 22 updated (new website picture)
  - 1117 tests pass (78 new for enquiries, 1 more in the test data tests) and 18 staff app tests (4 new); 80 of 82 deliberate breaks in task 3.1 are caught by tests (3 tests were made stronger); the other 2 were checks that could never fire (removed); all 8 breaks of the staff app helpers are caught
- [ ] 3.2 Packages and the quote builder: per-guest packages and extras, quote lines with GST, quote versions
- [ ] 3.3 The customer's quote page and PDF: a private link sent on WhatsApp or by email, Accept button, expiry date
- [ ] 3.4 AI quote drafts from the enquiry (a person checks and approves before anything is sent)
- [ ] 3.5 Invoices and deposits: a deposit invoice when the quote is accepted, a final invoice, bank details and a reference code, payments recorded by staff, what is still owed, payment reminders
- [ ] 3.6 Event calendar, supplier and task checklist, reminders before the event, and feedback after it

## Step 4: Learning and jobs flow

Not started.
