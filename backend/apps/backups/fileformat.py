#!/usr/bin/env python3
"""
Anish1989 Business OS backup file format (.a1989backup).

This file has no Django code on purpose: it is also the stand-alone tool that
opens a backup on any computer with Python 3.12+ and the `cryptography`
package (pip install cryptography):

    python anish1989-backup-tool.py info   FILE
    python anish1989-backup-tool.py decrypt FILE OUTPUT_FOLDER

`decrypt` asks for the backup passphrase (business backups). For platform
backups it uses the BACKUP_ENCRYPTION_KEYS environment variable, the same
value as in the server's .env file.

Format
------
    "A1989BK1"  (8 bytes)
    header length (4 bytes, big-endian) + header (JSON, UTF-8)
    encrypted chunks

The data is a tar archive (manifest.json, database.dump, media/...) split into
1 MiB chunks. Each chunk is encrypted with AES-256-GCM. The nonce is a random
7-byte prefix + a 4-byte chunk counter + 1 byte that is 1 only on the last
chunk, and the whole header is the associated data. So a changed header,
swapped, missing or extra chunks, or a cut-off file are all detected.

The file key comes from either
- a 32-byte platform key (HKDF-SHA256 with a random salt per file), or
- a passphrase (scrypt, n=2^17, r=8, p=1, random salt per file).
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import io
import json
import os
import struct
import sys
import tarfile
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"A1989BK1"
FORMAT_VERSION = 1
CHUNK_SIZE = 1024 * 1024
TAG_SIZE = 16
MAX_HEADER = 64 * 1024
MAX_CHUNK = 16 * 1024 * 1024
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**17, 8, 1
HKDF_INFO = b"anish1989-backup-file-v1"
EXTENSION = ".a1989backup"


class BackupFileError(Exception):
    """The file cannot be opened: wrong key or passphrase, changed, cut off, or not a backup."""


@dataclass(frozen=True)
class KeySource:
    """What encrypts a file: a platform key (`key_id`, 32 `key` bytes) or a `passphrase`."""

    key_id: str = ""
    key: bytes = b""
    passphrase: str = ""

    def __post_init__(self):
        if bool(self.key) == bool(self.passphrase):
            raise ValueError("Give either a key or a passphrase.")
        if self.key and len(self.key) != 32:
            raise ValueError("A backup key must be 32 bytes.")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)


def _derive(header: dict, source: KeySource | None, keys: dict[str, bytes] | None, passphrase: str | None) -> bytes:
    spec = header.get("key") or {}
    salt = _unb64(spec.get("salt", ""))
    if spec.get("type") == "passphrase":
        if passphrase is None:
            raise BackupFileError("This backup is protected with a passphrase. Enter the backup passphrase.")
        n, r, p = int(spec["n"]), int(spec["r"]), int(spec["p"])
        if not (2**14 <= n <= 2**20 and 1 <= r <= 16 and 1 <= p <= 4):
            raise BackupFileError("This file has unsupported passphrase settings.")
        return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))
    if spec.get("type") == "key":
        key = (keys or {}).get(spec.get("id", ""))
        if key is None:
            raise BackupFileError(f"Backup key '{spec.get('id', '')}' is not available, so this file cannot be opened.")
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=HKDF_INFO).derive(key)
    raise BackupFileError("This file uses an unknown key type.")


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", counter) + (b"\x01" if last else b"\x00")


class EncryptWriter(io.RawIOBase):
    """Write plain bytes in; encrypted chunks go to `out`. close() writes the last chunk."""

    def __init__(self, out, source: KeySource, *, info: dict | None = None, chunk_size: int = CHUNK_SIZE):
        super().__init__()
        self.out = out
        self.chunk_size = chunk_size
        self.counter = 0
        self.buffer = bytearray()
        self.prefix = os.urandom(7)
        salt = os.urandom(16)
        if source.passphrase:
            key_spec = {"type": "passphrase", "kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _b64(salt)}
        else:
            key_spec = {"type": "key", "id": source.key_id, "salt": _b64(salt)}
        header = {
            "format": FORMAT_VERSION, "cipher": "AES-256-GCM", "chunk_size": chunk_size,
            "nonce_prefix": _b64(self.prefix), "key": key_spec, "info": info or {},
        }
        header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        self.aad = MAGIC + struct.pack(">I", len(header_bytes)) + header_bytes
        file_key = _derive(header, source, {source.key_id: source.key} if source.key else None, source.passphrase or None)
        self.aead = AESGCM(file_key)
        self.out.write(self.aad)
        self.bytes_in = 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        if self.closed:
            raise ValueError("write to a closed backup file")
        self.buffer += data
        self.bytes_in += len(data)
        # Keep at least one byte back, so the last chunk is never written as "not last".
        while len(self.buffer) > self.chunk_size:
            self._emit(bytes(self.buffer[: self.chunk_size]), last=False)
            del self.buffer[: self.chunk_size]
        return len(data)

    def _emit(self, chunk: bytes, *, last: bool) -> None:
        self.out.write(self.aead.encrypt(_nonce(self.prefix, self.counter, last), chunk, self.aad))
        self.counter += 1

    def close(self) -> None:
        if not self.closed:
            self._emit(bytes(self.buffer), last=True)
            self.buffer.clear()
        super().close()


def read_header(stream) -> tuple[dict, bytes]:
    magic = stream.read(len(MAGIC))
    if magic != MAGIC:
        raise BackupFileError("This is not an Anish1989 backup file.")
    raw_len = stream.read(4)
    if len(raw_len) != 4:
        raise BackupFileError("The file is incomplete.")
    (length,) = struct.unpack(">I", raw_len)
    if not 0 < length <= MAX_HEADER:
        raise BackupFileError("The file header is damaged.")
    header_bytes = stream.read(length)
    if len(header_bytes) != length:
        raise BackupFileError("The file is incomplete.")
    try:
        header = json.loads(header_bytes)
    except ValueError as exc:
        raise BackupFileError("The file header is damaged.") from exc
    if header.get("format") != FORMAT_VERSION or header.get("cipher") != "AES-256-GCM":
        raise BackupFileError("This backup was made by a newer or unknown version.")
    return header, magic + raw_len + header_bytes


class DecryptReader(io.RawIOBase):
    """Read plain bytes from an encrypted backup stream. Raises BackupFileError on any problem."""

    def __init__(self, stream, *, keys: dict[str, bytes] | None = None, passphrase: str | None = None):
        super().__init__()
        self.stream = stream
        self.header, self.aad = read_header(stream)
        self.chunk_size = int(self.header.get("chunk_size") or 0)
        if not 0 < self.chunk_size <= MAX_CHUNK:
            raise BackupFileError("The file header is damaged.")
        self.prefix = _unb64(self.header.get("nonce_prefix", ""))
        if len(self.prefix) != 7:
            raise BackupFileError("The file header is damaged.")
        self.aead = AESGCM(_derive(self.header, None, keys, passphrase))
        self.counter = 0
        self.done = False
        self.plain = bytearray()
        self.next_block = self._read_block()
        self._first = True

    def _read_block(self) -> bytes:
        want = self.chunk_size + TAG_SIZE
        data = bytearray()
        while len(data) < want:
            part = self.stream.read(want - len(data))
            if not part:
                break
            data += part
        return bytes(data)

    def _next_chunk(self) -> None:
        block = self.next_block
        if not block:
            raise BackupFileError("The file is incomplete (it was cut off).")
        self.next_block = self._read_block() if len(block) == self.chunk_size + TAG_SIZE else b""
        last = not self.next_block
        try:
            self.plain += self.aead.decrypt(_nonce(self.prefix, self.counter, last), block, self.aad)
        except InvalidTag:
            if last and self._opens_as_middle_chunk(block):
                raise BackupFileError("The file is incomplete (it was cut off).") from None
            if self._first:
                raise BackupFileError("Wrong key or passphrase, or the file was changed.") from None
            raise BackupFileError("The file was changed or is incomplete.") from None
        self._first = False
        self.counter += 1
        if last:
            self.done = True

    def _opens_as_middle_chunk(self, block: bytes) -> bool:
        try:
            self.aead.decrypt(_nonce(self.prefix, self.counter, False), block, self.aad)
            return True
        except InvalidTag:
            return False

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while not self.plain and not self.done:
            self._next_chunk()
        n = min(len(buffer), len(self.plain))
        buffer[:n] = self.plain[:n]
        del self.plain[:n]
        return n

    def read_all_and_verify(self) -> int:
        """Read to the end (checks every chunk). Returns the number of plain bytes."""
        total = 0
        while True:
            chunk = self.read(CHUNK_SIZE)
            if not chunk:
                return total
            total += len(chunk)


# ---------------------------------------------------------------------------
# Archive helpers: a backup holds manifest.json, database.dump and media/.
# ---------------------------------------------------------------------------
def _private_member(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.mode, member.uid, member.gid, member.uname, member.gname = 0o600, 0, 0, "", ""
    return member


def write_archive(out, source: KeySource, *, info: dict, manifest: dict, files: list[tuple[str, str]]) -> int:
    """
    Encrypt a tar archive of `manifest` (as manifest.json) and `files`
    ([(name in archive, path on disk)]) into `out`. Returns plain bytes written.
    """
    writer = EncryptWriter(out, source, info=info)
    with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as tar:
        data = json.dumps(manifest, indent=2, sort_keys=True, default=str).encode()
        member = tarfile.TarInfo("manifest.json")
        member.size = len(data)
        member.mode = 0o600
        member.mtime = int(time.time())
        tar.addfile(member, io.BytesIO(data))
        for arcname, path in files:
            tar.add(path, arcname=arcname, recursive=False, filter=_private_member)
    writer.close()
    return writer.bytes_in


def extract_archive(stream, folder: str, *, keys=None, passphrase=None) -> dict:
    """Decrypt and unpack into `folder` (made private). Returns the manifest."""
    os.makedirs(folder, mode=0o700, exist_ok=True)
    reader = DecryptReader(stream, keys=keys, passphrase=passphrase)
    try:
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            tar.extractall(folder, filter="data")
    except tarfile.TarError as exc:
        raise BackupFileError("The backup content is damaged.") from exc
    if not reader.done:
        reader.read_all_and_verify()
    with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_keys(raw: str) -> dict[str, bytes]:
    """'id:base64,id2:base64' -> {id: 32 bytes}."""
    keys = {}
    for part in [p.strip() for p in (raw or "").split(",") if p.strip()]:
        if ":" not in part:
            raise ValueError("Backup keys must look like 'id:base64key'.")
        kid, b64 = part.split(":", 1)
        key = base64.b64decode(b64.strip())
        if len(key) != 32:
            raise ValueError(f"Backup key '{kid.strip()}' must be 32 bytes (base64 of 32 random bytes).")
        keys[kid.strip()] = key
    return keys


# ---------------------------------------------------------------------------
# Command line (stand-alone tool)
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("info", "decrypt") or (argv[0] == "decrypt" and len(argv) != 3):
        print(__doc__.split("Format")[0].strip())
        return 2
    with open(argv[1], "rb") as fh:
        try:
            header, _ = read_header(fh)
        except BackupFileError as exc:
            print(f"Error: {exc}")
            return 1
        if argv[0] == "info":
            print(json.dumps({k: header[k] for k in ("format", "cipher", "info")} | {"protected_with": header["key"]["type"]}, indent=2))
            return 0
        fh.seek(0)
        passphrase = None
        keys = None
        if header["key"]["type"] == "passphrase":
            passphrase = getpass.getpass("Backup passphrase: ")
        else:
            try:
                keys = parse_keys(os.environ.get("BACKUP_ENCRYPTION_KEYS", ""))
            except ValueError as exc:
                print(f"Error: {exc}")
                return 1
        try:
            manifest = extract_archive(fh, argv[2], keys=keys, passphrase=passphrase)
        except BackupFileError as exc:
            print(f"Error: {exc}")
            return 1
    print(f"Opened. Files are in {argv[2]}")
    print(f"Made: {manifest.get('created_at')}  Site: {manifest.get('site_name')}  Tables: {len(manifest.get('tables', {}))}")
    print("To load the database: pg_restore --no-owner --no-privileges -d <empty database> database.dump")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
