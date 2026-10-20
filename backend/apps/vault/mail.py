"""
Email backend that sends through the email connection saved in the vault.

Order of choice for each email:
1. the current business's own email connection (Gmail or SMTP), if it has one
   that is not disabled or failed;
2. otherwise the platform's email connection (saved on the platform site),
   with the business name in the sender name;
3. otherwise EMAIL_FALLBACK_BACKEND (the console in development, or the
   EMAIL_HOST settings from .env).

Set EMAIL_BACKEND=apps.vault.mail.VaultEmailBackend (the default).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection as db_connection
from django_tenants.utils import schema_context

from . import crypto, providers, services

log = logging.getLogger(__name__)
PLATFORM_NAME = "Anish1989 Business OS"


@dataclass
class SmtpSettings:
    host: str
    port: int
    use_tls: bool
    username: str
    password: str
    from_address: str
    from_name: str
    connection_id: int
    schema: str


def _settings_for(conn) -> SmtpSettings | None:
    try:
        secrets = services.read_secrets(conn)
    except crypto.VaultError:
        log.error("Email connection %s in schema %s could not be decrypted.", conn.pk, db_connection.schema_name)
        return None
    c = conn.config or {}
    if conn.provider == "gmail":
        return SmtpSettings(
            providers.GMAIL_HOST, providers.GMAIL_PORT, True, c["email"], providers.gmail_app_password(secrets),
            c["email"], c.get("from_name", ""), conn.pk, db_connection.schema_name,
        )
    if conn.provider == "smtp":
        return SmtpSettings(
            c["host"], int(c.get("port") or 587), providers.as_bool(c.get("use_tls", "true")), c.get("username", ""),
            secrets.get("password", ""), c["from_email"], "", conn.pk, db_connection.schema_name,
        )
    return None


def _business_name() -> str:
    tenant = getattr(db_connection, "tenant", None)
    return getattr(tenant, "name", "") if tenant is not None and db_connection.schema_name != "public" else ""


def resolve() -> SmtpSettings | None:
    """The sending account for the current schema, or None to use the fallback backend."""
    conn = services.active_connection("email")
    if conn is not None:
        found = _settings_for(conn)
        if found:
            if not found.from_name:
                found.from_name = _business_name() or PLATFORM_NAME
            return found
    if db_connection.schema_name == "public":
        return None
    business = _business_name()
    with schema_context("public"):
        conn = services.active_connection("email")
        found = _settings_for(conn) if conn is not None else None
    if found:
        base = found.from_name or PLATFORM_NAME
        found.from_name = f"{business} via {base}" if business else base
    return found


class VaultEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        smtp = resolve()
        if smtp is None:
            backend = get_connection(settings.EMAIL_FALLBACK_BACKEND, fail_silently=self.fail_silently)
            return backend.send_messages(email_messages)
        sender = formataddr((smtp.from_name.replace("\r", " ").replace("\n", " "), smtp.from_address))
        for message in email_messages:
            # Gmail and most servers only allow sending as the logged-in account.
            original_name, original_address = parseaddr(message.from_email or "")
            if original_address and original_address.lower() != smtp.from_address.lower() and not message.reply_to:
                message.reply_to = [original_address] if original_address != parseaddr(settings.DEFAULT_FROM_EMAIL)[1] else []
            message.from_email = sender
        backend = get_connection(
            "django.core.mail.backends.smtp.EmailBackend",
            host=smtp.host, port=smtp.port, username=smtp.username, password=smtp.password,
            use_tls=smtp.use_tls, timeout=providers.TIMEOUT, fail_silently=self.fail_silently,
        )
        try:
            return backend.send_messages(email_messages)
        except Exception:
            log.error("Sending email through connection %s in schema %s failed.", smtp.connection_id, smtp.schema)
            raise
