"""🗄️ SessionStore — the persistent source of truth for conversations.

Everything the sessions screen shows and every resume rebuilds comes
from here; the in-RAM agent history stays the hot path and is mirrored
into SQLite on every event.

Safety:
    * one connection + RLock → safe from the UI thread AND workers
    * every write commits immediately (a crash keeps all prior messages)
    * API keys / secrets never touch this DB (they live in models.json)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jimmy.llm.types import Message, ToolCall

from .db import connect, migrate

CLEANUP_CHOICES: tuple[str, ...] = ("15", "30", "90", "never")
_DEFAULT_SETTINGS: dict[str, str] = {"cleanup_days": "30"}


def default_db_path() -> Path:
    """~/.jimmy/sessions.db — JIMMY_SESSIONS_DB overrides (tests/CI)."""
    env = os.environ.get("JIMMY_SESSIONS_DB")
    if env:
        return Path(env)
    return Path.home() / ".jimmy" / "sessions.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class SessionRow:
    id: str
    title: str
    model: str
    permission_mode: str
    workspace: str
    created_at: str
    updated_at: str
    message_count: int
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def title_source(self) -> str:
        """'default' · 'auto' (AI) · 'user' (rename — never overwritten)."""
        return str(self.meta.get("title_source", "default"))


@dataclass
class MessageRow:
    seq: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    created_at: str = ""


class SessionStore:
    """SQLite-backed session storage — thread-safe, crash-safe."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = connect(self.path)
        self._version = migrate(self._conn)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ── sessions ──────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        title: str = "New session",
        model: str = "",
        permission_mode: str = "",
        workspace: str = "",
        session_id: str | None = None,
    ) -> SessionRow:
        sid = session_id or uuid.uuid4().hex
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions (id, title, model, permission_mode, workspace,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (sid, title, model, permission_mode, workspace, now, now),
            )
        row = self.get_session(sid)
        if row is None:  # pragma: no cover — insert+select under lock
            raise RuntimeError("session vanished right after insert")
        return row

    def get_session(self, session_id: str) -> SessionRow | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return self._row(r) if r is not None else None

    def list_sessions(self, limit: int | None = 200) -> list[SessionRow]:
        """Newest first (by updated_at)."""
        sql = "SELECT * FROM sessions ORDER BY updated_at DESC"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]

    def touch_session(
        self,
        session_id: str,
        *,
        model: str | None = None,
        permission_mode: str | None = None,
    ) -> bool:
        sets = ["updated_at=?"]
        args: list[Any] = [_now()]
        if model is not None:
            sets.append("model=?")
            args.append(model)
        if permission_mode is not None:
            sets.append("permission_mode=?")
            args.append(permission_mode)
        args.append(session_id)
        with self._lock, self._conn:
            cur = self._conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", args)
        return cur.rowcount > 0

    def rename_session(self, session_id: str, title: str, *, source: str = "user") -> bool:
        title = " ".join(str(title).split()) or "Untitled"
        row = self.get_session(session_id)
        if row is None:
            return False
        meta = dict(row.meta)
        meta["title_source"] = source
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET title=?, meta=?, updated_at=? WHERE id=?",
                (title, json.dumps(meta), _now(), session_id),
            )
        return True

    def set_auto_title(self, session_id: str, title: str) -> bool:
        """🏷️ AI title — NEVER overwrites a user rename."""
        row = self.get_session(session_id)
        if row is None or row.title_source == "user":
            return False
        return self.rename_session(session_id, title, source="auto")

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cur.rowcount > 0

    @staticmethod
    def _row(r: sqlite3.Row) -> SessionRow:
        try:
            meta = json.loads(r["meta"] or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        return SessionRow(
            id=r["id"],
            title=r["title"],
            model=r["model"],
            permission_mode=r["permission_mode"],
            workspace=r["workspace"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            message_count=int(r["message_count"]),
            meta=meta,
        )

    # ── messages ──────────────────────────────────────────────────────

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> int:
        now = _now()
        calls = tool_calls or []
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE session_id=?",
                (session_id,),
            )
            seq = int(cur.fetchone()[0])
            with self._conn:
                self._conn.execute(
                    "INSERT INTO messages (session_id, seq, role, content,"
                    " tool_calls, tool_call_id, created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        session_id,
                        seq,
                        role,
                        content,
                        json.dumps(calls, ensure_ascii=False),
                        tool_call_id,
                        now,
                    ),
                )
                self._conn.execute(
                    "UPDATE sessions SET updated_at=?,"
                    " message_count=(SELECT COUNT(*) FROM messages WHERE session_id=?)"
                    " WHERE id=?",
                    (now, session_id, session_id),
                )
        return seq

    def get_messages(self, session_id: str) -> list[MessageRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
        out: list[MessageRow] = []
        for r in rows:
            try:
                calls = json.loads(r["tool_calls"] or "[]")
            except Exception:
                calls = []
            if not isinstance(calls, list):
                calls = []
            out.append(
                MessageRow(
                    seq=int(r["seq"]),
                    role=r["role"],
                    content=r["content"],
                    tool_calls=calls,
                    tool_call_id=r["tool_call_id"],
                    created_at=r["created_at"],
                )
            )
        return out

    def count_user_messages(self, session_id: str) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id=? AND role='user'",
                (session_id,),
            ).fetchone()
        return int(r[0])

    def user_texts(self, session_id: str, limit: int = 3) -> list[str]:
        """First `limit` user messages — title-generation context."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT content FROM messages WHERE session_id=? AND role='user'"
                " ORDER BY seq LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
        return [r["content"] for r in rows if r["content"]]

    # ── tool calls ────────────────────────────────────────────────────

    def tool_started(
        self, session_id: str, call_id: str, name: str, arguments: dict[str, Any]
    ) -> int:
        now = _now()
        try:
            args_json = json.dumps(arguments or {}, ensure_ascii=False)
        except Exception:
            args_json = "{}"
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO tool_calls (session_id, call_id, name, arguments,"
                " status, created_at) VALUES (?,?,?,?,'running',?)",
                (session_id, call_id, name, args_json, now),
            )
        return int(cur.lastrowid or 0)

    def tool_finished(self, row_id: int, output: str, latency_ms: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tool_calls SET output=?, status='ok', latency_ms=? WHERE id=?",
                (output, float(latency_ms), row_id),
            )

    def tool_failed(self, row_id: int, detail: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tool_calls SET output=?, status='error' WHERE id=?",
                (detail, row_id),
            )

    def tool_denied(self, row_id: int, detail: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE tool_calls SET output=?, status='denied' WHERE id=?",
                (detail, row_id),
            )

    def get_tool_outputs(self, session_id: str) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT call_id, output FROM tool_calls"
                " WHERE session_id=? AND output IS NOT NULL ORDER BY id",
                (session_id,),
            ).fetchall()
        return {r["call_id"]: r["output"] for r in rows}

    # ── events (errors · max_steps …) ─────────────────────────────────

    def append_event(self, session_id: str, kind: str, detail: str = "") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (session_id, kind, detail, created_at) VALUES (?,?,?,?)",
                (session_id, kind, detail, _now()),
            )

    # ── settings ──────────────────────────────────────────────────────

    def get_setting(self, key: str) -> str:
        with self._lock:
            r = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if r is not None:
            return str(r["value"])
        return _DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    # ── auto-cleanup ──────────────────────────────────────────────────

    def cleanup_days(self) -> int | None:
        raw = self.get_setting("cleanup_days") or "30"
        if raw == "never":
            return None
        try:
            return max(1, int(raw))
        except ValueError:
            return 30

    def set_cleanup_days(self, raw: str) -> None:
        if raw not in CLEANUP_CHOICES:
            raise ValueError(f"cleanup days must be one of {CLEANUP_CHOICES}")
        self.set_setting("cleanup_days", raw)

    def cleanup(self, days: int | None) -> int:
        """Delete sessions not updated within `days`.  None/<=0 → never."""
        if days is None or days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
            timespec="milliseconds"
        )
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        return cur.rowcount

    # ── resume ────────────────────────────────────────────────────────

    def build_history(self, session_id: str) -> list[Message]:
        """Rebuild the agent's RAM history exactly as the loop expects it:
        assistant messages carry their tool_calls; each call is followed
        by its role='tool' result (from the tool_calls table)."""
        outputs = self.get_tool_outputs(session_id)
        history: list[Message] = []
        for m in self.get_messages(session_id):
            if m.role == "assistant" and m.tool_calls:
                calls = tuple(
                    ToolCall(
                        id=str(c.get("id", "")),
                        name=str(c.get("name", "")),
                        arguments=dict(c.get("arguments") or {}),
                    )
                    for c in m.tool_calls
                    if isinstance(c, dict)
                )
                history.append(Message(role="assistant", content=m.content, tool_calls=calls))
                for call in calls:
                    content = outputs.get(call.id)
                    if content is None:
                        content = f"Tool '{call.name}' produced no recorded output."
                    history.append(Message(role="tool", content=content, tool_call_id=call.id))
            else:
                history.append(Message(role=m.role, content=m.content, tool_call_id=m.tool_call_id))
        return history
