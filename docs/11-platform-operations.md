# 11. Platform operations

Last updated: 21 October 2026

This document covers domains, website content editing, the ticket system, the health check button and backups.

## 1. Domains, subdomains and custom URLs

| Feature | How it works | Phase |
|---|---|---|
| Free subdomain | Every tenant gets a subdomain, for example `gorkhabutchery.<platform-domain>` | Step 1 |
| Custom domain | Tenant links its own domain (for example `gorkhabutchery.co.nz`) | Step 2 |
| DNS instructions | The system shows the exact CNAME or A record to add at the tenant's domain provider | Step 2 |
| Ownership check | The tenant adds a TXT record; the system verifies it before going live | Step 2 |
| Automatic SSL (HTTPS) | Free certificates are issued and renewed automatically (for example Let's Encrypt) | Step 2 |
| Domain status | Shows Pending DNS, Verified, SSL active, SSL expiring, Error | Step 2 |
| Custom URLs | Page slugs (for example `/menu`, `/order`, `/catering`) and redirects from old URLs | Step 2 |
| Check domain availability | Search if a domain name is free (needs a registrar API) | Later |
| Buy a domain in the platform | Purchase through a registrar API (needs a registrar account and payment) | Later |

Rules:
- A domain can link to only one tenant.
- Only roles with the "Manage websites" permission can add or change domains.
- Domain changes are written to the audit log.

## 2. Website content editing (with AI)

Authorised users can change website text from the backend without code.

| Item | Editable |
|---|---|
| Site title and tagline | Yes |
| Page titles and headings | Yes |
| Page text and sections | Yes |
| Menu and navigation labels | Yes |
| SEO title, meta description, social share text | Yes |
| Images and alt text | Yes |
| Footer, contact details, opening hours | Yes |

AI content generation:
- A "Generate with AI" button sits next to each text field.
- The AI uses the tenant's own AI key (see [Settings and secrets](04-tenant-settings-and-secrets.md)) and the tenant's business details.
- The AI suggests text, for example 3 options. A person picks, edits and publishes it. The AI never publishes on its own.
- If no AI key is set up, the button is hidden and manual editing still works.
- Every change is saved in version history and can be restored.
- AI-generated text is marked as AI-drafted in the history.

## 3. Ticket system (issue reporting)

| Feature | Description |
|---|---|
| Report an issue | A "Report a problem" button on every page, with title, description, screenshot and priority |
| Auto-attached details | Page, browser, time, tenant and user are attached automatically. Secrets are never included. |
| Two support levels | Tenant staff → tenant admin (internal tickets); tenant admin → platform support (platform tickets) |
| Customer tickets | Customers can raise issues through WhatsApp or the website; these go to the tenant's support queue |
| Statuses | New, In progress, Waiting for reply, Resolved, Closed |
| Priority and SLA | Low, Normal, High, Urgent, with target response times |
| Assignment and comments | Assign to a person, internal notes, replies to the reporter |
| Notifications | In-app, email, and optional WhatsApp updates |
| Links | A failed health check or backup can create a ticket automatically |
| Reports | Open tickets, response time, resolution time, common issues |

## 4. Health check button ("Check system")

Each dashboard has a **Check system** button. One click runs the checks for that dashboard and shows the results as green (OK), amber (warning) or red (failed).

| Dashboard | What it checks |
|---|---|
| Super Admin | Database, background workers, queue length, storage, last backups, SSL certificates, error rate, all tenants' integration status |
| Tenant admin | Tenant's database schema, API keys (test connection), WhatsApp webhook, email and SMS, domain and SSL, last backup, scheduled jobs |
| Orders | WhatsApp connection, order queue, stock sync, printer or notifications if used |
| BI | Data freshness (last import, last refresh), scheduled reports |
| Competitor intelligence | Last crawl run, crawl errors, search API key |
| Website | Site loads, domain and SSL, broken links, chatbot status |

Rules:
- Checks are safe. They read and test, and never change data.
- Every check run is saved with its results (history).
- The same checks also run automatically on a schedule, and alert an admin if something fails.
- A red result offers "Create ticket" with the details filled in.

## 5. Backups to Google Drive

| Item | Plan |
|---|---|
| Frequency | Every 6 hours (4 times a day), configurable |
| What is backed up | Full PostgreSQL database (all schemas), plus uploaded files |
| Primary backup | Stored with the hosting provider (for example database snapshots or object storage) |
| Off-site copy | Uploaded to the platform owner's Google Drive |
| Encryption | Each backup is encrypted **before** upload. The encryption key is kept separately, never in Google Drive. |
| Google Drive access | A dedicated Google account or service account with access to one backup folder only |
| Retention | For example: keep 6-hourly backups for 7 days, daily for 30 days, monthly for 12 months (to confirm) |
| Monitoring | Each run is logged (time, size, checksum, status). A failed backup alerts an admin and can create a ticket. |
| Restore tests | Restore a backup to a test server regularly (for example monthly) and record the result |
| Per-tenant export | A tenant admin can download its own data at any time |
| Per-tenant Google Drive | Each business sends backups of its own data to its own Google Drive (see below) |

### Per-tenant Google Drive backups

Decided on 21 October 2026: each business gets backups of its own data in its own Google Drive.

**First-login setup (tenant IT admin)**

1. The first time the tenant's IT admin (or System Admin) logs in, a setup wizard opens.
2. One step asks: "Where should we send your backups?"
3. The admin clicks **Connect Google Drive** and signs in to Google (OAuth). The platform asks only for access to files it creates (Google Drive `drive.file` scope), not the whole Drive.
4. The admin chooses or creates a backup folder name, for example `Anish1989 Backups - Gorkha Butchery`.
5. The admin sets a **backup passphrase**, or lets the system generate one and shows it once to save. It is needed to restore. Without it, the backup cannot be opened.
6. The system runs a test backup and shows "Backup working".
7. The admin can skip this step, but a reminder banner stays on the dashboard until backups are set up.

**What is sent:** that tenant's database schema plus its uploaded files, encrypted with the tenant's passphrase, every 6 hours (setting).

**Status and control (Settings → Backups):** connected Google account, folder, last backup time, size, next run, "Back up now", "Test restore", "Disconnect". A failed upload alerts the IT admin, can create a ticket, and shows in the "Check system" results.

**Rules**
- The platform still keeps its own full backups. The tenant's Drive copy is extra, not a replacement.
- The Google refresh token is stored encrypted in the secret vault, like other keys.
- If the admin disconnects Google Drive or the token stops working, backups to Drive pause and the admin is alerted.
- A Google OAuth app used by the public needs Google's app verification and branding review before launch.

Notes:
- Backups contain customers' personal information, so encryption and access control are required (NZ Privacy Act).
- Google Drive storage is outside New Zealand, so mention this in the privacy policy.
- Google Drive has storage limits. Check the space needed as data grows.
- A backup only counts once a restore from it has been tested.
