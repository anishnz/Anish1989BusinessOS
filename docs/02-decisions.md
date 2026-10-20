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
| D-038 | Login security | Email login per business; Argon2 password hashing; lockout after 5 failures per email per business for 15 minutes; authenticator-app MFA (TOTP) with 10 single-use backup codes, required for staff and admins; read-only login history; password reset links expire after 1 hour | NFR-003 (MFA for privileged accounts), NFR-004 (modern password hashing); protects businesses if a password is stolen | Decided (21 Oct 2026) |
| D-039 | Permissions | Code-defined catalogue of module + action permissions; roles are sets of these; deny by default; checks run on the server for every API call and admin page; Django groups/per-user permissions are not used | Spec sections 4.1–4.4; one clear source of truth that tests can cover | Decided (21 Oct 2026) |
| D-040 | Privilege escalation | You can only grant permissions you hold, cannot change your own roles, and only full admins can grant full access; role editing in the Django admin is superuser-only | Spec 4.3: "IT Admin cannot grant themselves additional privileges" | Decided (21 Oct 2026) |
| D-041 | Audit log | Append-only, SHA-256 hash-chained events per schema, protected by a database trigger against UPDATE/DELETE/TRUNCATE; secrets redacted; login events and changes to users, roles and MFA recorded automatically | NFR-007 (tamper-resistant audit records) | Decided (21 Oct 2026) |
| D-042 | Licences | One licence per business in the public schema: trial/paid dates, grace period (default 7 days), limits; access state worked out from business status and dates; blocked states stop every page and API | FR-005, spec 5.5; one place that decides if a business can work | Decided (21 Oct 2026) |
| D-043 | Modules | Two levels: the platform entitles modules (licence), the business switches entitled modules on or off; core modules always on; industry templates choose starting modules | Spec section 3 (Super Admin enables per tenant; System Admin chooses within limits) | Decided (21 Oct 2026) |
| D-044 | Trial | 30 days, no automatic charge; reactivation restores the earlier status; marking as paid makes the licence active | D-018 and spec section 6 | Decided (21 Oct 2026) |
| D-045 | First System Admin | Created by invitation: the account has no password until the person sets one through an emailed link on their own business site | No passwords are chosen or sent by the platform | Decided (21 Oct 2026) |
| D-046 | Secret vault encryption | AES-256-GCM envelope encryption: a random data key per connection, wrapped by a master key from `VAULT_MASTER_KEYS`; ciphertext bound to `schema:uid`; rotation re-wraps data keys | Spec 4.4 and docs/04 (encrypted per-tenant keys); no extra service (KMS/Vault) needed for the pilot, can be swapped later | Decided (21 Oct 2026) |
| D-047 | Master key location | Kept only in `.env` / server environment, never in the database or backups; created by the start scripts; the owner must back it up | A stolen database backup alone must not reveal keys | Decided (21 Oct 2026) |
| D-048 | Showing saved keys | Never shown again after saving; only the last 4 characters; blank field on edit keeps the saved key | Spec "masked display"; stops shoulder-surfing and leaks through screenshots | Decided (21 Oct 2026) |
| D-049 | Who can change keys | View / configure / manage split: configure can test and rename, only `manage_integrations` can add, replace or remove keys; IT Admin and System Admin have it by default | Least privilege; spec 4.3 IT Admin manages integrations | Decided (21 Oct 2026) |
| D-050 | Outgoing test requests | One read-only request per test, 10-second timeout, no redirects, generic error messages; private-network addresses refused unless `ALLOW_PRIVATE_NETWORK_URLS` | Prevents the platform being used to reach internal services (SSRF) and stops tokens leaking in errors | Decided (21 Oct 2026) |
| D-051 | Card payment providers | Stripe, Windcave and PayPal listed but "coming later"; bank transfer details available now | Pilot businesses take bank transfer / pay on pickup first; card payments need provider accounts and more testing | Decided (21 Oct 2026) |
| D-052 | System email provider | Gmail with a Google app password (2-Step Verification on), saved in the vault; a business's own email connection first, then the platform's Gmail, then `.env` settings | Chosen by the owner on 21 Oct 2026; free and enough for invitations and resets (about 500 emails a day per personal account); marketing email will need a proper service later | Decided (21 Oct 2026) |
| D-053 | Prices and GST | Prices are stored in NZ$ including GST (15%); GST shown as 3/23 of the price; per-product "GST applies" switch | NZ retail prices are shown GST-inclusive; GST rate is a setting for other countries later | Decided (21 Oct 2026) |
| D-054 | Removing products and customers | Archive instead of delete; customers can have their personal data removed ("Removed customer #id") | Old orders and reports must stay correct; NZ Privacy Act 2020 requests can still be met | Decided (21 Oct 2026) |
| D-055 | Personal data in the audit log | Customer name, phone, email, address and notes are never copied into the audit log; only "changed" is recorded and the label is "Customer #id" | The audit log cannot be edited or deleted, so personal data in it could never be removed | Decided (21 Oct 2026) |
| D-056 | Phone numbers | Saved in international E.164 format (+64...) using the `phonenumbers` library; NZ is the default country; one customer per phone number and per email in each business | WhatsApp uses E.164; avoids duplicate customers | Decided (21 Oct 2026) |
| D-057 | Marketing consent | Append-only consent history (who, when, how); consent changes only through one service; CSV and admin changes recorded too | Unsolicited Electronic Messages Act 2007 needs consent before marketing messages | Decided (21 Oct 2026) |
| D-058 | CSV import/export | All-or-nothing imports with a "check only" step and row-numbered errors; exports guard against spreadsheet formulas and are audited; cost price only for editors | Owners will move existing lists in by spreadsheet; avoids half-imported files and CSV injection | Decided (21 Oct 2026) |
| D-059 | Shop Staff role | New default role for counter and kitchen staff: products (view, no cost price), customers (view, add, change, record consent), orders (view, create, change), tickets (view, report); no export, import, archive or delete | Agreed by the owner on 21 Oct 2026; least privilege for the people who take orders | Decided (21 Oct 2026) |
| D-060 | Order rules in one place | All order changes go through one service layer used by the API, the admin and later the WhatsApp AI; prices only from products | The AI must never set prices or skip steps (docs/05) | Decided (21 Oct 2026) |
| D-061 | Price copy on each line | Each order line keeps the product name, unit, price and GST flag of the moment | Later price changes must not change old orders or reports | Decided (21 Oct 2026) |
| D-062 | Order status flow | The states from docs/05 with fixed allowed moves; cancelling needs a reason; weight changes need "final price sent/accepted"; counter staff can record the customer's acceptance | Matches the agreed WhatsApp ordering workflow; customers accept the final price | Decided (21 Oct 2026) |
| D-063 | Order numbers | Per business, starting at #1001, from a locked counter row (no duplicates) | Easy to say on the phone and WhatsApp | Decided (21 Oct 2026) |
| D-064 | Payment in basic orders | Paid/not paid with method (cash, card, bank transfer, other); paid orders must be marked not paid (refund) before cancelling; full invoicing comes with finance in step 3 | Owners need "who has paid" now; refunds must not be forgotten | Decided (21 Oct 2026) |
| D-065 | Deleting orders | Only drafts can be deleted; other orders are cancelled | Complete history for reports, disputes and the accountant | Decided (21 Oct 2026) |
| D-066 | WhatsApp connection | Each business connects its own number through the official WhatsApp Business Platform (Cloud API); Graph API v25.0 (supported until July 2028); app secret required | Official API only (no unofficial WhatsApp Web tools, which risk bans); per-business keys as agreed | Decided (21 Oct 2026) |
| D-067 | Webhook security | Per-business callback URL on the business's own address; HMAC-SHA256 signature with the app secret; phone number ID must match; duplicates ignored; always 200 after a valid signature | Stops fake messages and cross-business mix-ups; Meta resends events | Decided (21 Oct 2026) |
| D-068 | Inbox permissions | The inbox uses the CRM module: view to read, edit to reply/close, assign to assign | Conversations are with customers; no new module or licence change needed | Decided (21 Oct 2026) |
| D-069 | 24-hour rule and templates | Free replies only within 24 hours of the customer's last message; otherwise approved templates; marketing templates only with consent; STOP opts out | WhatsApp policy and the NZ Unsolicited Electronic Messages Act | Decided (21 Oct 2026) |
| D-070 | Messages and privacy | Message text never goes into the audit log; removing a customer's data deletes their messages | Messages are personal data; the audit log cannot be edited | Decided (21 Oct 2026) |
| D-071 | Operations Manager defaults | Default role now also sees products and customers | Needed to pick products and customers in orders; agreed 21 Oct 2026 | Decided (21 Oct 2026) |
| D-072 | Backup codes | 10 one-time codes of 16 characters (XXXX-XXXX-XXXX-XXXX, no look-alike letters), with print and download | Asked by the owner on 21 Oct 2026; easier to read and type, about 79 bits each | Decided (21 Oct 2026) |
| D-073 | Switching MFA off | The Super Admin can switch MFA off for one user with a required reason; shown in red; recorded in both audit logs; "switch on again" and "reset" available. Not recommended for admins | Chosen by the owner on 21 Oct 2026 after the risk was explained | Decided (21 Oct 2026) |
| D-074 | Super Admin and business users | Super Admin can see every business's users and change roles, reset or switch off MFA, lock and unlock; recorded in the business's audit log as the platform administrator | Spec: Super Admin views and changes roles across tenants with an audit trail | Decided (21 Oct 2026) |
| D-075 | Locked-out Super Admin | Recovery is the `reset_mfa` server command (needs server access); a second Super Admin is recommended | No password-only backdoor in the web app | Decided (21 Oct 2026) |
| D-076 | What counts as a sale | Sales = totals of orders completed (picked up) that day, incl. GST; orders = confirmed that day and not cancelled; compared with the same weekday last week | Simple and matches cash in hand for pickup businesses; the same weekday is a fairer comparison than yesterday | Decided (21 Oct 2026) |
| D-077 | Dashboard days | Midnight to midnight in the business's time zone (Pacific/Auckland) | Owners think in local days; UTC days would mix evenings into the next day | Decided (21 Oct 2026) |
| D-078 | Dashboard access | Needs Reports – View; unread chats only for people who can see customers | Sales figures are sensitive; least privilege | Decided (21 Oct 2026) |

## Why schema per tenant?

- Each business's data lives in its own PostgreSQL schema, so a coding mistake is less likely to show one business's data to another.
- Shared platform data (plans, licences, platform billing) lives in the `public` schema.
- Backups, exports and offboarding can be done per tenant.
- Trade-off: database migrations run once per schema, so migrations must be tested well. With many thousands of tenants we may need to review this choice.

## Why a separate React frontend?

- BI needs many interactive charts and drag-and-drop dashboards.
- The same API can later serve the staff mobile app (PWA) and tenant integrations.
- Trade-off: two codebases to maintain (Django and React).
