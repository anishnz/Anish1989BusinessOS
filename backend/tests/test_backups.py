"""
Backups (task 1.14): the encrypted file format, real backups and restore tests
against the test database, keeping and removing old copies, the schedule and
alerts, Google Drive (a fake Google), "Connect Google Drive", the Backups page
and API, who may use them, and the Check system lines.
"""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.audit.models import AuditEvent
from apps.backups import checks as backup_checks
from apps.backups import dbtools, fileformat, gdrive, google_connect, keys, retention, services, tasks
from apps.backups.models import BackupRun, BackupSettings
from apps.vault import services as vault
from apps.vault.models import Connection
from tests.conftest import PASSWORD, host_of, make_user
from tests.test_rbac import give_role, verified_staff_client

KIND, SCHED, BUTTON = BackupRun.Kind, BackupRun.Trigger.SCHEDULE, BackupRun.Trigger.BUTTON
GOOD_PASSPHRASE = "orchid-tango-velvet-harbor-7781"


def new_key() -> bytes:
    return os.urandom(32)


@pytest.fixture(autouse=True)
def backup_settings(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "backups"
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.BACKUP_ENCRYPTION_KEYS = "b1:" + base64.b64encode(new_key()).decode()
    return settings


@pytest.fixture(autouse=True)
def no_real_tasks(monkeypatch):
    """Buttons queue a worker task; tests run queued runs by hand."""
    sent = []
    monkeypatch.setattr(tasks.run_task, "delay", lambda *a: sent.append(a))
    return sent


# ---------------------------------------------------------------------------
# A fake Google (OAuth + Drive), so no real account is needed
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeGoogle:
    ACCESS = "at-good"

    def __init__(self):
        self.files, self.sessions, self.calls = {}, {}, []
        self.revoked, self.fail_puts, self.bad_md5, self.no_refresh, self.no_scope = set(), 0, False, False, False
        self.next_id = 1000
        self.secret = "client-secret-XYZ"

    def _id(self):
        self.next_id += 1
        return f"fileid{self.next_id:08d}"

    def request(self, method, url, **kw):
        self.calls.append((method, url))
        data, params, headers = kw.get("data"), kw.get("params") or {}, kw.get("headers") or {}
        if url == gdrive.TOKEN_URL:
            if data.get("client_secret") != self.secret:
                return FakeResponse(401, {"error": "invalid_client"})
            if data["grant_type"] == "refresh_token":
                if data["refresh_token"] in self.revoked:
                    return FakeResponse(400, {"error": "invalid_grant"})
                return FakeResponse(200, {"access_token": self.ACCESS})
            if data["code"].startswith("test-"):
                return FakeResponse(400, {"error": "invalid_grant"})
            body = {"access_token": self.ACCESS, "scope": "" if self.no_scope else gdrive.SCOPE}
            if not self.no_refresh:
                body["refresh_token"] = "rt-" + data["code"]
            self.last_verifier = data.get("code_verifier")
            return FakeResponse(200, body)
        if url == gdrive.REVOKE_URL:
            self.revoked.add(data["token"])
            return FakeResponse(200)
        if headers.get("Authorization") != f"Bearer {self.ACCESS}":
            return FakeResponse(401, {"error": {"errors": [{"reason": "authError"}]}})
        if url == gdrive.ABOUT_URL:
            return FakeResponse(200, {"user": {"emailAddress": "owner@gmail.test"}})
        if url == gdrive.UPLOAD_URL and method == "POST":
            session = f"https://www.googleapis.com/upload/drive/v3/files?upload_id={self._id()}"
            self.sessions[session] = {"meta": kw["json"], "total": int(headers["X-Upload-Content-Length"]), "data": bytearray()}
            return FakeResponse(200, headers={"Location": session})
        if url in self.sessions and method == "PUT":
            s = self.sessions[url]
            rng = headers["Content-Range"]
            if rng.startswith("bytes */"):
                return self._upload_state(s)
            if self.fail_puts:
                self.fail_puts -= 1
                return FakeResponse(503)
            start = int(rng.split()[1].split("-")[0])
            assert start == len(s["data"])
            s["data"] += data
            return self._upload_state(s)
        if url == gdrive.FILES_URL and method == "POST":
            fid = self._id()
            self.files[fid] = {"name": kw["json"]["name"], "folder": True, "parents": [], "trashed": False}
            return FakeResponse(200, {"id": fid})
        if url == gdrive.FILES_URL and method == "GET":
            folder = params["q"].split("'")[1]
            found = [{"id": i, "name": f["name"], "createdTime": f["createdTime"], "size": str(len(f["data"]))}
                     for i, f in self.files.items() if folder in f["parents"] and not f.get("folder")]
            return FakeResponse(200, {"files": found})
        if url.startswith(gdrive.FILES_URL + "/"):
            fid = url.rsplit("/", 1)[1]
            if method == "DELETE":
                self.files.pop(fid, None)
                return FakeResponse(204)
            if fid in self.files:
                return FakeResponse(200, {"id": fid, "trashed": self.files[fid]["trashed"]})
            return FakeResponse(404)
        raise AssertionError(f"unexpected call {method} {url}")

    def _upload_state(self, s):
        if len(s["data"]) < s["total"]:
            return FakeResponse(308, headers={"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {})
        fid = self._id()
        md5 = hashlib.md5(bytes(s["data"])).hexdigest()
        self.files[fid] = {"name": s["meta"]["name"], "parents": s["meta"]["parents"], "data": bytes(s["data"]),
                           "createdTime": timezone.now().isoformat().replace("+00:00", "Z"), "trashed": False}
        return FakeResponse(200, {"id": fid, "md5Checksum": "0" * 32 if self.bad_md5 else md5, "size": str(s["total"])})

    def get(self, url, **kw):
        fid = url.rsplit("/", 1)[1]
        data = self.files[fid]["data"]

        class Stream(FakeResponse):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def iter_content(self, size):
                for i in range(0, len(data), size):
                    yield data[i:i + size]

        return Stream(200)

    def uploaded(self):
        return [f for f in self.files.values() if not f.get("folder")]


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(gdrive, "_request", fake.request)
    monkeypatch.setattr(gdrive.requests, "get", fake.get)
    monkeypatch.setattr(gdrive, "_sleep", lambda s: None)
    return fake


def sign_in_app(schema="public", google_fake=None):
    with schema_context(schema):
        return vault.create_connection(provider_code="google_oauth_app", label="Google sign-in", config={"client_id": "cid.apps"},
                                       secrets={"client_secret": (google_fake.secret if google_fake else "client-secret-XYZ")})


def connect_drive(schema, google_fake, *, passphrase=GOOD_PASSPHRASE, refresh="rt-good"):
    with schema_context(schema):
        conn = services.save_drive_connection(client_id="cid.apps", client_secret=google_fake.secret, refresh_token=refresh, email="owner@gmail.test")
        if passphrase and schema != "public":
            services.set_passphrase(passphrase)
        return conn


def backup(schema="public", trigger=BUTTON, kind=KIND.BACKUP):
    with schema_context(schema):
        run = BackupRun.objects.create(kind=kind, trigger=trigger, queued_at=timezone.now())
        services.execute(run)
        run.refresh_from_db()
        return run


def open_file(path, **kw):
    folder = Path(path).parent / ("opened-" + Path(path).stem)
    with open(path, "rb") as fh:
        return fileformat.extract_archive(fh, str(folder), **kw), folder


def alerts():
    """Alert emails only (failures also open a ticket, which sends its own email: test_tickets.py)."""
    return [m for m in mail.outbox if "needs attention" in m.subject]


def platform_keys_now():
    return keys.platform_keys()


# ---------------------------------------------------------------------------
# 1. File format and encryption
# ---------------------------------------------------------------------------
def _encrypt(data: bytes, source, chunk=fileformat.CHUNK_SIZE) -> bytes:
    out = io.BytesIO()
    writer = fileformat.EncryptWriter(out, source, chunk_size=chunk)
    writer.write(data)
    writer.close()
    return out.getvalue()


def _decrypt(blob: bytes, **kw) -> bytes:
    return fileformat.DecryptReader(io.BytesIO(blob), **kw).read()


class TestFileFormat:
    key = new_key()
    src = fileformat.KeySource(key_id="k1", key=key)

    @pytest.mark.parametrize("size", [0, 1, 4096, 4097, 3 * 4096])
    def test_round_trip_at_chunk_edges(self, size):
        data = os.urandom(size)
        assert _decrypt(_encrypt(data, self.src, chunk=4096), keys={"k1": self.key}) == data

    def test_passphrase_round_trip_and_wrong_passphrase(self):
        blob = _encrypt(b"customer list", fileformat.KeySource(passphrase=GOOD_PASSPHRASE))
        assert _decrypt(blob, passphrase=GOOD_PASSPHRASE) == b"customer list"
        with pytest.raises(fileformat.BackupFileError, match="Wrong key or passphrase"):
            _decrypt(blob, passphrase=GOOD_PASSPHRASE + "x")
        with pytest.raises(fileformat.BackupFileError, match="passphrase"):
            _decrypt(blob)

    def test_wrong_or_missing_key(self):
        blob = _encrypt(b"x" * 100, self.src)
        with pytest.raises(fileformat.BackupFileError, match="Wrong key"):
            _decrypt(blob, keys={"k1": new_key()})
        with pytest.raises(fileformat.BackupFileError, match="'k1' is not available"):
            _decrypt(blob, keys={"k2": self.key})

    def test_the_content_is_not_readable(self):
        secret = b"SECRET-CUSTOMER-PHONE-0211234567" * 50
        blob = _encrypt(secret, self.src)
        assert b"SECRET-CUSTOMER" not in blob and blob.startswith(fileformat.MAGIC)
        # Same data, new file: new salt and nonces, so the files differ completely.
        assert _encrypt(secret, self.src)[-200:] != blob[-200:]

    def test_any_changed_byte_is_detected(self):
        blob = bytearray(_encrypt(os.urandom(10000), self.src, chunk=4096))
        header_len = len(fileformat.read_header(io.BytesIO(bytes(blob)))[1])
        for pos in (header_len + 5, header_len + 4096 + 20, len(blob) - 3):
            changed = bytearray(blob)
            changed[pos] ^= 1
            with pytest.raises(fileformat.BackupFileError):
                _decrypt(bytes(changed), keys={"k1": self.key})

    def test_a_changed_header_is_detected(self):
        blob = _encrypt(b"data" * 100, self.src)
        header, raw = fileformat.read_header(io.BytesIO(blob))
        header["info"] = {"site": "other"}
        new_header = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        forged = fileformat.MAGIC + len(new_header).to_bytes(4, "big") + new_header + blob[len(raw):]
        with pytest.raises(fileformat.BackupFileError):
            _decrypt(forged, keys={"k1": self.key})

    def test_cut_off_swapped_and_extra_chunks_are_detected(self):
        blob = _encrypt(os.urandom(3 * 4096 + 10), self.src, chunk=4096)
        header_len = len(fileformat.read_header(io.BytesIO(blob))[1])
        block = 4096 + 16
        chunks = [blob[header_len + i:header_len + i + block] for i in range(0, len(blob) - header_len, block)]
        head = blob[:header_len]
        with pytest.raises(fileformat.BackupFileError, match="cut off"):
            _decrypt(head + b"".join(chunks[:2]), keys={"k1": self.key})
        with pytest.raises(fileformat.BackupFileError):
            _decrypt(head + chunks[1] + chunks[0] + b"".join(chunks[2:]), keys={"k1": self.key})
        with pytest.raises(fileformat.BackupFileError):
            _decrypt(blob + chunks[0], keys={"k1": self.key})
        with pytest.raises(fileformat.BackupFileError, match="cut off"):
            _decrypt(head, keys={"k1": self.key})

    def test_not_a_backup(self):
        with pytest.raises(fileformat.BackupFileError, match="not an Anish1989 backup"):
            _decrypt(b"PGDMP not ours")

    def test_archive_round_trip(self, tmp_path):
        data_file = tmp_path / "database.dump"
        data_file.write_bytes(b"dump-bytes")
        out = io.BytesIO()
        fileformat.write_archive(out, self.src, info={"kind": "test"}, manifest={"tables": {"a.b": 2}}, files=[("database.dump", str(data_file))])
        manifest = fileformat.extract_archive(io.BytesIO(out.getvalue()), str(tmp_path / "out"), keys={"k1": self.key})
        assert manifest == {"tables": {"a.b": 2}}
        assert (tmp_path / "out" / "database.dump").read_bytes() == b"dump-bytes"

    def test_archive_cannot_write_outside_its_folder(self, tmp_path):
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as tar:
            evil = tarfile.TarInfo("../../escaped.txt")
            evil.size = 4
            tar.addfile(evil, io.BytesIO(b"evil"))
        blob = _encrypt(raw.getvalue(), self.src)
        with pytest.raises(fileformat.BackupFileError, match="damaged"):
            fileformat.extract_archive(io.BytesIO(blob), str(tmp_path / "out" / "x"), keys={"k1": self.key})
        assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "out" / "escaped.txt").exists()

    def test_stand_alone_tool(self, tmp_path):
        out = io.BytesIO()
        data_file = tmp_path / "database.dump"
        data_file.write_bytes(b"dump")
        fileformat.write_archive(out, self.src, info={"kind": "platform"}, manifest={"site_name": "Platform", "tables": {}},
                                 files=[("database.dump", str(data_file))])
        (tmp_path / "b.a1989backup").write_bytes(out.getvalue())
        tool = Path(fileformat.__file__)
        env = {**os.environ, "BACKUP_ENCRYPTION_KEYS": "k1:" + base64.b64encode(self.key).decode()}
        run = subprocess.run([sys.executable, "-I", str(tool), "decrypt", str(tmp_path / "b.a1989backup"), str(tmp_path / "o")],
                             env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
        assert run.returncode == 0, run.stdout + run.stderr
        assert (tmp_path / "o" / "database.dump").read_bytes() == b"dump"
        info = subprocess.run([sys.executable, "-I", str(tool), "info", str(tmp_path / "b.a1989backup")], capture_output=True, text=True, timeout=60)
        assert '"protected_with": "key"' in info.stdout and "dump" not in info.stdout
        env["BACKUP_ENCRYPTION_KEYS"] = "k1:" + base64.b64encode(new_key()).decode()
        bad = subprocess.run([sys.executable, "-I", str(tool), "decrypt", str(tmp_path / "b.a1989backup"), str(tmp_path / "o2")],
                             env=env, capture_output=True, text=True, timeout=60)
        assert bad.returncode == 1 and "Wrong key" in bad.stdout

    def test_tool_has_no_django(self):
        source = Path(fileformat.__file__).read_text()
        assert "django" not in source.lower().replace("no django code", "")


class TestKeys:
    def test_platform_key_needed_without_debug(self, settings):
        settings.BACKUP_ENCRYPTION_KEYS = ""
        settings.DEBUG = False
        with pytest.raises(ImproperlyConfigured, match="BACKUP_ENCRYPTION_KEYS"):
            keys.platform_keys()
        settings.DEBUG = True
        assert list(keys.platform_keys()) == [keys.DEV_KEY_ID] and keys.using_dev_key()

    def test_first_key_encrypts_and_old_keys_still_open(self, settings):
        old, new = new_key(), new_key()
        settings.BACKUP_ENCRYPTION_KEYS = f"b2:{base64.b64encode(new).decode()},b1:{base64.b64encode(old).decode()}"
        assert keys.platform_source().key_id == "b2"
        blob = _encrypt(b"old", fileformat.KeySource(key_id="b1", key=old))
        assert _decrypt(blob, keys=keys.platform_keys()) == b"old"

    def test_bad_key_format(self, settings):
        settings.BACKUP_ENCRYPTION_KEYS = "b1:c2hvcnQ="
        with pytest.raises(ImproperlyConfigured, match="32 bytes"):
            keys.platform_keys()

    def test_passphrases(self):
        made = keys.generate_passphrase()
        parts = made.split("-")
        assert len(parts) == 7 and parts[-1].isdigit() and all(p in keys.WORDS for p in parts[:-1])
        assert keys.generate_passphrase() != made
        keys.check_passphrase(made)
        for weak in ("short", "aaaaaaaaaaaaaaaaaaaa"):
            with pytest.raises(ValidationError):
                keys.check_passphrase(weak)


# ---------------------------------------------------------------------------
# 2. Which old backups are kept
# ---------------------------------------------------------------------------
class TestRetention:
    def test_keeps_recent_then_daily_then_monthly(self):
        now = timezone.now()
        items = [(f"h{i}", now - timedelta(hours=6 * i)) for i in range(4 * 400)]  # every 6 hours for 400 days
        keep = retention.to_keep(items, now=now, all_days=7, daily_days=30, monthly=12)
        recent = [i for i, t in items if now - t <= timedelta(days=7)]
        assert set(recent) <= keep
        daily = {timezone.localtime(t).date() for i, t in items if i in keep and timedelta(days=7) < now - t <= timedelta(days=30)}
        assert len([i for i, t in items if i in keep and timedelta(days=7) < now - t <= timedelta(days=30)]) == len(daily)
        old = [t for i, t in items if i in keep and now - t > timedelta(days=30)]
        assert len(old) <= 12 and len({(timezone.localtime(t).year, timezone.localtime(t).month) for t in old}) == len(old)
        assert all(now - t < timedelta(days=370) for i, t in items if i in keep)
        assert len(keep) < 28 + 23 + 12 + 2

    def test_newest_is_always_kept(self):
        now = timezone.now()
        assert retention.to_keep([("old", now - timedelta(days=900))], now=now, all_days=7, daily_days=30, monthly=12) == {"old"}
        assert retention.to_keep([], now=now, all_days=7, daily_days=30, monthly=12) == set()


# ---------------------------------------------------------------------------
# 3. Real backups and restore tests (pg_dump and pg_restore on the test database)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPlatformBackup:
    def test_backup_and_restore_test(self, public_tenant, settings):
        run = backup()
        assert run.status == "ok", run.message
        path = Path(settings.BACKUP_DIR) / "platform" / run.file_name
        assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
        assert run.size_bytes == path.stat().st_size and run.sha256 == fileformat.sha256_file(str(path))
        assert b"PGDMP" not in path.read_bytes()  # the dump inside is encrypted
        assert run.details["tables"] > 50 and "Kept on the server" in run.message
        manifest, folder = open_file(path, keys=platform_keys_now())
        assert manifest["kind"] == "platform" and any(t.startswith("tenant_a.") for t in manifest["tables"])
        assert any(t.startswith("tenant_b.") for t in manifest["tables"]) and any(t.startswith("public.") for t in manifest["tables"])
        assert AuditEvent.objects.filter(action="backup.made", outcome="success").exists()

        test = backup(kind=KIND.RESTORE_TEST)
        assert test.status == "ok", test.message
        assert test.tested_backup_id == run.pk and test.details["loaded"] is True
        assert test.details["tables"] == run.details["tables"] and test.details["rows"] == run.details["rows"]
        assert "Restore test passed" in test.message and "this server" in test.message
        assert AuditEvent.objects.filter(action="backup.restore_tested", outcome="success").exists()
        with dbtools.connect(autocommit=True) as c, c.cursor() as cur:  # the temporary database is gone
            cur.execute("SELECT count(*) FROM pg_database WHERE datname LIKE 'a1989\\_restoretest\\_%%'")
            assert cur.fetchone()[0] == 0

    def test_changed_file_fails_the_restore_test(self, public_tenant, settings):
        run = backup()
        path = Path(settings.BACKUP_DIR) / "platform" / run.file_name
        data = bytearray(path.read_bytes())
        data[-10] ^= 1
        path.write_bytes(bytes(data))
        test = backup(kind=KIND.RESTORE_TEST)
        assert test.status == "failed" and "has changed since it was made" in test.message

    def test_differences_are_reported(self, public_tenant, monkeypatch):
        backup()
        real = dbtools.count_rows

        def fewer(cur, schemas):
            found = real(cur, schemas)
            found.pop(next(iter(found)))
            found["public.tenants_tenant"] -= 1
            return found

        monkeypatch.setattr(dbtools, "count_rows", fewer)
        monkeypatch.setattr(services.dbtools, "count_rows", fewer)
        test = backup(kind=KIND.RESTORE_TEST)
        assert test.status == "failed" and "1 missing tables and 1 tables with different row counts" in test.message
        assert test.details["missing"] and test.details["different"][0][0] == "public.tenants_tenant"

    def test_restore_test_without_create_database_right(self, public_tenant, monkeypatch):
        backup()
        read = []

        def denied(path):
            raise dbtools.CannotCreateDatabase("The database user may not create databases.")

        monkeypatch.setattr(dbtools, "restored_copy", denied)
        monkeypatch.setattr(dbtools, "read_all_data", lambda path: read.append(path))
        test = backup(kind=KIND.RESTORE_TEST)
        assert test.status == "warning" and "CREATEDB" in test.message and read

    def test_missing_key_fails_with_a_clear_message(self, public_tenant, settings):
        settings.BACKUP_ENCRYPTION_KEYS = ""
        run = backup()
        assert run.status == "failed" and "BACKUP_ENCRYPTION_KEYS must be set" in run.message
        assert not list((Path(settings.BACKUP_DIR) / "platform").glob("*"))

    def test_old_pg_dump_is_explained(self, public_tenant, monkeypatch):
        monkeypatch.setattr(dbtools, "tool_major_version", lambda name="pg_dump": 15)
        run = backup()
        assert run.status == "failed" and "pg_dump is version 15" in run.message and "postgresql-client-16" in run.message

    def test_unexpected_errors_are_hidden(self, public_tenant, monkeypatch):
        monkeypatch.setattr(dbtools, "dump", lambda *a, **k: 1 / 0)
        run = backup()
        assert run.status == "failed" and "unexpected error" in run.message and "Zero" not in run.message
        assert not list((Path(services.settings.BACKUP_DIR) / "tmp").glob("work-*"))  # temporary files removed

    def test_media_files_are_included(self, public_tenant, settings):
        media = Path(settings.MEDIA_ROOT) / "tenant_a" / "products"
        media.mkdir(parents=True)
        (media / "photo.jpg").write_bytes(b"jpeg")
        run = backup()
        manifest, folder = open_file(Path(settings.BACKUP_DIR) / "platform" / run.file_name, keys=platform_keys_now())
        assert manifest["media"]["files"] == 1 and (folder / "media" / "tenant_a" / "products" / "photo.jpg").read_bytes() == b"jpeg"

    def test_old_server_copies_are_removed(self, public_tenant, settings):
        folder = Path(settings.BACKUP_DIR) / "platform"
        folder.mkdir(parents=True)
        now = timezone.now()
        old = []
        with schema_context("public"):
            for days in (1, 2, 10, 10.1, 45, 46, 800):
                name = f"platform-old-{days}.a1989backup"
                (folder / name).write_bytes(b"x")
                old.append(BackupRun.objects.create(kind=KIND.BACKUP, trigger=SCHED, status="ok", queued_at=now - timedelta(days=days),
                                                    file_name=name, kept_locally=True, size_bytes=1))
        run = backup()
        names = {p.name for p in folder.glob("*.a1989backup")}
        assert run.file_name in names
        assert {"platform-old-1.a1989backup", "platform-old-2.a1989backup", "platform-old-10.a1989backup", "platform-old-45.a1989backup"} <= names
        assert "platform-old-10.1.a1989backup" not in names and "platform-old-800.a1989backup" not in names
        assert run.details["cleanup"]["server"] == 3

    def test_one_run_at_a_time(self, public_tenant):
        from django.core.cache import cache

        with schema_context("public"):
            cache.add(services.LOCK_KEY, 1, 60)
            run = backup()
        assert run.status == "failed" and "Another backup" in run.message

    def test_a_stuck_run_is_closed_after_four_hours(self, public_tenant):
        with schema_context("public"):
            stuck = BackupRun.objects.create(kind=KIND.BACKUP, trigger=BUTTON, status="running", queued_at=timezone.now() - timedelta(hours=5))
            assert services.active_run() is None
            stuck.refresh_from_db()
        assert stuck.status == "failed" and "did not finish" in stuck.message


@pytest.mark.django_db
class TestBusinessBackup:
    def test_needs_drive_and_passphrase(self, tenant_a, google):
        with schema_context("tenant_a"):
            assert not services.is_set_up()
            with pytest.raises(ValidationError, match="Connect Google Drive and set a backup passphrase"):
                services.queue(KIND.BACKUP)
            assert services.run_due() == []
        connect_drive("tenant_a", google, passphrase="")
        with schema_context("tenant_a"):
            assert not services.is_set_up()
            services.set_passphrase(GOOD_PASSPHRASE)
            assert services.is_set_up()

    def test_only_its_own_data_locked_with_its_passphrase(self, tenant_a, google, settings):
        connect_drive("tenant_a", google)
        run = backup("tenant_a")
        assert run.status == "ok", run.message
        assert run.drive_status == "uploaded" and "Copied to Google Drive" in run.message
        path = Path(settings.BACKUP_DIR) / "businesses" / "tenant_a" / run.file_name
        assert run.file_name.startswith("tenant_a-")
        manifest, _ = open_file(path, passphrase=GOOD_PASSPHRASE)
        assert manifest["schema"] == "tenant_a" and manifest["tables"]
        assert all(t.startswith("tenant_a.") for t in manifest["tables"])  # no other business, no platform data
        with pytest.raises(fileformat.BackupFileError):
            open_file(path, keys=platform_keys_now())  # the platform key does not open a business's backup
        uploaded = google.uploaded()
        assert len(uploaded) == 1 and uploaded[0]["data"] == path.read_bytes() and uploaded[0]["name"] == run.file_name

    def test_passphrase_is_stored_encrypted_and_audited_without_it(self, tenant_a):
        with schema_context("tenant_a"):
            services.set_passphrase(GOOD_PASSPHRASE)
            row = BackupSettings.objects.get()
            assert GOOD_PASSPHRASE.encode() not in bytes(row.passphrase_ciphertext)
            assert services.read_passphrase() == GOOD_PASSPHRASE
            events = AuditEvent.objects.filter(action="backup.passphrase_set")
            assert events.exists() and GOOD_PASSPHRASE not in json.dumps(list(events.values("metadata", "target_repr")), default=str)
        with schema_context("tenant_b"):  # copied to another business, it cannot be opened
            other = BackupSettings.objects.create(pk=1, passphrase_kid=row.passphrase_kid, passphrase_wrapped_key=row.passphrase_wrapped_key,
                                                  passphrase_key_nonce=row.passphrase_key_nonce, passphrase_nonce=row.passphrase_nonce,
                                                  passphrase_ciphertext=row.passphrase_ciphertext)
            assert other.has_passphrase
            from apps.vault.crypto import VaultError

            with pytest.raises(VaultError):
                services.read_passphrase()

    def test_restore_test_uses_the_google_drive_copy(self, tenant_a, google, settings):
        connect_drive("tenant_a", google)
        run = backup("tenant_a")
        (Path(settings.BACKUP_DIR) / "businesses" / "tenant_a" / run.file_name).unlink()  # only the Drive copy is left
        test = backup("tenant_a", kind=KIND.RESTORE_TEST)
        assert test.status == "ok", test.message
        assert test.details["source"] == "Google Drive" and "taken from Google Drive" in test.message

    def test_failed_drive_copy_fails_a_business_backup_but_only_warns_the_platform(self, tenant_a, public_tenant, google):
        connect_drive("tenant_a", google)
        connect_drive("public", google)
        google.bad_md5 = True
        run = backup("tenant_a")
        assert run.status == "failed" and "did not match" in run.message and run.drive_status == "failed"
        assert google.uploaded() == []  # the bad copy was removed
        assert backup("public").status == "warning"

    def test_upload_resumes_after_google_errors(self, public_tenant, google, monkeypatch):
        monkeypatch.setattr(gdrive, "PART_SIZE", 256 * 1024)
        media = Path(services.settings.MEDIA_ROOT) / "big.bin"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(os.urandom(700 * 1024))
        connect_drive("public", google)
        google.fail_puts = 2
        run = backup()
        assert run.status == "ok" and run.drive_status == "uploaded", run.message
        assert google.uploaded()[0]["data"] == (Path(services.settings.BACKUP_DIR) / "platform" / run.file_name).read_bytes()

    def test_only_the_newest_business_backup_stays_on_the_server(self, tenant_a, google, settings):
        connect_drive("tenant_a", google)
        first = backup("tenant_a")
        second = backup("tenant_a")
        assert first.file_name != second.file_name  # even within the same second
        files = list((Path(settings.BACKUP_DIR) / "businesses" / "tenant_a").glob("*.a1989backup"))
        assert [f.name for f in files] == [second.file_name]
        with schema_context("tenant_a"):
            first.refresh_from_db()
        assert not first.kept_locally and len(google.uploaded()) == 2

    def test_old_drive_copies_are_removed(self, tenant_a, google):
        connect_drive("tenant_a", google)
        backup("tenant_a")
        with schema_context("tenant_a"):
            folder_id = services.site_settings().drive_folder_id
        for days in (3, 20, 20.2, 400):
            google.files[f"oldfile{int(days * 10):06d}"] = {
                "name": f"old-{days}.a1989backup", "parents": [folder_id], "data": b"x", "trashed": False,
                "createdTime": (timezone.now() - timedelta(days=days)).isoformat().replace("+00:00", "Z")}
        google.files["notours000001"] = {"name": "holiday.jpg", "parents": [folder_id], "data": b"x", "trashed": False,
                                         "createdTime": (timezone.now() - timedelta(days=900)).isoformat()}
        run = backup("tenant_a")
        names = {f["name"] for f in google.files.values() if not f.get("folder")}
        assert {"old-3.a1989backup", "old-20.a1989backup", "holiday.jpg", run.file_name} <= names
        assert "old-20.2.a1989backup" not in names and "old-400.a1989backup" not in names
        assert run.details["cleanup"]["drive"] == 2

    def test_removed_google_access_pauses_copies_and_alerts_once(self, tenant_a, google):
        user = make_user("tenant_a", "it@a.test", staff=True)
        give_role("tenant_a", user, "it_admin")
        connect_drive("tenant_a", google)
        google.revoked.add("rt-good")
        run = backup("tenant_a", trigger=SCHED)
        assert run.status == "failed" and run.drive_status == "paused" and "Connect Google Drive again" in run.message
        assert len(alerts()) == 1 and alerts()[0].to == ["it@a.test"] and "Backup needs attention" in alerts()[0].subject
        assert "rt-good" not in alerts()[0].body
        with schema_context("tenant_a"):
            s = services.site_settings()
            assert s.drive_paused_reason and services.drive_connection().status == "failed"
            BackupRun.objects.update(queued_at=timezone.now() - timedelta(hours=7))  # a backup would be due now
            assert services.run_due() == []  # but nothing runs while paused
            assert AuditEvent.objects.filter(action="backup.drive_paused").count() == 1
        connect_drive("tenant_a", google, passphrase="", refresh="rt-new")
        with schema_context("tenant_a"):
            assert services.site_settings().drive_paused_reason == ""
        assert backup("tenant_a").status == "ok"


# ---------------------------------------------------------------------------
# 4. Schedule and alerts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSchedule:
    def test_first_run_makes_a_backup_and_a_restore_test(self, public_tenant):
        with schema_context("public"):
            assert services.run_due() == ["backup ok", "restore test ok"]
            assert services.run_due() == []  # not due again yet
            last = BackupRun.objects.filter(kind=KIND.BACKUP).get()
            last.queued_at -= timedelta(hours=6)
            last.save()
            assert services.run_due() == ["backup ok"]

    def test_every_hours_setting(self, public_tenant):
        with schema_context("public"):
            services.update_settings(every_hours=24)
            BackupRun.objects.create(kind=KIND.BACKUP, trigger=SCHED, status="ok", queued_at=timezone.now() - timedelta(hours=7), sha256="x")
            assert services.next_backup_due() > timezone.now()
            with pytest.raises(ValidationError):
                services.update_settings(every_hours=3)

    def test_failed_backup_is_retried_after_an_hour(self, public_tenant):
        with schema_context("public"):
            BackupRun.objects.create(kind=KIND.BACKUP, trigger=SCHED, status="failed", queued_at=timezone.now() - timedelta(minutes=30))
            assert services.next_backup_due() > timezone.now()
            BackupRun.objects.update(queued_at=timezone.now() - timedelta(minutes=61))
            assert services.next_backup_due() <= timezone.now()

    def test_restore_test_every_seven_days(self, public_tenant, settings):
        with schema_context("public"):
            assert services.next_restore_test_due() is None  # nothing to test yet
            BackupRun.objects.create(kind=KIND.BACKUP, trigger=SCHED, status="ok", queued_at=timezone.now())
            assert services.next_restore_test_due() <= timezone.now()
            BackupRun.objects.create(kind=KIND.RESTORE_TEST, trigger=SCHED, status="ok", queued_at=timezone.now() - timedelta(days=6))
            assert services.next_restore_test_due() > timezone.now()
            settings.BACKUP_RESTORE_TEST_EVERY_DAYS = 5
            assert services.next_restore_test_due() <= timezone.now()

    def test_alert_only_when_a_scheduled_run_starts_failing(self, public_tenant, monkeypatch, client_for):
        make_user("public", "root@platform.test", superuser=True)
        monkeypatch.setattr(dbtools, "dump", lambda *a, **k: (_ for _ in ()).throw(dbtools.DatabaseToolError("Disk full.")))
        assert backup(trigger=BUTTON).status == "failed"
        assert alerts() == []  # a button run is watched by the person who clicked
        assert backup(trigger=SCHED).alert_sent is False  # already failing: no new email
        with schema_context("public"):
            BackupRun.objects.filter(status="failed").update(status="ok")
        run = backup(trigger=SCHED)
        assert run.alert_sent and len(alerts()) == 1 and alerts()[0].to == ["root@platform.test"]
        assert "Disk full." in alerts()[0].body and "/backups/" in alerts()[0].body
        assert backup(trigger=SCHED).alert_sent is False and len(alerts()) == 1

    def test_run_everywhere(self, public_tenant, tenant_a, tenant_b, google):
        from apps.licensing.services import suspend

        connect_drive("tenant_a", google)
        connect_drive("tenant_b", google)
        suspend(tenant_b, "test")
        summary = tasks.scheduled()
        assert summary["public"][0] == "backup ok" and summary["tenant_a"][0] == "backup ok"
        assert "tenant_b" not in summary
        with schema_context("tenant_b"):
            assert not BackupRun.objects.exists()

    def test_queued_button_run_is_done_by_the_worker(self, public_tenant, no_real_tasks, django_capture_on_commit_callbacks):
        user = make_user("public", "root@platform.test", superuser=True)
        with schema_context("public"):
            with django_capture_on_commit_callbacks(execute=True):
                run = services.queue(KIND.BACKUP, user=user)
            assert no_real_tasks == [("public", run.pk)]
            with pytest.raises(ValidationError, match="already running"):
                services.queue(KIND.BACKUP, user=user)
        tasks.run_task("public", run.pk)
        run.refresh_from_db()
        assert run.status == "ok" and run.run_by_email == "root@platform.test"
        tasks.run_task("public", run.pk)  # a repeated task does nothing
        with schema_context("public"):
            assert BackupRun.objects.count() == 1
            with pytest.raises(ValidationError, match="no backup to test"):
                BackupRun.objects.all().delete()
                services.queue(KIND.RESTORE_TEST, user=user)


# ---------------------------------------------------------------------------
# 5. Connect Google Drive (OAuth)
# ---------------------------------------------------------------------------
def it_admin(client_for, tenant, email="it@a.test"):
    return verified_staff_client(client_for, tenant, email, "it_admin")


def start_connect(client, password=PASSWORD):
    return client.post("/backups/", {"action": "connect", "password": password})


@pytest.mark.django_db
class TestConnectGoogleDrive:
    def test_full_sign_in(self, client_for, tenant_a, public_tenant, google):
        sign_in_app("public")  # the platform's sign-in app is used by businesses without their own
        admin = it_admin(client_for, tenant_a)
        response = start_connect(admin)
        assert response.status_code == 302 and response["Location"].startswith(gdrive.AUTH_URL)
        q = parse_qs(urlparse(response["Location"]).query)
        assert q["client_id"] == ["cid.apps"] and q["scope"] == [gdrive.SCOPE] and q["code_challenge_method"] == ["S256"]
        assert q["access_type"] == ["offline"] and q["redirect_uri"][0].endswith("/oauth/google/callback/")
        assert urlparse(q["redirect_uri"][0]).hostname == host_of(public_tenant)

        back = client_for(public_tenant).get("/oauth/google/callback/", {"state": q["state"][0], "code": "abc"})
        assert back.status_code == 302
        target = urlparse(back["Location"])
        assert target.hostname == host_of(tenant_a) and target.path == "/backups/google/finish/"
        assert google.last_verifier and hashlib.sha256(google.last_verifier.encode()).digest() == base64.urlsafe_b64decode(q["code_challenge"][0] + "==")

        done = admin.get(f"{target.path}?{target.query}", follow=True)
        page = done.content.decode()
        assert "Google Drive connected (owner@gmail.test)" in page
        assert "rt-abc" not in page and google.secret not in page
        with schema_context("tenant_a"):
            conn = Connection.objects.get(provider="google_drive")
            assert vault.read_secrets(conn)["refresh_token"] == "rt-abc"
            assert "rt-abc" not in json.dumps(conn.config) and conn.status == "connected"
            assert services.site_settings().drive_folder_id  # the folder was made
            assert AuditEvent.objects.filter(action="backup.drive_connected").exists()
            assert "rt-abc" not in json.dumps(list(AuditEvent.objects.values("metadata")), default=str)
        with schema_context("public"):
            assert not Connection.objects.filter(provider="google_drive").exists()  # the platform's own Drive is separate

    def test_wrong_password_does_not_start(self, client_for, tenant_a, public_tenant, google):
        sign_in_app("public")
        response = start_connect(it_admin(client_for, tenant_a), password="wrong")
        assert response.status_code == 302 and response["Location"] == "/backups/"

    def test_no_sign_in_app(self, client_for, tenant_a, google):
        page = start_connect(it_admin(client_for, tenant_a)).wsgi_request
        admin = it_admin(client_for, tenant_a, "it2@a.test")
        page = admin.get("/backups/").content.decode()
        assert "the platform's Google sign-in app is not set up" in page
        response = admin.post("/backups/", {"action": "connect", "password": PASSWORD}, follow=True)
        assert "cannot be connected yet" in response.content.decode()

    def test_a_business_can_use_its_own_sign_in_app(self, client_for, tenant_a, public_tenant, google):
        sign_in_app("public")
        with schema_context("tenant_a"):
            vault.create_connection(provider_code="google_oauth_app", label="Own app", config={"client_id": "own.apps"}, secrets={"client_secret": google.secret})
        q = parse_qs(urlparse(start_connect(it_admin(client_for, tenant_a))["Location"]).query)
        assert q["client_id"] == ["own.apps"]

    def _started(self, client_for, tenant, public_tenant, google, email="it@a.test"):
        sign_in_app("public")
        admin = it_admin(client_for, tenant, email)
        state = parse_qs(urlparse(start_connect(admin)["Location"]).query)["state"][0]
        return admin, state

    def test_bad_or_reused_state(self, client_for, tenant_a, public_tenant, google):
        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        platform = client_for(public_tenant)
        bad = platform.get("/oauth/google/callback/", {"state": state + "x", "code": "abc"})
        assert bad.status_code == 400 and "not valid or has expired" in bad.content.decode()
        assert platform.get("/oauth/google/callback/", {"state": state, "code": "abc"}).status_code == 302
        again = platform.get("/oauth/google/callback/", {"state": state, "code": "abc"})
        assert again.status_code == 400 and "already used" in again.content.decode()

    def test_cancelled_at_google(self, client_for, tenant_a, public_tenant, google):
        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        back = client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "error": "access_denied"})
        assert back.status_code == 302 and back["Location"].endswith("/backups/?google=cancelled")
        assert "was not connected" in admin.get("/backups/?google=cancelled").content.decode()

    def test_only_the_same_person_in_the_same_browser_can_finish(self, client_for, tenant_a, tenant_b, public_tenant, google):
        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        back = urlparse(client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "code": "abc"})["Location"])
        finish = f"{back.path}?{back.query}"
        other = it_admin(client_for, tenant_a, "other@a.test")  # same business, different person and browser
        assert "did not start in this browser" in other.get(finish, follow=True).content.decode()
        elsewhere = it_admin(client_for, tenant_b, "it@b.test")  # another business
        assert "did not start in this browser" in elsewhere.get(finish, follow=True).content.decode()
        with schema_context("tenant_a"):
            assert not Connection.objects.filter(provider="google_drive").exists()
        with schema_context("tenant_b"):
            assert not Connection.objects.filter(provider="google_drive").exists()
        assert "Google Drive connected" in admin.get(finish, follow=True).content.decode()  # the right person still can

    def test_finishing_in_another_business_is_refused(self, client_for, tenant_a, tenant_b, public_tenant, google):
        """Even with the right session value, a sign-in started for one business cannot be saved in another."""
        from types import SimpleNamespace

        from django.test import RequestFactory

        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "code": "abc"})
        nonce = google_connect._nonce_from(state)
        with schema_context("tenant_a"):
            from apps.accounts.models import User

            user_id = User.objects.get(email="it@a.test").pk
        request = RequestFactory().get("/backups/google/finish/", {"state": state})
        request.session = {google_connect.SESSION_KEY: nonce}
        request.user = SimpleNamespace(pk=user_id, email="it@a.test")
        with schema_context("tenant_b"):
            with pytest.raises(ValidationError, match="belongs to someone else"):
                google_connect.finish(request)
            assert not Connection.objects.filter(provider="google_drive").exists()

    def test_session_from_another_flow_cannot_finish_this_one(self, client_for, tenant_a, public_tenant, google):
        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        attacker, attacker_state = self._started(client_for, tenant_a, public_tenant, google, "evil@a.test")
        back = urlparse(client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "code": "abc"})["Location"])
        assert "did not start in this browser" in attacker.get(f"{back.path}?{back.query}", follow=True).content.decode()

    @pytest.mark.parametrize("problem,message", [("no_refresh", "lasting access"), ("no_scope", "tick the Google Drive permission")])
    def test_google_problems_are_shown(self, client_for, tenant_a, public_tenant, google, problem, message):
        setattr(google, problem, True)
        admin, state = self._started(client_for, tenant_a, public_tenant, google)
        back = urlparse(client_for(public_tenant).get("/oauth/google/callback/", {"state": state, "code": "abc"})["Location"])
        assert message in admin.get(f"{back.path}?{back.query}", follow=True).content.decode()
        with schema_context("tenant_a"):
            assert not Connection.objects.filter(provider="google_drive").exists()

    def test_disconnect_needs_the_password_and_revokes_access(self, client_for, tenant_a, google):
        connect_drive("tenant_a", google)
        admin = it_admin(client_for, tenant_a)
        admin.post("/backups/", {"action": "disconnect", "password": "wrong"})
        with schema_context("tenant_a"):
            assert services.drive_connection() is not None
        page = admin.post("/backups/", {"action": "disconnect", "password": PASSWORD}, follow=True).content.decode()
        assert "Google Drive disconnected" in page and "rt-good" in google.revoked
        with schema_context("tenant_a"):
            assert services.drive_connection() is None and not services.is_set_up()
            assert AuditEvent.objects.filter(action="backup.drive_disconnected").exists()

    def test_drive_cannot_be_added_or_changed_on_the_integrations_page(self, tenant_a):
        with schema_context("tenant_a"):
            with pytest.raises(ValidationError, match="Backups page"):
                vault.create_connection(provider_code="google_drive", label="x", config={"client_id": "c"},
                                        secrets={"refresh_token": "r", "client_secret": "s"})
            conn = services.save_drive_connection(client_id="c", client_secret="s", refresh_token="r", email="a@gmail.test")
            with pytest.raises(ValidationError, match="only the name"):
                vault.update_connection(conn, secrets={"refresh_token": "attacker"})
            vault.update_connection(conn, label="Our Drive")  # a new name is fine

    def test_integrations_page_links_to_backups_and_shows_the_redirect_uri(self, client_for, public_tenant, google):
        from tests.test_mfa_admin import platform_staff

        sign_in_app("public")
        page = platform_staff(client_for, public_tenant, "root@platform.test", "super_admin").get("/settings/integrations/").content.decode()
        assert 'href="/backups/">Google Drive (backup copies)' in page
        assert "/oauth/google/callback/" in page

    def test_sign_in_app_test_button(self, google):
        from apps.vault import providers

        assert providers.test_google_oauth_app({"client_secret": google.secret}, {"client_id": "c"}).ok
        assert not providers.test_google_oauth_app({"client_secret": "wrong"}, {"client_id": "c"}).ok
        assert providers.test_google_drive({"client_secret": google.secret, "refresh_token": "rt"}, {"client_id": "c"}).message.endswith("(owner@gmail.test).")
        google.revoked.add("rt")
        assert "Connect Google Drive again" in providers.test_google_drive({"client_secret": google.secret, "refresh_token": "rt"}, {"client_id": "c"}).message


# ---------------------------------------------------------------------------
# 6. Backups page, API and permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPage:
    def test_who_may_see_and_use_it(self, client_for, tenant_a):
        shop = verified_staff_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        assert shop.get("/backups/").status_code == 403
        assert shop.post("/backups/", {"action": "backup"}).status_code == 403
        assert shop.get("/backups/tool/").status_code == 403
        owner = verified_staff_client(client_for, tenant_a, "owner@a.test", "business_owner")
        page = owner.get("/backups/")
        assert page.status_code == 200 and 'value="Back up now"' not in page.content.decode()
        assert owner.post("/backups/", {"action": "backup"}).status_code == 403
        assert it_admin(client_for, tenant_a).get("/backups/").status_code == 200

    def test_set_up_steps_and_passphrase(self, client_for, tenant_a, google):
        admin = it_admin(client_for, tenant_a)
        page = admin.get("/backups/").content.decode()
        assert "Set up backups to your Google Drive" in page and "Make a passphrase for me" in page
        wrong = admin.post("/backups/", {"action": "passphrase", "password": "nope", "generate": "1"}, follow=True)
        assert "password is not correct" in wrong.content.decode()
        made = admin.post("/backups/", {"action": "passphrase", "password": PASSWORD, "generate": "1"})
        assert made.status_code == 200 and "no-store" in made["Cache-Control"]
        with schema_context("tenant_a"):
            passphrase = services.read_passphrase()
        assert passphrase in made.content.decode() and "shown only this once" in made.content.decode()
        assert passphrase not in admin.get("/backups/").content.decode()
        own = admin.post("/backups/", {"action": "passphrase", "password": PASSWORD, "passphrase": GOOD_PASSPHRASE, "passphrase_again": "different-but-long-x"}, follow=True)
        assert "not the same" in own.content.decode()
        saved = admin.post("/backups/", {"action": "passphrase", "password": PASSWORD, "passphrase": GOOD_PASSPHRASE, "passphrase_again": GOOD_PASSPHRASE})
        assert GOOD_PASSPHRASE not in saved.content.decode() and "Older backups still need the old one" in saved.content.decode()

    def test_buttons_settings_and_history(self, client_for, tenant_a, google, no_real_tasks, django_capture_on_commit_callbacks):
        connect_drive("tenant_a", google)
        admin = it_admin(client_for, tenant_a)
        with django_capture_on_commit_callbacks(execute=True):
            assert "Started." in admin.post("/backups/", {"action": "backup"}, follow=True).content.decode()
        assert len(no_real_tasks) == 1
        page = admin.get("/backups/").content.decode()
        assert 'http-equiv="refresh"' in page and "waiting to start" in page
        assert "already running" in admin.post("/backups/", {"action": "backup"}, follow=True).content.decode()
        tasks.run_task(*no_real_tasks[0])
        page = admin.get("/backups/").content.decode()
        assert "Backup made" in page and "it@a.test" in page and 'http-equiv="refresh"' not in page
        admin.post("/backups/", {"action": "settings", "every_hours": "12", "folder_name": "Gorkha backups"})
        with schema_context("tenant_a"):
            s = services.site_settings()
            assert s.every_hours == 12 and s.drive_folder_name == "Gorkha backups" and s.drive_folder_id == ""
        assert "Choose every 6 hours" in admin.post("/backups/", {"action": "settings", "every_hours": "1"}, follow=True).content.decode()
        assert "cannot contain" in admin.post("/backups/", {"action": "settings", "every_hours": "6", "folder_name": "a/b"}, follow=True).content.decode()

    def test_platform_page(self, client_for, public_tenant, settings):
        from tests.test_mfa_admin import platform_staff

        backup()
        page = platform_staff(client_for, public_tenant, "root@platform.test", "super_admin").get("/backups/").content.decode()
        assert "whole platform (every business)" in page and "Encryption key: <code>b1</code>" in page
        assert "passphrase" not in page.lower().split("history")[0]
        settings.BACKUP_ENCRYPTION_KEYS = ""
        settings.DEBUG = True
        page = platform_staff(client_for, public_tenant, "root2@platform.test", "super_admin").get("/backups/").content.decode()
        assert "Development key" in page

    def test_backup_tool_download(self, client_for, tenant_a):
        response = it_admin(client_for, tenant_a).get("/backups/tool/")
        assert response.status_code == 200 and "anish1989-backup-tool.py" in response["Content-Disposition"]
        assert b"def extract_archive" in response.content

    def test_api(self, client_for, tenant_a, google, no_real_tasks, django_capture_on_commit_callbacks):
        from tests.test_vault import api_client

        shop = api_client(client_for, tenant_a, "shop@a.test", "shop_staff")
        assert shop.get("/api/backups/").status_code == 403
        owner = api_client(client_for, tenant_a, "owner@a.test", "business_owner")
        assert owner.get("/api/backups/").json()["set_up"] is False
        assert owner.post("/api/backups/run/", {"kind": "backup"}).status_code == 403
        it = api_client(client_for, tenant_a, "it@a.test", "it_admin")
        assert it.post("/api/backups/run/", {"kind": "backup"}).status_code == 409
        connect_drive("tenant_a", google)
        assert it.post("/api/backups/run/", {"kind": "nonsense"}).status_code == 400
        with django_capture_on_commit_callbacks(execute=True):
            assert it.post("/api/backups/run/", {"kind": "backup"}).status_code == 202
        tasks.run_task(*no_real_tasks[0])
        data = it.get("/api/backups/").json()
        assert data["set_up"] and data["last_backup"]["status"] == "ok" and data["google_drive"]["account"] == "owner@gmail.test"
        body = json.dumps(data)
        assert "rt-good" not in body and google.secret not in body and GOOD_PASSPHRASE not in body


# ---------------------------------------------------------------------------
# 7. Check system lines
# ---------------------------------------------------------------------------
def by_code(results, code):
    return next(r for r in results if r.code == code)


@pytest.mark.django_db
class TestCheckSystemLines:
    def test_platform(self, public_tenant, settings, google):
        with schema_context("public"):
            found = backup_checks.results()
            assert by_code(found, "backup_key").status == "ok" and by_code(found, "backups").status == "warning"
            assert by_code(found, "backups_drive").status == "warning" and by_code(found, "backups_restore").status == "warning"
        backup()
        backup(kind=KIND.RESTORE_TEST)
        with schema_context("public"):
            found = backup_checks.results()
            assert by_code(found, "backups").status == "ok" and by_code(found, "backups_restore").status == "ok"
            BackupRun.objects.filter(kind=KIND.BACKUP).update(queued_at=timezone.now() - timedelta(hours=8))
            assert by_code(backup_checks.results(), "backups").status == "warning"
            BackupRun.objects.filter(kind=KIND.BACKUP).update(queued_at=timezone.now() - timedelta(hours=14))
            assert by_code(backup_checks.results(), "backups").status == "failed"
        settings.BACKUP_ENCRYPTION_KEYS = ""
        with schema_context("public"):
            assert by_code(backup_checks.results(), "backup_key").status == "failed"

    def test_business(self, tenant_a, google):
        with schema_context("tenant_a"):
            assert [r.status for r in backup_checks.results()] == ["not_set_up"]
        connect_drive("tenant_a", google)
        backup("tenant_a")
        with schema_context("tenant_a"):
            found = backup_checks.results()
            assert by_code(found, "backups").status == "ok" and by_code(found, "backups_drive").status == "ok"
            assert "owner@gmail.test" in by_code(found, "backups_drive").message
        google.revoked.add("rt-good")
        backup("tenant_a")
        with schema_context("tenant_a"):
            found = backup_checks.results()
            assert by_code(found, "backups").status == "failed" and by_code(found, "backups_drive").status == "failed"

    def test_check_system_includes_them(self, public_tenant):
        from apps.health import checks

        with schema_context("public"):
            codes = [r.code for r in checks.platform_checks(live=False)]
        assert {"backup_key", "backups", "backups_drive", "backups_restore"} <= set(codes)
