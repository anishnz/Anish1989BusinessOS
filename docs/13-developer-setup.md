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

## Useful commands

| Task | Command |
|---|---|
| Create a business | `python manage.py create_business --name "..." --slug ... --industry ...` |
| Run a command in one business's schema | `python manage.py tenant_command <command> --schema=<slug>` |
| Migrate all schemas | `python manage.py migrate_schemas` |
| Make migrations after model changes | `python manage.py makemigrations` |

Industries: `butchery`, `restaurant`, `fast_food`, `catering`, `events`, `retail`, `services`, `education_consultancy`, `e_learning`, `jobs`, `other`.

## Rules

- Never commit `.env` or any real keys.
- Every new app must be added to `SHARED_APPS` (platform data) or `TENANT_APPS` (business data) in `config/settings.py`. Business data always goes in `TENANT_APPS`.
- Every feature needs tests, including a tenant isolation test where data is involved.
