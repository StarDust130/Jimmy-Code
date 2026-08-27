from typing import Any, Protocol

from jimmy.state.session import SessionState


class SessionStore(Protocol):
    """Storage interface for Jimmy sessions."""

    def create(
        self,
        state: SessionState,
    ) -> str: ...

    def save(
        self,
        session_id: str,
        state: SessionState,
        status: str,
    ) -> None: ...

    def load(
        self,
        session_id: str,
    ) -> SessionState: ...

    def list(
        self,
    ) -> list[dict[str, Any]]: ...

    def delete(
        self,
        session_id: str,
    ) -> bool: ...
