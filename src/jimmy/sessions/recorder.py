"""🗄️ SessionRecorder — mirrors a live conversation into SQLite.

Wired by JimmyApp (one call per UI event).  Recording is BEST-EFFORT by
contract: a storage hiccup must never break a running chat, so every
method swallows unexpected errors.

Grouping model (mirrors the agent loop's event order):
    user_message()               → role=user row
    begin_step()                 → flushes the previous assistant (if any)
    step_text(chunk)             → accumulates the assistant text
    tool_started/finished/…      → tool_calls table + pending call list
    assistant_flush()            → role=assistant row (+ tool_calls JSON)
    event(kind, detail)          → events table
"""

from __future__ import annotations

from typing import Any

from .store import SessionStore

_DENIED_TEMPLATE = "Permission denied by the user for tool '{name}'."


def _guarded(method):
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            pass  # 🛡️ recording must never break the chat

    return wrapper


class SessionRecorder:
    """One session's live writer — created per session by JimmyApp."""

    def __init__(self, store: SessionStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id
        self._pending_content = ""
        self._pending_calls: list[dict[str, Any]] = []
        self._tool_rows: dict[str, int] = {}
        self._tool_names: dict[str, str] = {}

    # ── conversation ─────────────────────────────────────────────────

    @_guarded
    def user_message(self, text: str) -> None:
        self.store.append_message(self.session_id, "user", text)

    @_guarded
    def begin_step(self) -> None:
        self.assistant_flush()

    @_guarded
    def step_text(self, chunk: str) -> None:
        if chunk:
            self._pending_content += chunk

    @_guarded
    def tool_started(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        row = self.store.tool_started(self.session_id, call_id, name, arguments)
        self._tool_rows[call_id] = row
        self._tool_names[call_id] = name
        self._pending_calls.append(
            {"id": call_id, "name": name, "arguments": dict(arguments or {})}
        )

    @_guarded
    def tool_finished(self, call_id: str, output: str, latency_ms: float) -> None:
        row = self._tool_rows.get(call_id)
        if row is not None:
            self.store.tool_finished(row, output, latency_ms)

    @_guarded
    def tool_failed(self, call_id: str, error: BaseException | str) -> None:
        row = self._tool_rows.get(call_id)
        if row is not None:
            # 🏷️ store the type name too — matches what the chat shows
            if isinstance(error, BaseException):
                detail = f"{type(error).__name__}: {error}"
            else:
                detail = str(error)
            self.store.tool_failed(row, detail)

    @_guarded
    def tool_denied(self, call_id: str) -> None:
        row = self._tool_rows.get(call_id)
        if row is not None:
            name = self._tool_names.get(call_id, call_id)
            self.store.tool_denied(row, _DENIED_TEMPLATE.format(name=name))

    @_guarded
    def assistant_flush(self) -> None:
        if not self._pending_content and not self._pending_calls:
            return
        self.store.append_message(
            self.session_id,
            "assistant",
            self._pending_content,
            tool_calls=list(self._pending_calls),
        )
        self._pending_content = ""
        self._pending_calls = []

    @_guarded
    def event(self, kind: str, detail: str = "") -> None:
        self.store.append_event(self.session_id, kind, detail)
