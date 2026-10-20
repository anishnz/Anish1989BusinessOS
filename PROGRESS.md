# Progress

Last updated: 21 October 2026

This file shows where the project is, so any new session can continue from the right place.

## How to continue

Open a new chat in the ERP CRM project and type:

> Continue building Anish1989 Business OS. Read PROGRESS.md in the GitHub repo anishnz/Anish1989BusinessOS and start the next unchecked task.

## Current stage

**Step 1 (shared core) in progress.** Task 1.1 is done. Next: **1.2 Login, MFA for admins, user model**. See [docs/10-delivery-plan.md](docs/10-delivery-plan.md) and [docs/13-developer-setup.md](docs/13-developer-setup.md).

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
  - 39 tests pass against real PostgreSQL 16 and Redis (isolation, routing, login, admin access, health)
  - GitHub Actions CI: tests + Docker image build
  - Not yet verified: building the Docker image (Docker Hub was blocked in the build workspace; CI builds it on GitHub)
  - Follow-up for later tasks: tenant-aware Celery tasks (run each job in the right schema) when the first tenant job is added
- [ ] 1.2 Login, MFA for admins, user model
- [ ] 1.3 Roles, permissions and audit log
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
