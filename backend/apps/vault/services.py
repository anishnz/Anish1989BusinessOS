"""
Connections: save (encrypting secrets), read secrets on the server only,
test, disable and delete. Every change and test is audited, without secrets.
"""
from __future__ import annotations

import json
import re
import secrets as secrets_module

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import connection as db_connection
from django.db import transaction
from django.utils import timezone

from apps.audit.services import audit

from . import crypto, providers
from .models import Connection


def _aad(conn: Connection) -> bytes:
    return f"{db_connection.schema_name}:{conn.uid}".encode()


def mask(value: str) -> str:
    value = value or ""
    return "••••" + value[-4:] if len(value) >= 8 else "••••"


def _validate(provider: providers.Provider, config: dict, secrets: dict, *, is_new: bool) -> tuple[dict, dict]:
    clean_config = {}
    for f in provider.config_fields:
        value = str(config.get(f.name, "") or "").strip() or f.default
        if f.required and not value:
            raise ValidationError(f"'{f.label}' is required.")
        if "\r" in value or "\n" in value:
            raise ValidationError(f"'{f.label}' must be on one line.")
        if value and f.kind == "digits" and not value.isdigit():
            raise ValidationError(f"'{f.label}' must contain only numbers.")
        if value and f.kind == "graph_version" and not re.fullmatch(r"v\d{1,3}\.\d", value):
            raise ValidationError(f"'{f.label}' must look like v25.0.")
        if value and f.kind == "email":
            try:
                validate_email(value)
            except ValidationError:
                raise ValidationError(f"'{f.label}' must be a valid email address.") from None
        if value:
            clean_config[f.name] = value[:500]
    clean_secrets = {}
    for f in provider.secret_fields:
        value = str(secrets.get(f.name, "") or "").strip()
        if value:
            clean_secrets[f.name] = value[:4000]
        elif f.required and is_new:
            raise ValidationError(f"'{f.label}' is required.")
    if provider.code == "whatsapp_cloud" and not clean_config.get("webhook_verify_token"):
        clean_config["webhook_verify_token"] = secrets_module.token_urlsafe(24)
    unknown = set(secrets) - {f.name for f in provider.secret_fields}
    if unknown:
        raise ValidationError(f"Unknown secret field(s): {', '.join(sorted(unknown))}")
    return clean_config, clean_secrets


def _store_secrets(conn: Connection, secrets: dict) -> None:
    sealed = crypto.seal(json.dumps(secrets, sort_keys=True).encode(), _aad(conn))
    conn.secret_kid = sealed.kid
    conn.secret_wrapped_key = sealed.wrapped_key
    conn.secret_key_nonce = sealed.key_nonce
    conn.secret_nonce = sealed.nonce
    conn.secret_ciphertext = sealed.ciphertext
    conn.secret_hints = {k: mask(v) for k, v in secrets.items()}


def read_secrets(conn: Connection) -> dict:
    """Decrypt a connection's secrets. Server-side use only (adapters); never send the result to a browser."""
    if not conn.has_secrets:
        return {}
    sealed = crypto.Sealed(
        conn.secret_kid, conn.secret_wrapped_key, conn.secret_key_nonce, conn.secret_nonce, conn.secret_ciphertext
    )
    return json.loads(crypto.open_sealed(sealed, _aad(conn)))


@transaction.atomic
def create_connection(*, provider_code: str, label: str, config: dict, secrets: dict, is_backup=False, actor=None) -> Connection:
    try:
        provider = providers.get(provider_code)
    except KeyError:
        raise ValidationError("This provider is not available.") from None
    clean_config, clean_secrets = _validate(provider, config, secrets, is_new=True)
    conn = Connection(
        provider=provider.code, category=provider.category, label=(label or provider.label).strip()[:100],
        config=clean_config, is_backup=bool(is_backup), created_by=actor if getattr(actor, "pk", None) else None,
    )
    if clean_secrets:
        _store_secrets(conn, clean_secrets)
    conn.save()
    audit("integration.create", target=conn, actor=actor, metadata={"provider": provider.code, "saved_fields": sorted(clean_secrets)})
    return conn


@transaction.atomic
def update_connection(conn: Connection, *, label=None, config=None, secrets=None, is_backup=None, actor=None) -> Connection:
    """Blank secret fields keep the saved value; filled ones replace it."""
    provider = providers.get(conn.provider)
    merged_config = {**conn.config, **(config or {})}
    clean_config, new_secrets = _validate(provider, merged_config, secrets or {}, is_new=False)
    changed_secrets = sorted(new_secrets)
    if new_secrets:
        _store_secrets(conn, {**read_secrets(conn), **new_secrets})
    conn.config = clean_config
    if label is not None:
        conn.label = label.strip()[:100] or conn.label
    if is_backup is not None:
        conn.is_backup = bool(is_backup)
    if new_secrets or config:
        conn.status = Connection.Status.NOT_TESTED
    conn.save()
    audit("integration.update", target=conn, actor=actor, metadata={"replaced_fields": changed_secrets, "config_fields": sorted((config or {}).keys())})
    return conn


def test_connection(conn: Connection, *, actor=None) -> providers.TestResult:
    provider = providers.get(conn.provider)
    if conn.status == Connection.Status.DISABLED:
        return providers.TestResult(False, "This connection is disabled.")
    try:
        result = provider.test(read_secrets(conn), conn.config)
    except crypto.VaultError as exc:
        result = providers.TestResult(False, str(exc))
    conn.status = Connection.Status.CONNECTED if result.ok else Connection.Status.FAILED
    conn.last_tested_at = timezone.now()
    conn.last_test_message = result.message
    conn.save(update_fields=["status", "last_tested_at", "last_test_message", "updated_at"])
    audit("integration.test", target=conn, actor=actor, outcome="success" if result.ok else "failed", metadata={"message": result.message})
    return result


def set_disabled(conn: Connection, disabled: bool, *, actor=None) -> Connection:
    conn.status = Connection.Status.DISABLED if disabled else Connection.Status.NOT_TESTED
    conn.save(update_fields=["status", "updated_at"])
    audit("integration.disable" if disabled else "integration.enable", target=conn, actor=actor)
    return conn


@transaction.atomic
def delete_connection(conn: Connection, *, actor=None) -> None:
    audit("integration.delete", target=conn, actor=actor, metadata={"provider": conn.provider})
    conn.delete()


def active_connection(category: str) -> Connection | None:
    """The connection modules should use for a category: the main one if it works, else a backup."""
    candidates = Connection.objects.filter(category=category).exclude(status__in=[Connection.Status.DISABLED, Connection.Status.FAILED])
    return candidates.order_by("is_backup", "id").first()


@transaction.atomic
def rotate_master_key() -> int:
    """Re-wrap every data key in the current schema with the newest master key."""
    count = 0
    for conn in Connection.objects.select_for_update().exclude(secret_ciphertext=None):
        old = crypto.Sealed(conn.secret_kid, conn.secret_wrapped_key, conn.secret_key_nonce, conn.secret_nonce, conn.secret_ciphertext)
        new = crypto.rewrap(old, _aad(conn))
        if new is not old:
            Connection.objects.filter(pk=conn.pk).update(secret_kid=new.kid, secret_wrapped_key=new.wrapped_key, secret_key_nonce=new.key_nonce)
            count += 1
    if count:
        audit("vault.key_rotated", metadata={"connections": count, "key_id": crypto.master_keys()[0][0]})
    return count
