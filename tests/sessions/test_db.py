"""🗄️ db layer — migrations · WAL · FK enforcement."""

from __future__ import annotations

import sqlite3

import pytest

from jimmy.sessions.db import MIGRATIONS, connect, migrate
from jimmy.sessions.store import SessionStore

TABLES = {"sessions", "messages", "tool_calls", "events", "settings", "schema_migrations"}


def test_migrate_creates_all_tables(tmp_path) -> None:
    conn = connect(tmp_path / "s.db")
    version = migrate(conn)
    assert version >= 1
    found = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= found
    conn.close()


def test_migrate_is_idempotent(tmp_path) -> None:
    path = tmp_path / "s.db"
    first = connect(path)
    migrate(first)
    first.close()

    second = connect(path)
    migrate(second)
    rows = second.execute("SELECT version FROM schema_migrations").fetchall()
    assert [r["version"] for r in rows] == [1]  # applied once, never re-run
    second.close()


def test_wal_journal(tmp_path) -> None:
    conn = connect(tmp_path / "s.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    conn.close()


def test_foreign_keys_enforced(tmp_path) -> None:
    store = SessionStore(tmp_path / "s.db")
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO messages (session_id, seq, role, content, created_at)"
            " VALUES ('missing', 1, 'user', 'x', '2025-01-01')"
        )
    store._conn.rollback()
    store.close()


def test_migration_repairs_crash_mid_migration(tmp_path) -> None:
    """💥 A crash INSIDE migration 1 (DDL autocommits, the version row
    never lands) leaves tables behind with NO version recorded.  The
    next start must REPAIR that state — not crash with 'table already
    exists'.  This is exactly the bug that broke real startups."""
    path = tmp_path / "s.db"

    crashed = connect(path)
    for statement in MIGRATIONS[0]:
        crashed.execute(statement)  # DDL lands in autocommit
    crashed.commit()  # …but no version row is written
    crashed.close()

    store = SessionStore(path)  # migrate() runs — must not raise
    row = store.create_session(title="after repair")
    assert store.get_session(row.id) is not None

    with store._lock:
        versions = [
            r["version"] for r in store._conn.execute("SELECT version FROM schema_migrations")
        ]
    assert versions == [1]  # version recorded exactly once
    store.close()
