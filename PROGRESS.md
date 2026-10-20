# Progress

Last updated: 21 October 2026

This file shows where the project is, so any new session can continue from the right place.

## How to continue

Open a new chat in the ERP CRM project and type:

> Continue building Anish1989 Business OS. Read PROGRESS.md in the GitHub repo anishnz/Anish1989BusinessOS and start the next unchecked task.

## Current stage

**Step 1 (shared core) in progress.** Tasks 1.1 to 1.3 are done. Next: **1.4 Tenants, licences and module on/off**. See [docs/10-delivery-plan.md](docs/10-delivery-plan.md) and [docs/13-developer-setup.md](docs/13-developer-setup.md).

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
  - Permission catalogue (module + 17 actions), 24 default business roles and 4 platform roles, custom roles
  - Deny-by-default policy checked on the server (user active → business active → module → role); admin pages follow roles
  - Escalation protection: grant only what you have, not your own roles, full access only from full admins
  - Tamper-proof audit log: hash chain + database trigger; secrets redacted; logins, user/role/MFA changes and denied requests recorded; `verify_audit_chain`
  - Roles API for the React frontend; role editor in the admin
  - User guide chapter: docs/user-guide/02-roles-permissions-and-audit-log.md
  - 133 tests pass
  - Later: department/branch scopes (with the departments module), module entitlements (1.4)
- [ ] 1.4 Tenants, licences and module on/off
- [ ] 1.5 Settings and secret vault (encrypted keys, test connection)
- [ ] 1.6 Products and customers
- [ ] 1.7 Basic orders
- [ ] 1.8 WhatsApp adapter and unified inbox
- [ ] 1.9 Simple dashboard
- [ ] 1.10 Tenant isolation and permission tests
- [ ] 1.11 React/Next.js frontend shell
- [ ] 1.12 Tenant subdomains
- [ ] 1.13 "Check system" health check button
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
