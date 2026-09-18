"""🗄️ SQLite connection + versioned migrations for the session store.

Crash safety:
    * WAL journal + synchronous=NORMAL — a kill -9 mid-turn loses at
      most the current statement, never earlier messages.
    * one transaction per migration version.

Idempotent by design:
    Python's sqlite3 runs DDL in AUTOCOMMIT — a crash (or a failed
    bookkeeping write) mid-migration can leave tables behind WITHOUT a
    schema_migrations row.  Every statement therefore uses IF NOT
    EXISTS, so the next start REPAIRS that half-migrated state instead
    of crashing with 'table already exists'.

Schema changes = append a new statement-tuple to MIGRATIONS — never
edit an already-applied one.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

# Each migration = tuple of SQL statements, applied in ONE transaction.
# ⚠️ IDEMPOTENT ONLY — every CREATE carries IF NOT EXISTS (see docstring).
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New session',
            model TEXT NOT NULL DEFAULT '',
            permission_mode TEXT NOT NULL DEFAULT '',
            workspace TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions (updated_at)",
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls TEXT NOT NULL DEFAULT '[]',
            tool_call_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (session_id, seq)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, seq)",
        """
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            call_id TEXT NOT NULL,
            name TEXT NOT NULL,
            arguments TEXT NOT NULL DEFAULT '{}',
            output TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            latency_ms REAL,
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls (session_id, call_id)",
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, created_at)",
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    ),
)


def connect(path: Path) -> sqlite3.Connection:
    """Open a crash-safe connection (WAL · FK on · busy timeout)."""
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the schema version now in place."""
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
    applied = {int(r["version"]) for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, statements in enumerate(MIGRATIONS, start=1):
        if version in applied:
            continue
        applied_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, applied_at),
            )
    return len(MIGRATIONS)
