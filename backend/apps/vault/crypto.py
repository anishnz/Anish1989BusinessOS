"""
Envelope encryption for secrets.

- Every secret gets its own random 256-bit data key (DEK) and is encrypted
  with AES-256-GCM.
- The DEK is encrypted ("wrapped") with a master key (KEK). Master keys come
  only from the VAULT_MASTER_KEYS environment variable, never the database.
- Both encryptions are bound to "associated data" (the business schema and the
  connection id), so a ciphertext copied to another business or another
  connection cannot be decrypted.
- Master keys have ids. The first key in VAULT_MASTER_KEYS encrypts new
  secrets; older keys still decrypt. `rotate_vault_key` re-wraps old DEKs.

VAULT_MASTER_KEYS format: "k2:<base64 32 bytes>,k1:<base64 32 bytes>"
Create a key with: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class VaultError(Exception):
    """Decryption failed (wrong key, tampered data, or data copied from elsewhere)."""


@dataclass
class Sealed:
    kid: str
    wrapped_key: bytes
    key_nonce: bytes
    nonce: bytes
    ciphertext: bytes


def _parse_keys(raw: str) -> list[tuple[str, bytes]]:
    keys = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        if ":" not in part:
            raise ImproperlyConfigured("VAULT_MASTER_KEYS entries must look like 'id:base64key'.")
        kid, b64 = part.split(":", 1)
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise ImproperlyConfigured(f"Vault key '{kid}' must be 32 bytes (base64 of 32 random bytes).")
        keys.append((kid.strip(), key))
    return keys


def master_keys() -> list[tuple[str, bytes]]:
    """[(key_id, key)], first one is used for new secrets."""
    raw = getattr(settings, "VAULT_MASTER_KEYS", "") or ""
    if raw:
        return _parse_keys(raw)
    if settings.DEBUG:
        # Development only: derive a key from SECRET_KEY so the project runs without setup.
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"anish1989-vault-dev", info=b"vault").derive(
            settings.SECRET_KEY.encode()
        )
        return [("dev", derived)]
    raise ImproperlyConfigured("VAULT_MASTER_KEYS must be set when DEBUG is off.")


def _key_by_id(kid: str) -> bytes:
    for key_id, key in master_keys():
        if key_id == kid:
            return key
    raise VaultError(f"Master key '{kid}' is not configured, so this secret cannot be opened.")


def seal(plaintext: bytes, aad: bytes) -> Sealed:
    kid, kek = master_keys()[0]
    dek = AESGCM.generate_key(bit_length=256)
    nonce, key_nonce = os.urandom(12), os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
    wrapped = AESGCM(kek).encrypt(key_nonce, dek, aad + b"|dek")
    return Sealed(kid, wrapped, key_nonce, nonce, ciphertext)


def open_sealed(sealed: Sealed, aad: bytes) -> bytes:
    try:
        dek = AESGCM(_key_by_id(sealed.kid)).decrypt(bytes(sealed.key_nonce), bytes(sealed.wrapped_key), aad + b"|dek")
        return AESGCM(dek).decrypt(bytes(sealed.nonce), bytes(sealed.ciphertext), aad)
    except InvalidTag as exc:
        raise VaultError("This secret could not be opened (wrong key or the data was changed or copied).") from exc


def rewrap(sealed: Sealed, aad: bytes) -> Sealed:
    """Re-encrypt the data key with the current master key (the secret itself is unchanged)."""
    kid, kek = master_keys()[0]
    if sealed.kid == kid:
        return sealed
    try:
        dek = AESGCM(_key_by_id(sealed.kid)).decrypt(bytes(sealed.key_nonce), bytes(sealed.wrapped_key), aad + b"|dek")
    except InvalidTag as exc:
        raise VaultError("Could not re-wrap: data key did not open.") from exc
    key_nonce = os.urandom(12)
    return Sealed(kid, AESGCM(kek).encrypt(key_nonce, dek, aad + b"|dek"), key_nonce, sealed.nonce, sealed.ciphertext)
