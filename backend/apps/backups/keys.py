"""
Encryption keys for backups.

- Platform backups use BACKUP_ENCRYPTION_KEYS from the environment
  ("b2:<base64>,b1:<base64>": the first key encrypts new backups, older keys
  still open old ones). On a laptop with DEBUG on and no key set, a key is
  derived from DJANGO_SECRET_KEY so the project runs without setup.
- Business backups use the business's own passphrase, stored encrypted with
  the vault master key (see services.set_passphrase).
"""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .fileformat import KeySource, parse_keys

DEV_KEY_ID = "dev"
# Word list for generated passphrases: short, common, easy to read aloud and type.
WORDS = (
    "acorn amber anchor apple arrow aspen autumn badge bamboo banjo barley basket beacon berry birch biscuit blanket "
    "bridge bronze bucket butter cabin cactus camel candle canyon carrot castle cedar cherry chess cider cinnamon "
    "clover cobalt comet copper coral cotton crayon cricket crystal daisy delta desert dolphin dragon dune eagle "
    "ember emerald falcon feather fern fiddle forest fossil garden garlic ginger glacier granite grape harbor hazel "
    "helmet honey island ivory jacket jasmine jungle kettle kiwi ladder lagoon lantern lemon lily lotus magnet "
    "mango maple marble meadow melon mint mirror monsoon mosaic nectar nickel noodle oasis ocean olive onion orbit "
    "orchid otter paddle palm panda pebble pepper pigeon pillow planet plum pocket pony puzzle quartz quiet rabbit "
    "radish rain raven reef ribbon river rocket saddle saffron salmon sandal scarf sesame shadow silver sparrow "
    "spider spring squash stone summer sunset tango teapot thistle thunder tiger timber tomato topaz tulip tunnel "
    "turtle valley velvet violet walnut willow window winter yarn yellow zebra zigzag"
).split()


def platform_keys() -> dict[str, bytes]:
    """{key id: key}; the first entry encrypts new backups."""
    raw = getattr(settings, "BACKUP_ENCRYPTION_KEYS", "") or ""
    if raw:
        try:
            return parse_keys(raw)
        except ValueError as exc:
            raise ImproperlyConfigured(f"BACKUP_ENCRYPTION_KEYS: {exc}") from None
    if settings.DEBUG:
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"anish1989-backup-dev", info=b"backup").derive(
            settings.SECRET_KEY.encode()
        )
        return {DEV_KEY_ID: derived}
    raise ImproperlyConfigured("BACKUP_ENCRYPTION_KEYS must be set when DEBUG is off.")


def platform_source() -> KeySource:
    kid, key = next(iter(platform_keys().items()))
    return KeySource(key_id=kid, key=key)


def using_dev_key() -> bool:
    try:
        return next(iter(platform_keys())) == DEV_KEY_ID
    except ImproperlyConfigured:
        return False


def generate_passphrase(words: int = 6) -> str:
    """Six random words from 159 plus a 4-digit number: about 57 bits, slowed down further by scrypt."""
    picked = [secrets.choice(WORDS) for _ in range(words)]
    return "-".join(picked) + f"-{secrets.randbelow(10000):04d}"


def check_passphrase(passphrase: str) -> None:
    from django.core.exceptions import ValidationError

    if len(passphrase) < 16:
        raise ValidationError("The passphrase must be at least 16 characters. Several words work well.")
    if len(passphrase) > 200:
        raise ValidationError("The passphrase must be at most 200 characters.")
    if len(set(passphrase)) < 6:
        raise ValidationError("The passphrase is too simple. Use several different words.")
