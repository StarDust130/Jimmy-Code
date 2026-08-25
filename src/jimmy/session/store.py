from typing import Protocol

from jimmy.state.session import SessionState


class SessionStore(Protocol):
    """Storage contract for Jimmy sessions."""

    def create(
        self,
        state: SessionState,
    ) -> str:
        """Create a session and return its ID."""
        ...

    def save(
        self,
        session_id: str,
        state: SessionState,
        status: str,
    ) -> None:
        """Persist the current session state."""
        ...

    def load(
        self,
        session_id: str,
    ) -> SessionState:
        """Load a session."""
        ...

    def list(
        self,
    ) -> list[dict]:
        """List saved sessions."""
        ...

    def delete(
        self,
        session_id: str,
    ) -> None:
        """Delete a session."""
        ...
