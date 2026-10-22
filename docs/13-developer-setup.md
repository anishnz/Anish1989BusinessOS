# 13. Developer setup

Last updated: 21 October 2026

How to run Anish1989 Business OS on your own computer (Windows, macOS or Linux).

## Project layout

```
Anish1989BusinessOS/
├── backend/                  Django project
│   ├── config/               settings, URLs, Celery
│   ├── apps/
│   │   ├── tenants/          tenants (businesses) and domains — public schema
│   │   ├── accounts/         custom user model (email login) — every schema
│   │   └── core/             health endpoint and shared code
│   ├── tests/                pytest tests (tenant isolation, health, tenants)
│   ├── requirements/         base.txt (production), dev.txt (development)
│   ├── Dockerfile
│   └── docker-entrypoint.sh
├── docker-compose.yml        PostgreSQL, Redis, web, worker, scheduler
├── .env.example              copy to .env and fill in
└── docs/                     all planning documents
```

## Same versions on every laptop

- The app image is built by GitHub Actions on every push to `main` and published to
  `ghcr.io/anishnz/anish1989businessos-backend` (for Intel/AMD and Apple Silicon/ARM).
- Python packages are locked to exact versions with hashes in `backend/requirements/base.lock` and `dev.lock`.
- PostgreSQL (16) and Redis (7.4) image versions are pinned in `docker-compose.yml`.
- To use one exact build instead of the newest, set `APP_IMAGE_TAG=sha-<commit>` in `.env`.

To change a package version: edit `requirements/base.txt` or `dev.txt`, then run
`pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file base.lock base.txt`
(and the same for `dev.lock`), and commit both files.

## Option A: Docker (recommended)

You need **Docker Desktop** (on Windows, with the WSL 2 backend). No Docker Hub login is needed.

1. Start everything with one command from the project folder:
   - Windows: double-click **`start.cmd`**, or run:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\start.ps1
     ```
   - macOS/Linux:
     ```bash
     ./start.sh
     ```
   The script creates `.env` with random local passwords (first time only), pulls the images,
   starts all services, runs database migrations, and waits until the platform is healthy.
2. Create a platform admin (Super Admin). You type the password yourself:
   ```powershell
   docker compose exec web python manage.py createsuperuser
   ```
3. Create a test business:
   ```powershell
   docker compose exec web python manage.py create_business --name "Gorkha Butchery" --slug gorkhabutchery --industry butchery
   ```
4. Create a login for that business (its users live in its own schema):
   ```powershell
   docker compose exec web python manage.py tenant_command createsuperuser --schema=gorkhabutchery
   ```
5. Open in the browser:
   - Platform admin: http://localhost:8000/admin/
   - Business admin: http://gorkhabutchery.localhost:8000/admin/
   - Health check: http://localhost:8000/health/

`*.localhost` addresses work in Chrome, Edge and Firefox without changing DNS.

Stop with `docker compose down` (data is kept in Docker volumes). `docker compose down -v` deletes all data.

### Development mode (code changes reload automatically)

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Option B: Python on your computer

You need Python 3.13, PostgreSQL 16 and Redis running locally.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install --require-hashes --no-deps -r requirements/dev.lock
```

In `.env`, use `localhost` instead of `db` and `redis` in `DATABASE_URL` and `REDIS_URL`. Then:

```powershell
python manage.py migrate_schemas --shared
python manage.py bootstrap_platform
python manage.py runserver
```

## Running tests

```powershell
cd backend
python -m pytest
```

The tests need PostgreSQL and Redis (Docker: `docker compose up -d db redis`). They create three tenants in a temporary test database and check that:
- every business gets its own schema and users table
- data in one business is invisible to another
- a user of one business cannot log in to another business or the platform
- tenant admins cannot see the tenant registry, and tenants cannot be deleted from the admin
- each host name is routed to the right schema, and unknown hosts get 404
- the health endpoint works and does not leak internal details

GitHub Actions runs the same tests and a Docker build on every push to `main`.

## Login and MFA (task 1.2)

- Email + password login, case-insensitive, per business (users are stored in each schema).
- Passwords are hashed with Argon2 (older hashes upgrade automatically on next login).
- Lockout: 5 failed attempts per email, per business, locks that email for 15 minutes (`LOGIN_LOCKOUT_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS`).
- MFA: staff and admins must use an authenticator app (TOTP) with 10 single-use backup codes. Anyone else who turns MFA on must use it too. Turn the staff requirement off only for local testing with `MFA_REQUIRED_FOR_STAFF=False`.
- A user who already has MFA must verify before adding a new authenticator, so a stolen password alone is not enough.
- Login history: `LoginEvent` (read-only in the admin). Passwords and codes are never stored.
- Password reset by email; links use the business's own address and expire after 1 hour. Set `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` for real email. The default prints emails to the console (`docker compose logs web`).

### Auth API (for the React frontend)

Session cookie + CSRF. Call `GET /api/auth/csrf/` first and send the returned `csrfToken` in the `X-CSRFToken` header on every POST/PATCH/PUT/DELETE. The `csrftoken` cookie is HttpOnly, so scripts cannot read it; the token comes from this endpoint instead. Call it again after logging in or out (Django changes the token then).

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/auth/csrf/` | – | Sets the `csrftoken` cookie and returns `csrfToken` |
| POST | `/api/auth/login/` | `email`, `password` | 400 wrong details, 429 locked out. Response says if MFA is required or needs setup |
| POST | `/api/auth/mfa/verify/` | `token` | 6-digit code or a backup code |
| POST | `/api/auth/mfa/totp/setup/` | – | Returns `otpauth_url`, `secret`, `qr_svg` |
| POST | `/api/auth/mfa/totp/confirm/` | `token` | Turns MFA on and returns 10 backup codes |
| POST | `/api/auth/mfa/backup-codes/` | – | New backup codes (MFA-verified users only) |
| GET | `/api/auth/me/` | – | Current user and MFA state |
| POST | `/api/auth/logout/` | – | 204 |
| POST | `/api/auth/password/reset/` | `email` | Always the same answer |

Until a staff user has passed MFA, every other `/api/...` path returns `403` with `"code": "mfa_required"`.

## Roles, permissions and audit log (task 1.3)

- Permission catalogue: `backend/apps/rbac/catalogue.py` (module + action, using the 17 actions from the spec). Business modules and platform modules are separate.
- Default roles: `backend/apps/rbac/defaults.py`. Created automatically in every new or migrated schema, and by `python manage.py sync_roles`. Admins' later changes are never overwritten.
- Checks: `apps.rbac.policy.check(user, "orders.approve")` → deny unless the user is active, the business is active or in trial, the module is enabled (task 1.4), and a role grants it. Superusers have everything in their own schema.
- In API views use `permission_classes = [ModulePermission]` with `permission_module = "orders"` (GET→view, POST→create, PUT/PATCH→edit, DELETE→delete) or `requires("finance.approve")`. Denied requests are audited.
- Django admin permissions are translated to role permissions (`apps/rbac/backends.py`). Django groups and per-user permissions are ignored.
- Escalation rules (`apps/rbac/services.py`): grant only what you have; never change your own roles; only full admins give full access; default roles cannot be deleted.
- Audit log: `apps.audit.services.audit("action.name", target=obj, changes={...})`. Hash-chained, append-only, and protected by a database trigger in every schema. Secrets are redacted. Changes to users, roles, role permissions, role assignments and MFA devices are recorded automatically (`apps/audit/tracking.py`).
- Check the audit chain: `python manage.py verify_audit_chain` (all schemas) or `--schema=<slug>`.

### Roles API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/rbac/me/permissions/` | signed in |
| GET | `/api/rbac/catalogue/` | `roles.view` |
| GET, POST | `/api/rbac/roles/` | `roles.view`, `roles.create` |
| GET, DELETE | `/api/rbac/roles/<id>/` | `roles.view`, `roles.delete` |
| PUT | `/api/rbac/roles/<id>/permissions/` | `roles.manage_permissions` |
| GET, POST | `/api/rbac/users/<id>/roles/` | `roles.view`, `roles.assign` |
| DELETE | `/api/rbac/users/<id>/roles/<role_id>/` | `roles.assign` |

## Licences and modules (task 1.4)

- App `apps.licensing` (public schema only): `Licence` (one per business: trial/paid dates, grace days, limits) and `TenantModule` (entitled by the platform, enabled by the business).
- New businesses (`create_tenant`) get a 30-day trial (`LICENCE_TRIAL_DAYS`) and their industry's modules (`apps/licensing/templates_catalogue.py`). Existing businesses get one with `python manage.py sync_licences` (also run on container start).
- Access state: trial, active, grace, expired, suspended, cancelled. `LicenceMiddleware` blocks every page and API (except `/health/` and static files) unless the state is trial, active or grace. In grace, responses carry `X-Account-Status: grace`.
- The permission policy also checks the licence and whether the module is switched on (core modules: users, roles, settings, integrations, audit).
- Active-user limit is enforced whenever a user is created or reactivated (`LimitReached`).
- Super Admin: create a business (with an optional System Admin invitation), edit licence and modules, suspend (reason required), reactivate, extend trial, mark paid. All audited. Command: `python manage.py invite_admin --schema <slug> --email <email>`.

### Business licence API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/tenant/licence/` | `settings.view` |
| GET | `/api/tenant/modules/` | `settings.view` |
| PATCH | `/api/tenant/modules/<code>/` `{"enabled": true}` | `settings.configure` |

These return 404 on the platform site.

## Secret vault and integrations (task 1.5)

- App `apps.vault` (in both shared and tenant apps): one `Connection` table per schema. The platform site uses it for platform-wide keys (permission module `platform_settings`); each business uses its own (module `integrations`).
- **Encryption** (`apps/vault/crypto.py`): AES-256-GCM envelope encryption. Each connection's secrets are one JSON blob encrypted with a fresh random data key; the data key is encrypted ("wrapped") with the master key. Both use the associated data `"<schema>:<connection uid>"`, so a ciphertext copied to another row or another business cannot be opened.
- **Master keys**: `VAULT_MASTER_KEYS="id:base64,..."` (32-byte keys, newest first). The start scripts create one. With `DEBUG=True` and no key, a development key is derived from `DJANGO_SECRET_KEY`; with `DEBUG=False` and no key, the app refuses to save or open secrets (`ImproperlyConfigured`).
- **Rotation**: put the new key first, restart, run `python manage.py rotate_vault_key` (re-wraps every data key in every schema, audited), then remove the old key.
- **What is stored**: the encrypted blob plus masked hints (`••••` + last 4 characters, only for values of 8+ characters). Secrets are never returned by the API or pages, never put back into form fields, and never written to the audit log (only field names).
- **Providers** (`apps/vault/providers.py`): each provider declares its config fields, secret fields and a `test()` that makes one small read-only request (10-second timeout, no redirects). Error messages are generic, so tokens inside URLs (Telegram) never leak. Add a provider by adding a `Provider(...)` entry; set `available=False` for ones not built yet.
- **Private network guard** (`apps/vault/netguard.py`): user-supplied URLs (Ollama `base_url`, SMTP host) must be http/https and must not resolve to private, loopback, link-local or reserved addresses. Set `ALLOW_PRIVATE_NETWORK_URLS=True` only on a laptop for a local Ollama. Known limit: DNS can change between the check and the request (DNS rebinding); redirects are off, which closes the common case.
- **Backup connections**: `services.active_connection(category)` returns the main connection, or the backup when the main one is disabled or failed. The AI and messaging adapters will use this.
- Pages: `/settings/integrations/` (staff, MFA required). The Django admin entry redirects there; add/change/delete in the admin are switched off.

### Integrations API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/integrations/providers/` | `integrations.view` |
| GET, POST | `/api/integrations/connections/` | `integrations.view`, `integrations.manage_integrations` |
| GET | `/api/integrations/connections/<id>/` | `integrations.view` |
| PATCH | `/api/integrations/connections/<id>/` | `integrations.configure` (+ `manage_integrations` when `secrets` is sent) |
| DELETE | `/api/integrations/connections/<id>/` | `integrations.manage_integrations` |
| POST | `/api/integrations/connections/<id>/test/` | `integrations.configure` |
| POST | `/api/integrations/connections/<id>/disable/` `{"disabled": true}` | `integrations.configure` |

Body for POST: `{"provider": "openai", "label": "Main AI", "config": {"model": "gpt-4o-mini"}, "secrets": {"api_key": "..."}, "is_backup": false}`. In PATCH, a blank secret keeps the saved value. On the platform site the module is `platform_settings`.

## Email through Gmail (task 1.6)

- `EMAIL_BACKEND` defaults to `apps.vault.mail.VaultEmailBackend`. For each email it uses, in order: the current business's own email connection (provider `gmail` or `smtp`, not disabled or failed); the platform's email connection (public schema), with the sender name "<Business> via <platform sender>"; then `EMAIL_FALLBACK_BACKEND` (console when `DEBUG=True`, otherwise Django's SMTP backend with the `EMAIL_HOST*` settings).
- Gmail provider: `smtp.gmail.com:587` with STARTTLS, the Gmail address as username and a Google **app password** (needs 2-Step Verification; spaces are removed). The From address is always the connected account; a different `from_email` becomes Reply-To.
- Invitation emails that fail raise a clear `ValidationError` (audited as `tenant.admin_invite_failed`); the account is already created, so "Invite System Admin" can be clicked again.
- Check the real connection: `python manage.py send_test_email --to you@example.com [--schema <slug>]`.

## Products and customers (task 1.6)

- Business-only apps (in `TENANT_APPS` only; no tables in the public schema): `apps.catalog` (module `products`) and `apps.customers` (module `crm`). Their URLs are in `config/urls.py` (business sites only), and `BusinessOnlyAdminMixin` hides them in the platform admin.
- **Products**: `Category`, `Product` (unit kg/each/pack, price NZ$ incl. GST, optional cost price, `gst_applies`, `min_quantity`, `quantity_step`, `search_terms`, `is_available`, `is_archived`). GST included = price × 3/23 at 15% (`GST_RATE`). Products are archived, never deleted. Cost price is only returned to users with `products.edit`.
- **Customers**: `Customer` (phone saved as E.164 using `phonenumbers`, default region `PHONE_DEFAULT_REGION=NZ`; unique phone and unique email per business), `ConsentRecord` (append-only marketing consent history). Marketing consent changes only through `services.set_marketing_consent` (API `/consent/`, admin checkbox, CSV import).
- **Privacy**: customer name, phone, email, address and notes are tracked with `track(..., personal=...)`, so the audit log records only that they changed; the audit label is "Customer #id". `services.anonymise` removes personal data (and the admin history label) but keeps the record for orders and reports.
- **CSV** (`apps/core/csvtools.py`): UTF-8 (with or without BOM), 2 MB / 5,000 rows, unknown columns refused, all-or-nothing with row-numbered errors, "check only" mode. Exports prefix cells starting with `= + - @` with `'` (CSV injection) and the import removes it again. Exports are audited.

### Products API

| Method | Path | Permission |
|---|---|---|
| GET, POST | `/api/products/` (filters `q`, `category`, `available`, `archived`, `unit`; 50 per page) | `products.view`, `products.create` |
| GET, PATCH, DELETE | `/api/products/<id>/` (DELETE archives) | `products.view`, `products.edit`, `products.delete` |
| POST | `/api/products/<id>/restore/` | `products.edit` |
| GET, POST | `/api/products/categories/` | `products.view`, `products.create` |
| GET, PATCH, DELETE | `/api/products/categories/<id>/` | `products.view`, `products.edit`, `products.delete` |
| POST | `/api/products/import/` (multipart `file`, `dry_run`) | `products.import` |
| GET | `/api/products/export/` | `products.export` |
| GET, POST | `/api/products/<id>/stock/` (GET: last 50 changes; POST `{"reason": "received\|counted\|waste\|correction", "quantity": "5", "note": ""}`) | `products.view`, `products.edit` |

The product list also takes `stock=low` (counted products that are low, out of stock or below zero).

### Customers API

| Method | Path | Permission |
|---|---|---|
| GET, POST | `/api/customers/` (filters `q`, `tag`, `consent`, `archived`) | `crm.view`, `crm.create` |
| GET, PATCH, DELETE | `/api/customers/<id>/` (DELETE archives; detail includes consent history) | `crm.view`, `crm.edit`, `crm.delete` |
| POST | `/api/customers/<id>/restore/` | `crm.edit` |
| POST | `/api/customers/<id>/anonymise/` | `crm.delete` |
| POST | `/api/customers/<id>/consent/` `{"given": true, "channel": "all", "note": ""}` | `crm.edit` |
| POST | `/api/customers/import/` | `crm.import` |
| GET | `/api/customers/export/` | `crm.export` |

## Orders (task 1.7)

- Business-only app `apps.orders` (module `orders`): `Order` (number from #1001 per business via `OrderCounter` with a row lock), `OrderLine` (copy of product name, unit, price and GST flag; ordered `quantity` and `final_quantity` for real weight), `OrderEvent` (status history).
- All changes go through `apps/orders/services.py` (API, admin and later the WhatsApp AI use the same rules):
  - prices come only from products; request prices are ignored;
  - amounts must be >= `min_quantity` and go up in `quantity_step` (max 3 decimals);
  - unavailable/archived products and removed customers are refused;
  - lines change only in `draft` / `awaiting_confirmation` (a change while awaiting sends it back to `draft`);
  - status moves: draft → awaiting_confirmation | confirmed; awaiting → confirmed | draft | expired; confirmed → preparing; preparing → final_price_sent | ready; final_price_sent → final_price_accepted | preparing; final_price_accepted → ready; ready → completed; cancel (customer/shop, reason required) from any open status;
  - `ready` needs every kg line weighed, and `final_price_sent`/`accepted` when the weighed total differs from the estimate;
  - paid orders cannot be cancelled until marked not paid; only confirmed orders can be paid;
  - only drafts can be deleted.
- Money: line total = unit price × (real weight or ordered amount), rounded half-up to cents; GST included = 3/23 of each GST line total.
- Audit: `orders.create`, `orders.status`, `orders.lines_changed`, `orders.weights`, `orders.paid`/`unpaid`, `orders.delete_draft`, `orders.export`; the order's `notes` are personal data (not copied into the audit log).
- `python manage.py expire_orders --minutes 60` expires unconfirmed orders in every business (to be scheduled with tenant-aware Celery tasks).

### Orders API

| Method | Path | Permission |
|---|---|---|
| GET, POST | `/api/orders/` (filters `status`, `open`, `customer`, `date=YYYY-MM-DD` local, `q=#number` or customer name) | `orders.view`, `orders.create` |
| GET, PATCH, DELETE | `/api/orders/<id>/` (PATCH: `customer`, `notes`, `channel`, `lines`, `fulfilment`, `due_at`, `delivery_address`, `delivery_suburb`, `delivery_postcode`, `delivery_area`; DELETE drafts only) | `orders.view`, `orders.edit`, `orders.delete` |
| POST | `/api/orders/<id>/status/` `{"to": "confirmed", "note": ""}` | `orders.edit` |
| POST | `/api/orders/<id>/weights/` `{"weights": {"<line id>": "1.08"}}` | `orders.edit` |
| POST | `/api/orders/<id>/payment/` `{"paid": true, "method": "cash"}` | `orders.edit` |
| GET | `/api/orders/export/` (`date_from`, `date_to`) | `orders.export` |
| GET | `/api/orders/fulfilment/` (settings and active delivery areas) | `orders.view` |
| GET | `/api/orders/slots/?kind=pickup\|delivery&date=YYYY-MM-DD&order=<id>` (that day's slots with `taken`, `capacity`, `full`, `past`, `too_soon`; `order` is not counted) | `orders.view` |
| GET | `/api/orders/delivery-areas/find/?postcode=&suburb=&address=` | `orders.view` |

Create body: `{"customer": 3, "channel": "counter", "notes": "", "fulfilment": "delivery", "due_at": "2026-10-23T16:00:00+13:00", "delivery_address": "1 Queen Street", "delivery_postcode": "1010", "lines": [{"product": 5, "quantity": "1.5", "note": ""}]}`. The delivery fee always comes from the area. Responses include `next_statuses`, `status_label` ("Ready for pickup" / "Ready for delivery"), `due_text` and, on one order, `warnings` (slot, area and minimum-order rules the order breaks).

## Pickup and delivery (task 2.1)

- Business-only app `apps.fulfilment` (permissions: module `orders`; changing needs `orders.configure`, D-124): `FulfilmentSettings` (one row: pickup/delivery on, slot lengths, orders per slot, preparation time, days ahead, GST in fees), `OpeningHours` (kind, weekday, from, until; periods must not overlap), `ClosedDay`, `DeliveryArea` (postcodes, suburbs, fee, minimum order, free from, active; a postcode or suburb in one active area only).
- `apps/fulfilment/services.py`: `slots(kind, day, days)` builds slots from the opening hours in the business time zone (times that do not exist when the clocks go forward are skipped) and counts orders with `due_at` in each slot whose status is "awaiting confirmation" or later (not cancelled or expired, D-120); `bookable_slots()` (after the preparation time, within the days ahead, not full); `time_problems()`; `find_area()` (postcode first, then suburb; "Mt" = "Mount"); `delivery_fee()`; `required_problems()` (a delivery needs address, area and time) and `rule_problems()` (switched off, inactive area, minimum order, slot rules).
- Orders: `fulfilment`, `due_at` (renamed from `pickup_at`, D-125), `due_until` (end of the slot, set by the server), `delivery_address/suburb/postcode`, `delivery_area`, `delivery_fee` and `delivery_fee_gst` (copied when the products, pickup or delivery, or the area change; weights never change them). Totals include the fee.
- Status `out_for_delivery`: delivery orders go ready → out_for_delivery → completed; out_for_delivery → ready needs a note (D-123). `change_status(..., strict=True)` and `update_order(..., strict=True)` apply every slot and area rule (for the WhatsApp AI and website); staff calls only need the delivery must-haves, and `warnings(order)` lists the rest (D-121).
- Migration `orders.0003` renames the field, adds the columns, and gives `orders.configure` to roles that had every other Orders permission.
- Check system: "Pickup and delivery" warns when customers cannot choose a time (no hours, no free slots, no delivery areas, both switched off).

## Stock (task 2.2)

- `Product.track_stock` ("Count stock", D-130), `stock_quantity` (not editable; changes only through `apps/catalog/stock.py`) and `low_stock_level` ("Warn at"). `StockMovement` (product, change, quantity after, reason `order|weight|cancelled|received|counted|waste|correction`, order id and number, note, who, when) cannot be changed or deleted (save with a pk, `delete()`, `QuerySet.update()` and `.delete()` raise `PermissionError`; the product is `PROTECT`ed, so products with history are archived).
- `stock.adjust()` (changes by hand, D-133): waste and correction need a note; counted cannot be below zero; at most 3 decimal places. Audit `products.stock_adjusted`.
- Orders (D-131): `change_status(..., CONFIRMED)` calls `take_for_order()` and sets `Order.stock_taken`; `set_weights()` calls `weight_changed()` with the amounts counted before; cancelling calls `give_back()` (the real weight when entered). Orders confirmed before this task have `stock_taken = False`, so nothing is given back for them. Products are locked with `select_for_update()` in id order.
- Not enough stock (D-132): `booking_problems(strict=True)` adds `shortages()` (customers and the AI cannot confirm); staff can confirm and `warnings()` lists the shortage until the order is confirmed. A confirmed order is not checked again (its stock is already taken).
- `state()`: `not_counted`, `below_zero`, `out` (less than the smallest amount), `low` (at or below "Warn at"), `ok`. `low_stock()` feeds the dashboard's `low_stock` list (D-134).
- Admin: "In stock" column and "stock" filter in the product list, page `/admin/catalog/product/<id>/stock/` (history for Products – View, form for Products – Edit). CSV columns `count_stock`, `warn_at`, `stock` (a "Counted" change).
- Migrations: `catalog.0003_stock`, `orders.0004_stock_taken`. Tests: `tests/test_stock.py`.

## WhatsApp messages about orders (task 2.3)

- `apps/orders/notify.py`, models `CustomerMessageSettings` (one row: which messages, template names, template language) and `OrderMessage` (order, kind, status `queued|sent|failed|skipped`, note, `via` message/template, link to the inbox `Message`, question `token`, `is_open`, `asked_total`, `answer`, times). No message text is stored there; it is made when sent and kept only in the inbox (deleted with the customer's personal data).
- `services._move()` calls `notify.after_move()`: it closes the order's open questions and queues the message for the new status (D-135) inside the same transaction; `transaction.on_commit` starts the Celery task `orders.send_message` (`apps/orders/tasks.py`). `deliver()` locks the row and only sends a queued message (safe to run twice); it skips a question whose order has moved on.
- Inside the 24-hour window: `inbox.send_buttons()` (interactive reply buttons, ids `order:<id>:<16 hex token>:yes|no`) or `inbox.send_text()`. Outside: `inbox.send_template()` with the body parameters and quick-reply button payloads (D-136). Template parameters are cleaned (no new lines, tabs or long spaces; empty = "-").
- Answers: `inbox.services.message_received` (a Django signal sent after an incoming message is stored, with `reply_id` from `interactive.button_reply.id` or `button.payload`) → `notify.on_message_received()` (never raises; own savepoint) → `apply_answer()` (D-137, D-139). "Yes" to confirm uses `change_status(..., strict=True)`; when a rule stops it the order goes back to Draft. Short replies to the customer are `OrderMessage` kind `reply`. `answer_warning()` adds "Customer said No… Call the customer." to `warnings()`.
- API: `GET /api/orders/<id>/` returns `messages` (`label`, `result` such as "Read · answered Yes"). Admin: messages inline on the order page; settings page `/admin/orders/customermessagesettings/` (Orders – Configure) with the template texts to create in Meta. Check system: `order_messages` (queued > 10 minutes = failed; not sent in 24 hours = warning).
- Test data: made-up `OrderMessage` rows and inbox messages, never sent (test businesses never connect WhatsApp).
- Migration `orders.0005_customer_messages`. Tests: `tests/test_order_messages.py` (a fake Graph API; `send_now` runs the worker task at once).

## AI assistant on WhatsApp (task 2.4)

- Business-only app `apps.ai` (module `ai`; settings need `ai.configure`, the log `ai.view`; the chat API uses `crm`). Models: `AISettings` (one row: on/off, connection, monthly NZ$ limit, US$→NZ$ rate, price overrides, answers per chat per day, extra instructions), `AIChat` (per conversation: the draft order, hand-over reason and times), `AIRun` (the AI log: provider, model, tokens, estimated cost, tools, steps, result, note). `inbox.Message.bot` marks AI messages.
- `apps/ai/providers.py`: `chat(provider, key, model, system, turns, tools)` for OpenAI (Chat Completions), Anthropic (Messages, `anthropic-version: 2023-06-01`) and Gemini (`v1beta generateContent`, schema types in capitals). Each assistant reply keeps the provider's own message (`raw`) and sends it back unchanged in the same run (Gemini thought signatures). Fixed URLs, 45 s timeout, no redirects; `AIError` messages never contain the key. `DEFAULT_MODELS` and `PRICES` (US$ per 1M tokens) checked 22 Oct 2026; unknown models use a high guess.
- `apps/ai/tools.py`: `search_products`, `shop_info`, `available_times`, `check_delivery_address`, `set_order` (create/update the chat's draft through `orders.services`, channel `whatsapp`, returns `warnings()`), `send_for_confirmation` (`change_status(..., AWAITING, strict=True)`; the Yes/No summary of task 2.3 follows), `cancel_draft`, `hand_over`. Each tool runs in its own transaction and returns `{"error": ...}` on a `ValidationError`.
- `apps/ai/agent.py`: `on_message_received` (connected to `inbox.services.message_received` after the orders app, so Yes/No answers — `message.answered_question` — are skipped) queues Celery `ai.answer` 3 s later on commit. `answer()`: newer message → skip; per-chat lock in the cache (busy → the task retries every 5 s, up to 12 times); quiet when staff handle the chat (`staff_handling`: handed over, assigned, staff reply in 12 h after `resumed_at`); hand-over for media, the monthly limit and the daily limit; then up to 6 rounds with the last 24 h of the chat (30 messages, starting with the customer). The reply is sent with `inbox.send_text(..., bot=True)`; `AIRun` is written with the cost (`cost_of`). `forget_customer` clears steps when a customer is anonymised.
- API: `GET/POST /api/ai/chats/<conversation id>/` (`{"answer": true|false}`). Admin: settings (status line, this month's cost) and a read-only AI log. Check system: `ai`.
- Staff app: `Thread.tsx` shows the AI bar ("I will answer" / "Let the AI answer again") and marks AI messages.
- Tests: `tests/test_ai.py` (a scripted fake AI for the agent; faked HTTP for the three adapters). Migrations: `ai.0001_initial`, `inbox.0003_message_bot`.

## Quick reorder and hand-over (task 2.5)

- `orders.services.reorder(source, actor=, channel=)` → `(draft, left_out)`; `REORDER_FROM` lists the statuses that count as placed orders. API `POST /api/orders/<id>/reorder/` (`orders.create`, 201 with `left_out`). The customer list adds `last_order` (`{"id", "number"}`, a subquery).
- AI tools `past_orders` (last 3 placed orders of the chat's customer) and `reorder` (only this customer's orders; refuses while a draft is open in the chat).
- `ai.agent.waiting_chats()`: handed over, open, not assigned, no staff reply since `handed_over_at`. `GET /api/ai/waiting/` (`crm.view`); the dashboard adds `waiting_chats` when the user can see customers. `hand_over()` without an actor queues Celery `ai.handover_email` (recipients: active staff with `crm.assign`; `AISettings.email_on_handover`). `POST /api/ai/chats/<id>/ {"answer": false}` assigns the chat to the user.
- Staff app: `useWaiting` (polls every 30 s) for the menu badge, the Inbox "Needs staff" view (`?show=needs_staff`), the dashboard tile, "Order again" on `OrderDetail` and `Customers`.
- Tests: `tests/test_reorder_handover.py`. Migration `ai.0002_email_on_handover`.

## Live order board (task 2.6)

- `orders.board.board(tomorrow=False, now=None)`: confirmed, not finished orders (`ON_BOARD`) due before the end of today (or tomorrow), plus orders without a time, in the four `COLUMNS`. Late first, then by time, no time last. `late` = `due_until or due_at` is before `now`.
- `orders.board.next_step(order)`: `{"to", "label"}` for the one forward move the board offers, or `{"note"}` (weights to enter, waiting for the customer). A test follows the button from Confirmed to Completed to prove the normal rules accept every step.
- A card has `customer` as a short name (`short_name()`), and `suburb` only for delivery; never the street address or phone (D-153).
- API `GET /api/orders/board/` (`orders.view`, `?tomorrow=1`). Moving uses the normal `POST /api/orders/<id>/status/` (`orders.edit`).
- Staff app: `pages/Board.tsx` (route `/board`, menu item **Board**), polls every 10 s; `board.ts` has the pure helpers (`newOrders` for the chime, `needsSecondTap` for unpaid orders, remembered choices) and the WebAudio chime. TV mode is a fixed full-screen layer (`.board-tv`) and asks the browser for full screen.
- Test data: `demo.services._board_today()` moves four open orders to today (two late).
- Tests: `tests/test_board.py`, `frontend/src/test/board.test.ts`. The screenshot tool has a new step `{"check": selector}`.

## Test data, Log in as and safer deleting (task 1.18)

- `apps.demo` (platform only, no tables): `data.py` (the six test businesses, Nepali names, products, conversations, tickets), `services.install(only=...)` / `remove()` (lock in the cache, progress in `demo:progress`), Celery tasks `demo.install` / `demo.remove`, commands `install_test_data [--only test_butchery]` and `remove_test_data [--yes]`, page `/platform/test-data/` (Super Admin only).
- `Tenant.is_test` marks test businesses; only those are removed (`tenant.delete(force_drop=True)` after `SET CONSTRAINTS ALL IMMEDIATE`). `DEMO_PASSWORD` (at least 8 characters) comes from `.env`; empty = install refused.
- Test users: one per default role, `roleas<slug without _>@anish1989.com.np`, `mfa_exempt` with reason "Test account"; platform test users for the non-full-access platform roles keep two-step verification.
- `apps/accounts/login_as.py`: POST `/platform/login-as/<schema>/<user id>/` (Super Admin = superuser or full-access role; reason required unless `is_test`) signs `{schema, user, by, nonce, reason, back}` (salt `anish1989.login-as`, 60 s, nonce single-use in the public cache); business GET `/login-as/?token=` logs the user in and stores `session["login_as"]` (`by`, `until` = 60 min, `back`); `LoginAsMiddleware` ends it after the time; `StaffMFAMiddleware` does not ask two-step verification while it is set; POST `/login-as/stop/` (JSON when asked) logs out and returns to the platform. `/api/auth/me/` returns `login_as`. Audit: `security.login_as` (platform), `security.login_as_started` / `_ended` (business, as the platform administrator).
- `apps/core/deleteguard.py`: `issue()` (sum of two numbers 2 to 9, token in the session, at most 20 open), `check()` (answer, at least 5 s, at most 15 min, single use), `require()` for views with their own Remove buttons (renders `core/confirm_delete.html`). `DeleteGuardMiddleware` checks the admin's delete pages (`/admin/<app>/<model>/<id>/delete/` and "delete_selected") and sends the person back with "Not deleted: ..." when the check fails. Templates `admin/delete_confirmation.html` and `admin/delete_selected_confirmation.html` add `{% delete_guard %}`. Tests use `tests.conftest.pass_delete_check()`.

## WhatsApp and the inbox (task 1.8)

- Business-only app `apps.inbox` (permissions: module `crm`): `Conversation` (one per channel + contact id, linked to a `Customer`), `Message` (direction, kind, text, media id, provider message id unique, status), `WebhookDelivery` (log without message content).
- Webhook `/webhooks/whatsapp/` (business sites only, CSRF-exempt, in `apps/inbox/whatsapp.py`):
  - GET: answers `hub.challenge` when `hub.mode=subscribe` and `hub.verify_token` equals the connection's `webhook_verify_token` (created automatically).
  - POST: refuses unless `X-Hub-Signature-256` is HMAC-SHA256(body, app secret) (constant-time compare); ignores items whose `metadata.phone_number_id` is not the business's own; stores messages once (provider id unique); applies statuses forward only (sent < delivered < read; failed always). Always answers 200 after a valid signature so Meta does not retry.
- Incoming messages create or link the customer by E.164 phone; text `STOP` (and similar) records a consent withdrawal (`source=stop`, `channel=whatsapp`).
- Sending (`apps/inbox/services.py`): `send_text` only within 24 hours of the customer's last message; `send_template` (name `[a-z0-9_]`, language `en` / `en_US`, body parameters) any time, but `category=marketing` needs marketing consent; Graph API `v25.0` by default (`GRAPH_API_VERSION`); 10-second timeout, no redirects; errors are generic and never include the token. Sends are synchronous for now (one HTTP call); move to Celery when volume grows.
- WhatsApp connection: `app_secret` is now required; `phone_number_id` / `business_account_id` must be digits and `graph_api_version` must look like `v25.0`, because they are part of request URLs.
- Privacy: message text is never written to the audit log (only `inbox.send` with kind/template/ok, `inbox.assign`, `inbox.close`); removing a customer's personal data deletes their messages (`customer_anonymised` signal).
- Testing without Meta: `python manage.py whatsapp_simulate --schema <slug> --from "021 123 4567" --text "..."` signs a payload with the saved app secret and posts it to the real webhook.

### Inbox API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/inbox/conversations/` (filters `status`, `mine`, `unread`, `q`) | `crm.view` |
| GET | `/api/inbox/conversations/<id>/` (latest 200 messages, `can_reply_freely`) | `crm.view` |
| POST | `/api/inbox/conversations/<id>/read/` | `crm.view` |
| POST | `/api/inbox/conversations/<id>/reply/` `{"text": "..."}` | `crm.edit` |
| POST | `/api/inbox/conversations/<id>/template/` `{"name", "language", "params": [], "category"}` | `crm.edit` |
| POST | `/api/inbox/conversations/<id>/assign/` `{"user": id or null}` | `crm.assign` |
| POST | `/api/inbox/conversations/<id>/close/` `{"closed": true}` | `crm.edit` |
| POST | `/api/inbox/start/` `{"customer": id, "name", "language", "params", "category"}` | `crm.edit` |

## MFA tools and Super Admin user pages

- Backup codes: 10 codes of 16 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, shown as `XXXX-XXXX-XXXX-XXXX`; typed with or without dashes/spaces, any case (`security.normalise_code`). Old 8-character codes still work.
- `/account/mfa/` (all sites): status; new backup codes and new authenticator (QR) both need the password (normal 5-try lockout); the old authenticator is removed only after the new one is confirmed.
- `User.mfa_exempt` (+ reason, by, at): set by `security.set_mfa_switched_off` (reason required, devices removed); `mfa_required` is False for exempt users. `security.reset_mfa` removes devices and clears the exemption. Both write a LoginEvent and an audit event.
- `python manage.py reset_mfa --email <email> [--schema <slug>]` for locked-out accounts (server access needed).
- Platform pages (`config/urls_public.py`, `apps/accounts/platform_pages.py`): `/platform/people/`, `/platform/people/<schema>/`, `/platform/people/<schema>/<user id>/`, wrapped in `admin.site.admin_view` (staff + MFA). Permissions: `tenants.view` / `tenants.administer` for business users; `platform_users.view` / `platform_users.edit` / `platform_roles.assign` for platform users. No self-lock, no own-role change, last active Super Admin cannot be locked or lose full access.
- Changes inside a business run in `schema_context(schema)` and `audit.services.platform_actor(email)`, so the business's audit log records `actor_type=platform` with the Super Admin's email and no user id (platform user ids mean nothing in a business schema). A `platform.user_changed` event is also written to the platform log.
- Bug fix: links from business-only tables to users use `apps.core.business.SET_NULL_IN_BUSINESS` (lazy), so deleting a platform user no longer touches business tables that do not exist in the public schema.
- `backend/templates/admin/base_site.html` adds the "Two-step verification" and (platform) "Businesses and users" links.

## Dashboard (task 1.9)

- App `apps.reports` (module `reports`, no tables). `apps/reports/dashboard.py` `summary(day)` returns: sales (completed orders by `completed_at`: total, GST, count, average, unpaid) with the change against the same weekday last week; orders confirmed (by `confirmed_at`, not cancelled/expired); sales per day for 7 days; top 5 products by line totals of completed orders in those 7 days; counts of open orders per status; pickups and deliveries due that day; unread open conversations (if the user has `crm.view`). Pickups and deliveries due that day count booked orders (not drafts) by `due_at`.
- Days are midnight to midnight in `TIME_ZONE` (Pacific/Auckland), including `TruncDate(..., tzinfo=...)`.
- API `GET /api/reports/dashboard/?date=YYYY-MM-DD` (`reports.view`); money values are exact strings.
- Page `/dashboard/` (business sites, `admin.site.admin_view`, `reports.view`): stat tiles, an inline SVG column chart (single series `#2a78d6` light / `#3987e5` dark, validated with the dataviz palette checker; per-bar tooltip on hover/focus; table view), top-product bars, attention list linking to filtered orders. Header link "Dashboard" on business sites.

## Security sweep tests (task 1.10)

`tests/test_security_sweep.py` walks **every URL** of the business sites (`config.urls`) and the platform site (`config.urls_public`), so new pages are checked without writing new tests:

| Sweep | What it proves |
|---|---|
| Not logged in | Every page except the public list (`PUBLIC_ROUTES`) answers 401/403/404/405 or redirects to login, for GET and POST |
| Logged in, no role | Every API answers 403/405 and every page refuses (deny by default); only "about me" routes (`SELF_ROUTES`) answer |
| Staff without roles | Every admin list page is refused, and the admin menu is empty |
| MFA not finished | Every API answers 403 `mfa_required`, every page redirects to `/account/mfa/` |
| Business B vs A | A full System Admin of B opens every API (with every id of A's records) and every admin list and change page: A's marker text never appears; searches find nothing |
| Platform | Platform APIs show no business data; every platform admin page opens without crashing, and business-only admin pages are refused |
| Module off | Every API and admin page of a switched-off module is refused, using real records |
| Suspended | Every page except `/health/` is blocked, for staff and anonymous visitors |
| CSRF / cookies | POST without the CSRF token is refused; a session cookie from one business does not work on another; cookie domains are host-only |
| Production checks | `check --deploy` passes (CI) |

When adding a page that anyone may open, add it to `PUBLIC_ROUTES` with a comment saying how it protects itself. The sweeps were checked by switching protections off one at a time (each one makes a sweep fail).

Bugs the sweeps found and fixed: `GET /api/rbac/users/<id>/roles/<role_id>/` crashed (now a delete-only view); a view-only role page in the admin crashed; the platform's tenant admin page crashed on business sites before refusing; the CSRF token could not be read by the React app.

## Staff app, React (task 1.11)

The staff screens are a React single-page app in `frontend/`: Vite 8, React 19, React Router 7, TypeScript, with tests in Vitest. Django serves it on every business site at **`/app/`**, on the same address as the API.

| Piece | Where |
|---|---|
| Source | `frontend/src/` (pages, components, `api.ts`, `auth.tsx`, `nav.ts`, `styles.css`) |
| Built files | `frontend/dist/` (not in git). `FRONTEND_DIST` setting; in Docker `/opt/frontend-dist` |
| Page | `apps/core/spa.py`: `/app/` and `/app/<anything>` return `index.html` with a strict CSP; 503 page if not built; GET only; not on the platform site |
| Assets | collected under `/static/app/` (`STATICFILES_DIRS`), so WhiteNoise/collectstatic serve them |

How it talks to Django:

- Session login, same origin, no CORS and no tokens in browser storage.
- `GET /api/auth/csrf/` returns `csrfToken` (the cookie is HttpOnly) and `authenticated` (so the app skips `/api/auth/me/` when nobody is logged in). The app sends `X-CSRFToken` on POST/PATCH/DELETE, fetches a new token after login and logout, and retries once on a CSRF failure.
- `GET /api/rbac/me/permissions/` returns `usable`: permissions the role has **and** whose module is switched on. The menu (`nav.ts`) shows only usable pages. The server still checks every request; hiding menu items is not security.
- If two-step verification is required but not set up, the app sends the person to the Django page `/account/mfa/setup/`.

Run it while developing (two terminals):

```bash
# 1. Django (Docker or local), on port 8000
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# 2. Vite with hot reload; it forwards /api, /account, /admin, /static, /dashboard and /settings to port 8000
cd frontend
npm ci
npm run dev
# open http://gorkhabutchery.localhost:5173/app/
```

Checks (CI runs the same in the `frontend` job):

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

Docker: `backend/Dockerfile` has a Node stage (`frontend-build`) that runs `npm ci` and `npm run build`. The frontend folder is passed as a second build context named `frontend-src` (`additional_contexts` in the compose files, `build-contexts` in CI), so the backend build context stays `./backend`. Needs Docker Compose 2.17 or newer (Docker Desktop is fine).

Phone layout: below 760 px the menu becomes a drawer (☰); below 560 px order line tables (`table.stack`) turn into label/value blocks. Wide tables scroll inside their card, never the whole page.

## Web addresses (task 1.12)

Code: `apps/tenants/domains.py` (rules and changes), `apps/tenants/middleware.py` (routing), `apps/tenants/platform_pages.py` (Super Admin page), `apps/tenants/views.py` (unknown address page). Tests: `tests/test_domains.py`.

| Piece | How it works |
|---|---|
| Routing | `TenantRoutingMiddleware` replaces django-tenants' `TenantMainMiddleware` (still first in `MIDDLEWARE`). Host names are matched in lower case, without the port, a trailing dot or `www.` |
| Main address | `Domain.is_primary`. One per business (the library clears the others when one is saved). Careful: a new `Domain` is primary by default, so `add_subdomain` always sets `is_primary` itself |
| Redirect | GET/HEAD on any other address of the business gets a **302** to the main address, same scheme, port, path and query. Not for `/api/`, `/webhooks/`, `/health/` and `/static/` (decision D-085) |
| Unknown address | `DEFAULT_NOT_FOUND_TENANT_VIEW` renders `tenants/unknown_address.html` with status 404, without sessions, cookies or the database |
| Rules | 3–63 characters, `a-z 0-9 -`, no hyphen at either end, no `xx--` (punycode), not only digits, not reserved (`RESERVED_LABELS`), unique; up to `MAX_SUBDOMAINS` = 5 per business |
| Who changes | Super Admin page `/platform/businesses/<id>/addresses/`: `tenants.view` to look, `tenants.edit` to change. The Domain admin and the address list on the tenant page are read-only |
| Audit | `tenant.address_added`, `tenant.main_address_changed`, `tenant.address_removed`: in the platform log and in the business's log (actor type `platform`) |
| Links | `domains.site_url(host, request, path)`: https in production; on a laptop it keeps http and the port. Invitations use the main address |
| API | `GET /api/tenant/licence/` now includes `web_addresses: [{address, main}]` |

### Laptop

`PLATFORM_DOMAIN=localhost`. Businesses open at `http://<name>.localhost:8000/`; browsers send `*.localhost` to your own computer. `DJANGO_ALLOWED_HOSTS` already has `.localhost`.

### Real server (when hosting is chosen)

For a platform domain such as `example.co.nz`:

1. **DNS:** an `A` record for `example.co.nz` and a wildcard `A` record for `*.example.co.nz`, both to the server's IP address. One wildcard covers every business subdomain, so new businesses need no DNS change.
2. **HTTPS:** one certificate for `example.co.nz` and `*.example.co.nz`. Let's Encrypt gives wildcard certificates only with the DNS-01 check, which needs an API key for the DNS provider (for example Cloudflare). Another option is a proxy such as Cloudflare in front of the server.
   A wildcard covers one level only: `gorkha.example.co.nz` works, `www.gorkha.example.co.nz` does not, so do not give out `www.` business links.
3. **`.env`:**
   ```
   PLATFORM_DOMAIN=example.co.nz
   DJANGO_ALLOWED_HOSTS=example.co.nz,.example.co.nz
   DJANGO_CSRF_TRUSTED_ORIGINS=https://example.co.nz,https://*.example.co.nz
   ```
4. **Move existing businesses** (for example data from a laptop pilot): see the changes first, then apply them:
   ```bash
   python manage.py change_platform_domain --from localhost --to example.co.nz
   python manage.py change_platform_domain --from localhost --to example.co.nz --apply
   ```
   `bootstrap_platform` (run by the container at start) never adds a second platform address: if `PLATFORM_DOMAIN` differs from the saved one, it prints the command above and changes nothing.
5. After moving, update the WhatsApp webhook URL in Meta for each business (it contains the business address).

Own domains for businesses (`gorkhabutchery.co.nz`) come in Step 2, with a TXT ownership check and automatic certificates.

## Check system (task 1.13)

Code: `apps/health/` (in both SHARED_APPS and TENANT_APPS, so every schema has its own `CheckRun` history). Tests: `tests/test_system_check.py`.

| Piece | Where |
|---|---|
| Checks | `apps/health/checks.py`: `business_checks()` and `platform_checks()`. Each returns `Result(code, area, label, status, message)`; status `ok`, `warning`, `failed` or `not_set_up` |
| Safety | `_safe()` turns any error inside a check into a red result with a plain message; details go to the log only |
| Connections | `test_connections()` reads secrets in the request thread, then runs the provider tests in a thread pool (no database work in the threads); saves Connected/Failed; audits `integration.status_changed` only when the status changes |
| Runs | `services.run(trigger, user=...)` saves a `CheckRun` (results JSON, counts), audits `system_check.run`, keeps the last 500. The button is limited to once a minute per site (cache key, so per schema) |
| Page / API | `/system-check/`, `/system-check/<id>/`, `GET /api/system-check/`, `POST /api/system-check/run/` (201, or 429 if too soon). Permission: `settings.view` on business sites, `platform_settings.view` on the platform |
| Schedule | `CELERY_BEAT_SCHEDULE`: `health.heartbeat` every 5 minutes, `health.scheduled_checks` every `SYSTEM_CHECK_EVERY_MINUTES` (default 60). The scheduled run goes through every business that may use the system (skips suspended and expired), then the platform |
| Heartbeat | Stored under the platform's cache prefix (`health:heartbeat`), so every business reads the same value. Older than 15 minutes = amber |
| Alerts | A **scheduled** run that turns red (previous run not red) emails System Admins and IT Admins (business) or Super Admins (platform) |
| Command | `python manage.py check_system [--schema <id>] [--all] [--no-live]`; exits with code 1 when red |

Tests replace `ping_workers` (conftest) so no test waits for a Celery reply.

Adding a check: write a function that returns a `Result` (or a list), and add it to `business_checks()` or `platform_checks()` through `_safe()`. Messages must say what to do, in plain words, and never include secrets, host names or exception text.

## Backups (task 1.14)

Code: `apps/backups/` (in both SHARED_APPS and TENANT_APPS). Tests: `tests/test_backups.py` (real `pg_dump` and `pg_restore` against the test database, and a fake Google).

| Piece | Where |
|---|---|
| File format | `fileformat.py`: `.a1989backup` = header + AES-256-GCM chunks; inside, a tar with `manifest.json`, `database.dump` (pg_dump custom format) and `media/`. No Django code, so the same file is the stand-alone tool (`/backups/tool/`) |
| Keys | `keys.py`: platform key from `BACKUP_ENCRYPTION_KEYS` (dev key from `DJANGO_SECRET_KEY` only with DEBUG on); business passphrase sealed with the vault key in `BackupSettings` |
| Database | `dbtools.py`: `dump()` exports a snapshot, counts every table's rows in it, then runs `pg_dump --snapshot`; `restored_copy()` makes a temporary database `a1989_restoretest_<time>_<hex>`, runs `pg_restore`, yields a cursor and always drops it. The password goes in `PGPASSWORD`, never on the command line |
| Runs | `services.py`: `queue()` (button: a `BackupRun`, then the `backups.run` task after commit), `execute()` (one run at a time per site, cache lock), `_backup()`, `_restore_test()`, `cleanup()`, `run_due()`, `run_everywhere()` |
| Google | `gdrive.py` (token refresh, folder, resumable upload in 8 MiB parts with MD5 check, list, delete, download) and `google_connect.py` (sign-in with PKCE through `/oauth/google/callback/` on the platform address) |
| Page / API | `/backups/`, `/backups/google/finish/`, `/backups/tool/`, `GET /api/backups/`, `POST /api/backups/run/` (`{"kind": "backup" or "restore_test"}`; 202, or 409 if not possible). View: `settings.view` / `platform_settings.view`; buttons and changes: `settings.configure` / `platform_settings.configure` |
| Schedule | `backups.scheduled` every 15 minutes: platform first, then every open business that is set up. A backup is due `every_hours` after the last one (1 hour after a failed one); a restore test every `BACKUP_RESTORE_TEST_EVERY_DAYS` days (1 day after a failed one) |
| Check system | `apps/backups/checks.py`: backup key (platform), last backup, Google Drive copy, restore test |
| Storage | `BACKUP_DIR` (`/app/backups`, the `backups_data` Docker volume): `platform/`, `businesses/<schema>/`, `tmp/` (work folders, removed after each run) |

Settings (`.env`): `BACKUP_ENCRYPTION_KEYS` (required when DEBUG is off; the start scripts create `b1:...`), `BACKUP_DIR`, `BACKUP_KEEP_ALL_DAYS` (7), `BACKUP_KEEP_DAILY_DAYS` (30), `BACKUP_KEEP_MONTHLY` (12), `BACKUP_RESTORE_TEST_EVERY_DAYS` (7).

Notes:
- `pg_dump` must be at least as new as the server. The Docker image installs PostgreSQL 16 client tools; a mismatch gives a clear message.
- Backups need a direct database connection (not a transaction-pooling proxy such as PgBouncer), because `pg_dump --snapshot` uses an exported snapshot.
- The restore test needs the CREATEDB right (the Docker database user has it). Without it the test reads all data but cannot load it, and shows amber.
- To rotate the backup key: put a new key first, keep the old one after it (`b2:NEW,b1:OLD`). New backups use `b2`; old ones still open. Remove `b1` only after the old backups have expired.
- Disaster recovery: new server with the same `.env` keys, `python manage.py open_backup <file> <folder>`, then `pg_restore --no-owner --no-privileges -d <empty database> <folder>/database.dump`, then copy `media/` back. Practise it on a test server before the pilots.
- Google sign-in app: see user guide 12.6. Redirect URI: `https://<platform address>/oauth/google/callback/` (laptop: `http://localhost:8000/oauth/google/callback/`).

## Tickets (task 1.15)

Code: `apps/tickets/` (in both SHARED_APPS and TENANT_APPS). Tests: `tests/test_tickets.py`.

| Piece | Where |
|---|---|
| Models | `Ticket` (status, priority, category, source, reporter, assignee, page, browser, response targets) and `TicketComment` (`internal` = note for handlers only). Platform copies keep `from_schema`, `from_business`, `from_ticket_id`; the business ticket keeps `platform_ticket_id` |
| Rules | `services.py`: module `tickets` on business sites, `support` on the platform. `visible()` = all with `.edit`, else own tickets. `report`, `comment`, `set_status`, `assign`, `send_to_platform`, `platform_view` / `reply_to_platform` (always filtered by `from_schema` and `from_ticket_id`), `system_ticket` (one open ticket per `source_key`) |
| Pages / API | `/tickets/`, `/tickets/new/?from=<path>`, `/tickets/<id>/`, `POST /tickets/from-check/<run>/`, `POST /tickets/from-backup/<run>/`; `GET/POST /api/tickets/`, `GET/PATCH /api/tickets/<id>/`, `POST /api/tickets/<id>/comments/`. Someone else's ticket answers 404 |
| Automatic | `apps/health/services.py` (`_ticket`) and `apps/backups/services.py` (`_ticket`) call `system_ticket` for scheduled failures |
| Emails | New ticket → handlers; reply → reporter or assignee; status → reporter; platform answers → the business person who sent it. Email errors are logged, never raised |

## First-login setup (task 1.16)

Code: `apps/setup/` (TENANT_APPS only). Tests: `tests/test_setup.py`.

| Piece | Where |
|---|---|
| Models | `BusinessProfile` and `SetupProgress`, one row each per business schema |
| Opening | `SetupWizardMiddleware` (after the MFA middleware): GET `/admin/` → `/setup/` when `services.should_open_wizard()` (business site, staff, `settings.configure`, not finished, not "Later" in this session) |
| Wizard | `/setup/?step=business|backups|connections|done`, POST actions `business`, `skip`, `test_backup`, `connections`, `finish`; `/setup/later/` |
| Backups step | Uses the Backups page forms with `next=/setup/?step=backups`. `apps.backups.views.safe_next()` accepts only `/setup/...`; the Google sign-in keeps it in the session (`backups_return`) |
| Reminder | Context processor `apps.setup.context.setup`: `backups_reminder` (shown in `templates/admin/base_site.html` until backups are set up) and `show_setup_link` |

Tests: the two test businesses are marked "setup finished" in `conftest.py`; `tests/test_setup.py` uses the `fresh` fixture to undo that.

## In-app user guide (task 1.17)

Code: `apps/guide/` (no models). Tests: `tests/test_guide.py`.

| Piece | Where |
|---|---|
| Chapters | `docs/user-guide/NN-name.md`. `GUIDE_DIR` points there on a laptop; the Docker image copies the folder to `/opt/guide` (third build context `guide-src`, in `docker-compose*.yml` and CI) |
| Order and groups | `GROUPS` in `apps/guide/services.py`; chapters not listed appear under "More" |
| Markdown | `apps/guide/markdown.py`: headings (with anchors), paragraphs, lists, tables, quotes, code, bold, italics, links, images. Everything is HTML-escaped; links may only be relative, http(s) or mailto. `chapter.md` links become `/guide/chapter/`, `images/x.png` becomes `/guide/images/x.png` |
| Pages | `/guide/`, `/guide/search/?q=`, `/guide/<chapter>/`, `/guide/images/<name>` (letters, numbers and dashes; .png/.jpg/.webp). Login needed; any signed-in person |
| Help link | Context processor `apps.guide.context.help_link` → `help_url` (longest matching prefix in `PAGE_HELP`) |
| Screenshots | `tools/guide_screenshots.py` with `docs/user-guide/screenshots.json`. Run on a computer with `pip install playwright` and `playwright install chromium`, against a test business; set `GUIDE_BASE`, `GUIDE_EMAIL`, `GUIDE_PASSWORD` (typed, never saved) and `GUIDE_TOTP_SECRET` |

With `docker-compose.dev.yml` the chapters come from the image: rebuild (`--build`) after editing them, or set `GUIDE_DIR` to a mounted folder.

## Useful commands

| Task | Command |
|---|---|
| Create a business | `python manage.py create_business --name "..." --slug ... --industry ... [--subdomain gorkha]` |
| Move the platform and every business address to a new domain | `python manage.py change_platform_domain --from localhost --to example.co.nz [--apply]` |
| Run a command in one business's schema | `python manage.py tenant_command <command> --schema=<slug>` |
| Migrate all schemas | `python manage.py migrate_schemas` |
| Create missing default roles | `python manage.py sync_roles` |
| Give businesses without a licence a trial | `python manage.py sync_licences` |
| Invite a business's System Admin | `python manage.py invite_admin --schema <slug> --email <email>` |
| Check the audit log is untouched | `python manage.py verify_audit_chain` |
| Re-encrypt saved keys with the newest master key | `python manage.py rotate_vault_key` |
| Reset someone's two-step verification (locked out) | `python manage.py reset_mfa --email <email> [--schema <slug>]` |
| Pretend a customer sent a WhatsApp message (testing) | `python manage.py whatsapp_simulate --schema <slug> --from "021 123 4567" --text "hi"` |
| Expire orders not confirmed in time | `python manage.py expire_orders --minutes 60` |
| Send a test email through the saved Gmail/SMTP connection | `python manage.py send_test_email --to you@example.com [--schema <slug>]` |
| Run the system checks (platform, one business, or all) | `python manage.py check_system [--schema <slug>] [--all] [--no-live]` |
| Make a backup now (platform, or one business), and test restoring it | `python manage.py backup_now [--schema <slug>] [--restore-test]` |
| Open a backup file into a folder (asks for a business passphrase) | `python manage.py open_backup <file> <folder>` |
| Make new screenshots for the user guide (on your computer) | `python tools/guide_screenshots.py [name ...]` |
| Make migrations after model changes | `python manage.py makemigrations` |

Industries: `butchery`, `restaurant`, `fast_food`, `catering`, `events`, `retail`, `services`, `education_consultancy`, `e_learning`, `jobs`, `other`.

## Rules

- Never commit `.env` or any real keys.
- Every new app must be added to `SHARED_APPS` (platform data) or `TENANT_APPS` (business data) in `config/settings.py`. Business data always goes in `TENANT_APPS`.
- Every feature needs tests, including a tenant isolation test where data is involved.

## Daily summary and star feedback (task 2.7)

- `apps.core.scheduled.for_each_business(job, module=)`: runs `job()` in every business that may use the system (licence allowed, module active); one failing business never stops the others.
- Feedback: `orders.feedback` and model `OrderFeedback` (one per order; status asked, answered, skipped, failed; stars 1–5; comment; token). Celery beat `orders.ask_feedback` every 10 minutes → `ask_due()`: orders completed 1–24 hours ago without a row; `why_not()` gives the skip reason. Inside the window `inbox.send_list()` (new: interactive list, up to 10 rows); outside, the template `order_feedback` with 5 quick-reply payloads `feedback:<pk>:<token>:<stars>` (`send_template` now allows up to 10 buttons). `_reply_id()` also reads `list_reply`.
- Answers: `feedback.on_message_received` is connected after the order Yes/No receiver and before the AI (it sets `message.answered_question`). 1–2 stars → `agent.hand_over(..., tell=False)` and the next text is the comment. `customer_anonymised` clears comments.
- Summary: `apps.reports` models `DailySummarySettings` (pk=1) and `DailySummary` (unique `day`). Celery beat `reports.daily_summaries` every 5 minutes → `summary.send_if_due()` → `make(day)`. WhatsApp goes straight to `inbox.whatsapp.send_message` (not an inbox chat) as the `daily_summary` template with 11 parameters; email with `send_mail`. `send_test()` for the admin button.
- API: order detail adds `feedback`; the dashboard adds `feedback` (last 7 days, `feedback.stats`).
- Admin: Reports and dashboard → Daily summary settings (view with orders.view, change and test with orders.configure), Daily summaries (reports.view, read-only); Orders → Customer feedback (read-only).
- Migrations `orders.0006_feedback`, `reports.0001_daily_summary`. Tests: `tests/test_feedback_summary.py`.

## Own domains and HTTPS (task 2.8)

- Model `tenants.CustomDomain` (public schema): name (unique, without www, IDNA form), token, status (pending, live, failing), `domain` (the `Domain` routing row, made when it goes live), last result, verified / failing / fell-back times.
- `apps.tenants.custom_domains`: `validate()`, `lookup()` (dnspython, 5 s; tests replace it), `server_ips()` (`PLATFORM_SERVER_IPS` or the platform domain's A/AAAA), `check_dns()`, `add()`, `check()` (pending → live; live ↔ failing; fall back after 3 days), `make_main_by_business()`, `remove()`, `due()`, `check_due()`, `tls_allowed()`, `is_live()`. Its `_record()` writes both audit logs; `audit(..., actor_elsewhere=True)` (new) keeps only the email of a business admin in the platform log.
- Celery beat `tenants.check_custom_domains` every 15 minutes.
- Middleware: `/internal/tls-allowed/?domain=` (Caddy's "ask") is answered first; a host that fails `ALLOWED_HOSTS` is let in when `is_live()`, by giving that request a `get_host()` that returns the checked host.
- Pages: `/settings/web-addresses/` (`apps.tenants.business_pages`, Settings – View / Configure; link "Web addresses" in the admin header) and the Super Admin's business addresses page (own domains list, remove). `domains.check_removable()` refuses a custom domain's routing row; `add_subdomain()` counts only platform subdomains.
- Check system: "Own domains" (not set up / waiting / live / DNS problem).
- Server: `deploy/Caddyfile` and the `caddy` service (`caddy:2.10.2-alpine`, profile `server`, ports 80/443, volumes `caddy_data`, `caddy_config`). `.env`: `ACME_EMAIL`, `PLATFORM_SERVER_IPS`.
- New package: dnspython (in `base.txt` and both lock files). Migration `tenants.0003_custom_domains`. Tests: `tests/test_custom_domains.py`.
