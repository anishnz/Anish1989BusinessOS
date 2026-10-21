"""
PostgreSQL helpers for backups: pg_dump with exact row counts, and loading a
dump into a temporary database for the restore test.

- The database password goes to pg_dump and pg_restore in the PGPASSWORD
  environment variable, never on the command line.
- Row counts are taken inside the same snapshot that pg_dump uses, so the
  restore test can compare them exactly.
- Separate connections are used (not Django's), because CREATE DATABASE cannot
  run inside a transaction and the dump must see committed data only.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import shutil
import subprocess

import psycopg2
from django.db import connection
from django.utils import timezone
from psycopg2 import sql

log = logging.getLogger(__name__)
DUMP_TIMEOUT = 3 * 3600
TEST_DB_PREFIX = "a1989_restoretest_"
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema")


class DatabaseToolError(Exception):
    """A problem in plain words (technical details go to the server log)."""


def _params(dbname: str | None = None) -> dict:
    s = connection.settings_dict
    params = {"dbname": dbname or s["NAME"], "user": s.get("USER") or None, "password": s.get("PASSWORD") or None,
              "host": s.get("HOST") or None, "port": s.get("PORT") or None, "connect_timeout": 10}
    sslmode = (s.get("OPTIONS") or {}).get("sslmode")
    if sslmode:
        params["sslmode"] = sslmode
    return {k: v for k, v in params.items() if v is not None}


def connect(dbname: str | None = None, *, autocommit: bool = False):
    conn = psycopg2.connect(**_params(dbname))
    conn.autocommit = autocommit
    return conn


def _env() -> dict:
    s = connection.settings_dict
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    if s.get("PASSWORD"):
        env["PGPASSWORD"] = str(s["PASSWORD"])
    sslmode = (s.get("OPTIONS") or {}).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = sslmode
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


def _target_args(dbname: str) -> list[str]:
    s = connection.settings_dict
    args = []
    if s.get("HOST"):
        args += ["--host", str(s["HOST"])]
    if s.get("PORT"):
        args += ["--port", str(s["PORT"])]
    if s.get("USER"):
        args += ["--username", str(s["USER"])]
    return args + ["--no-password", "--dbname", dbname]


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise DatabaseToolError(f"The {name} program is not installed on the server (package postgresql-client).")
    return path


def tool_major_version(name: str = "pg_dump") -> int:
    out = subprocess.run([_tool(name), "--version"], capture_output=True, text=True, timeout=30).stdout
    match = re.search(r"(\d+)(?:\.\d+)?", out)
    return int(match.group(1)) if match else 0


def server_major_version() -> int:
    with contextlib.closing(connect()) as conn, conn.cursor() as cur:
        cur.execute("SHOW server_version_num")
        return int(cur.fetchone()[0]) // 10000


def check_tools() -> None:
    """pg_dump must be at least as new as the database server."""
    tool, server = tool_major_version("pg_dump"), server_major_version()
    if tool < server:
        raise DatabaseToolError(
            f"The server's pg_dump is version {tool}, but the database is version {server}. Install postgresql-client-{server}."
        )


def _tables(cur, schemas: list[str] | None) -> list[tuple[str, str]]:
    query = (
        "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind = 'r' AND n.nspname <> ALL(%s) AND n.nspname NOT LIKE 'pg\\_%%'"
    )
    args: list = [list(SYSTEM_SCHEMAS)]
    if schemas is not None:
        query += " AND n.nspname = ANY(%s)"
        args.append(list(schemas))
    cur.execute(query + " ORDER BY 1, 2", args)
    return list(cur.fetchall())


def count_rows(cur, schemas: list[str] | None) -> dict[str, int]:
    counts = {}
    for schema, table in _tables(cur, schemas):
        cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
        counts[f"{schema}.{table}"] = cur.fetchone()[0]
    return counts


def dump(path: str, *, schema: str | None = None) -> dict[str, int]:
    """
    pg_dump (custom format) of the whole database, or of one schema, to `path`.
    Returns {"schema.table": rows} counted in the same snapshot as the dump.
    """
    check_tools()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SELECT pg_export_snapshot()")
            snapshot = cur.fetchone()[0]
            counts = count_rows(cur, [schema] if schema else None)
            args = [_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", f"--snapshot={snapshot}", f"--file={path}"]
            if schema:
                args.append(f"--schema={schema}")
            result = subprocess.run(args + _target_args(connection.settings_dict["NAME"]), env=_env(), capture_output=True,
                                    text=True, timeout=DUMP_TIMEOUT)
        conn.rollback()
    finally:
        conn.close()
    if result.returncode != 0:
        log.error("pg_dump failed: %s", result.stderr.strip()[:2000])
        raise DatabaseToolError("The database could not be copied (pg_dump failed). Details are in the server log.")
    return counts


def check_archive(path: str) -> int:
    """pg_restore --list: the dump's table of contents can be read. Returns the number of entries."""
    result = subprocess.run([_tool("pg_restore"), "--list", path], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log.error("pg_restore --list failed: %s", result.stderr.strip()[:2000])
        raise DatabaseToolError("The database copy inside the backup is damaged.")
    return sum(1 for line in result.stdout.splitlines() if line and not line.startswith(";"))


def read_all_data(path: str) -> None:
    """Read every table's data from the dump without loading it anywhere."""
    result = subprocess.run([_tool("pg_restore"), "--file=/dev/null", path], capture_output=True, text=True, timeout=DUMP_TIMEOUT)
    if result.returncode != 0:
        log.error("pg_restore read failed: %s", result.stderr.strip()[:2000])
        raise DatabaseToolError("The data inside the backup could not be read.")


class CannotCreateDatabase(DatabaseToolError):
    pass


def _drop(dbname: str) -> None:
    with contextlib.closing(connect(autocommit=True)) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname)))


def drop_old_test_databases(older_than_hours: int = 6) -> int:
    """Remove temporary restore-test databases left behind by a crash."""
    cutoff = (timezone.now() - timezone.timedelta(hours=older_than_hours)).strftime("%Y%m%d%H%M")
    dropped = 0
    with contextlib.closing(connect(autocommit=True)) as conn, conn.cursor() as cur:
        cur.execute("SELECT datname FROM pg_database WHERE datname LIKE %s", [TEST_DB_PREFIX.replace("_", "\\_") + "%"])
        names = [r[0] for r in cur.fetchall()]
    for name in names:
        match = re.fullmatch(TEST_DB_PREFIX + r"(\d{12})_[0-9a-f]{8}", name)
        if match and match.group(1) < cutoff:
            _drop(name)
            dropped += 1
    return dropped


@contextlib.contextmanager
def restored_copy(dump_path: str):
    """
    Load the dump into a new, empty temporary database and yield a cursor on
    it. The database is always removed afterwards.
    """
    name = f"{TEST_DB_PREFIX}{timezone.now():%Y%m%d%H%M}_{secrets.token_hex(4)}"
    try:
        with contextlib.closing(connect(autocommit=True)) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    except psycopg2.errors.InsufficientPrivilege as exc:
        raise CannotCreateDatabase("The database user may not create databases, so the backup could not be loaded into a test database.") from exc
    try:
        result = subprocess.run(
            [_tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", *_target_args(name), dump_path],
            env=_env(), capture_output=True, text=True, timeout=DUMP_TIMEOUT,
        )
        if result.returncode != 0:
            log.error("pg_restore into %s failed: %s", name, result.stderr.strip()[:2000])
            raise DatabaseToolError("The backup could not be loaded into a test database. Details are in the server log.")
        with contextlib.closing(connect(name)) as conn, conn.cursor() as cur:
            yield cur
    finally:
        try:
            _drop(name)
        except Exception:  # noqa: BLE001 - cleanup must not hide the real result
            log.exception("Could not remove the temporary restore-test database %s", name)
