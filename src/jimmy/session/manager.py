from typing import Any

from jimmy.session.store import SessionStore
from jimmy.state.session import SessionState


class SessionManager:
    """High-level session operations."""

    def __init__(
        self,
        store: SessionStore,
    ) -> None:
        self.store = store

    def create(
        self,
        state: SessionState,
    ) -> str:
        return self.store.create(state)

    def save(
        self,
        session_id: str,
        state: SessionState,
        status: str,
    ) -> None:
        self.store.save(
            session_id=session_id,
            state=state,
            status=status,
        )

    def load(
        self,
        session_id: str,
    ) -> SessionState:
        return self.store.load(session_id)

    def list(
        self,
    ) -> list[dict[str, Any]]:
        return self.store.list()

    def delete(
        self,
        session_id: str,
    ) -> None:
        self.store.delete(session_id)
