"""🗄️ Local session persistence (SQLite) — schema · store · recorder.

The RAM context (agent.history) stays the hot path; SQLite is the
persistent source of truth: every message, tool result and error is
mirrored as it happens, so a restart never loses a session and old
sessions can be resumed exactly where they stopped.
"""

from .db import MIGRATIONS, SCHEMA_VERSION, connect, migrate
from .recorder import SessionRecorder
from .store import CLEANUP_CHOICES, MessageRow, SessionRow, SessionStore, default_db_path

__all__ = [
    "CLEANUP_CHOICES",
    "MIGRATIONS",
    "MessageRow",
    "SCHEMA_VERSION",
    "SessionRecorder",
    "SessionRow",
    "SessionStore",
    "connect",
    "default_db_path",
    "migrate",
]
