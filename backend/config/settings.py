"""
Settings for Anish1989 Business OS.

All environment-specific values come from environment variables (or a
`.env` file in development). Never put secrets in this file.
See `.env.example` in the repository root for the full list.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_SECURE_SSL_REDIRECT=(bool, True),
    PLATFORM_DOMAIN=(str, "localhost"),
    TIME_ZONE=(str, "Pacific/Auckland"),
)

# Read a local .env file if present (development only).
env_file = BASE_DIR.parent / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("DJANGO_CSRF_TRUSTED_ORIGINS")

# Root domain of the platform. Tenants get <slug>.<PLATFORM_DOMAIN>.
PLATFORM_DOMAIN = env("PLATFORM_DOMAIN")

# ---------------------------------------------------------------------------
# Apps
#
# SHARED_APPS live in the `public` schema (platform-wide data: tenants,
# domains, platform admins). TENANT_APPS get their own tables inside every
# tenant schema, so each business's data is physically separate.
# `auth` and `accounts` are in both lists: platform admins are stored in the
# public schema, and each business's users are stored in its own schema.
# ---------------------------------------------------------------------------
SHARED_APPS = [
    "django_tenants",  # must be first
    "apps.tenants",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "apps.accounts",
    "apps.audit",
    "apps.rbac",
    "apps.licensing",
    "apps.vault",
    "apps.health",
    "apps.backups",
    "apps.tickets",
    "apps.core",
]

TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "apps.accounts",
    "apps.audit",
    "apps.rbac",
    "apps.vault",
    "apps.health",
    "apps.backups",
    "apps.tickets",
    # Business data (only inside each business's schema)
    "apps.catalog",
    "apps.customers",
    "apps.orders",
    "apps.inbox",
    "apps.reports",
]

INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"
# Shown (with status 404) when no business uses the requested address.
DEFAULT_NOT_FOUND_TENANT_VIEW = "apps.tenants.views.unknown_address"
PUBLIC_SCHEMA_NAME = "public"

MIDDLEWARE = [
    "apps.tenants.middleware.TenantRoutingMiddleware",  # must be first: finds the business from the address
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.licensing.middleware.LicenceMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.accounts.middleware.StaffMFAMiddleware",
    "apps.audit.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"  # tenant sites
PUBLIC_SCHEMA_URLCONF = "config.urls_public"  # platform site

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL, schema per tenant)
# ---------------------------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DATABASE_CONN_MAX_AGE", default=60)
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

# Email login with lockout after repeated failures (see apps/accounts/backends.py).
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.LockoutEmailBackend",  # login
    "apps.rbac.backends.RolePermissionBackend",  # permissions from roles (also used by the admin)
]
LOGIN_LOCKOUT_ATTEMPTS = env.int("LOGIN_LOCKOUT_ATTEMPTS", default=5)
LOGIN_LOCKOUT_SECONDS = env.int("LOGIN_LOCKOUT_SECONDS", default=15 * 60)

# Argon2 first. Older hashes still work and are upgraded on the next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# MFA (authenticator app). Staff and admins must use it.
MFA_REQUIRED_FOR_STAFF = env.bool("MFA_REQUIRED_FOR_STAFF", default=True)
MFA_BACKUP_CODE_COUNT = 10


def OTP_TOTP_ISSUER(device):  # noqa: N802 - Django settings must be uppercase
    """Name shown in the authenticator app, e.g. 'Anish1989 Business OS - Gorkha Butchery'."""
    from apps.accounts.security import totp_issuer

    return totp_issuer(device)

LOGIN_URL = "admin:login"

# Secret vault: master keys come only from the environment ("id:base64key,...", newest first).
# Without it, development (DEBUG) derives a key from SECRET_KEY; production refuses to start the vault.
VAULT_MASTER_KEYS = env("VAULT_MASTER_KEYS", default="")
# Let connections call private-network addresses (e.g. a local Ollama). Development only.
ALLOW_PRIVATE_NETWORK_URLS = env.bool("ALLOW_PRIVATE_NETWORK_URLS", default=False)

# Licences: every new business starts with a trial (no automatic charge).
LICENCE_TRIAL_DAYS = env.int("LICENCE_TRIAL_DAYS", default=30)
LICENCE_TRIAL_MAX_USERS = env.int("LICENCE_TRIAL_MAX_USERS", default=10)
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)  # 8 hours

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Cache and background jobs (Redis)
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        # Keep cache keys separate per tenant.
        "KEY_FUNCTION": "django_tenants.cache.make_key",
        "REVERSE_KEY_FUNCTION": "django_tenants.cache.reverse_key",
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TIMEZONE = env("TIME_ZONE")
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Scheduled jobs (run by the `scheduler` service). See apps/health/tasks.py.
CELERY_BEAT_SCHEDULE = {
    "heartbeat": {"task": "health.heartbeat", "schedule": 5 * 60},
    "system-checks": {"task": "health.scheduled_checks", "schedule": env.int("SYSTEM_CHECK_EVERY_MINUTES", default=60) * 60},
    # Looks every 15 minutes for sites whose next backup (every 6 hours by default) or restore test is due.
    "backups": {"task": "backups.scheduled", "schedule": 15 * 60},
}

# ---------------------------------------------------------------------------
# Backups (task 1.14). See docs/13-developer-setup.md, "Backups".
# ---------------------------------------------------------------------------
# Folder for the platform's own encrypted backups (a Docker volume in production).
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(BASE_DIR / "backups")))
# Key(s) that encrypt the platform's full backups, like VAULT_MASTER_KEYS: "b1:<base64 32 bytes>".
# Keep a copy outside the server: without it the backups cannot be opened.
BACKUP_ENCRYPTION_KEYS = env("BACKUP_ENCRYPTION_KEYS", default="")
# Keep every backup for 7 days, then one a day for 30 days, then one a month for 12 months.
BACKUP_KEEP_ALL_DAYS = env.int("BACKUP_KEEP_ALL_DAYS", default=7)
BACKUP_KEEP_DAILY_DAYS = env.int("BACKUP_KEEP_DAILY_DAYS", default=30)
BACKUP_KEEP_MONTHLY = env.int("BACKUP_KEEP_MONTHLY", default=12)
# Automatic restore test of the newest backup.
BACKUP_RESTORE_TEST_EVERY_DAYS = env.int("BACKUP_RESTORE_TEST_EVERY_DAYS", default=7)

# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Deny by default; each view opens access explicitly.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {
        "login": env("THROTTLE_LOGIN", default="20/min"),
        "password_reset": env("THROTTLE_PASSWORD_RESET", default="5/hour"),
        "mfa": env("THROTTLE_MFA", default="20/min"),
    },
}

# ---------------------------------------------------------------------------
# Email (password reset and notifications)
# ---------------------------------------------------------------------------
# Sends through the email connection saved on the Integrations page (see apps/vault/mail.py).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="apps.vault.mail.VaultEmailBackend")
# Used when no email connection is saved: the console in development, or the EMAIL_HOST settings below.
EMAIL_FALLBACK_BACKEND = env(
    "EMAIL_FALLBACK_BACKEND",
    default="django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Anish1989 Business OS <no-reply@localhost>")
PASSWORD_RESET_TIMEOUT = 60 * 60  # reset links work for 1 hour

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-nz"
# Prices include GST. Phone numbers without a + are read as numbers from this country.
GST_RATE = env("GST_RATE", default="0.15")
PHONE_DEFAULT_REGION = env("PHONE_DEFAULT_REGION", default="NZ")
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static and media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Staff screens (React, task 1.11). Built by `npm run build` in frontend/ (or in the Docker image)
# and served at /app/; its files are collected under /static/app/.
FRONTEND_DIST = Path(env("FRONTEND_DIST", default=str(BASE_DIR.parent / "frontend" / "dist")))
STATICFILES_DIRS = [("app", FRONTEND_DIST)] if FRONTEND_DIST.is_dir() else []
MEDIA_URL = "media/"
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# ---------------------------------------------------------------------------
# Security (strict unless DEBUG)
# ---------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env("DJANGO_SECURE_SSL_REDIRECT")
    SECURE_REDIRECT_EXEMPT = [r"^health/"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 30)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # HSTS "preload" is left off on purpose (decision D-081): a domain on the browsers'
    # preload list is very hard to remove, and businesses will add their own domains.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]

# ---------------------------------------------------------------------------
# Logging (never log secrets)
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"tenant_context": {"()": "django_tenants.log.TenantContextFilter"}},
    "formatters": {
        "tenant": {"format": "%(asctime)s %(levelname)s [%(schema_name)s:%(domain_url)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "filters": ["tenant_context"], "formatter": "tenant"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # HTTP client debug logs can contain request URLs (some providers put tokens in URLs).
    "loggers": {"urllib3": {"level": "WARNING"}, "requests": {"level": "WARNING"}},
}
