import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jimmy.state.session import SessionState


class JsonSessionStore:
    """Local JSON-backed session storage."""

    def __init__(
        self,
        root: Path,
    ) -> None:
        self.directory = root / ".jimmy" / "sessions"
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        state: SessionState,
    ) -> str:
        session_id = uuid4().hex[:12]
        self.save(
            session_id=session_id,
            state=state,
            status="running",
        )
        return session_id

    def save(
        self,
        session_id: str,
        state: SessionState,
        status: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()

        data = {
            "id": session_id,
            "task": state.task,
            "messages": self._sanitize(state.messages),
            "turn_count": state.turn_count,
            "status": status,
            "updated_at": now,
        }

        path = self._path(session_id)
        temp_path = path.with_suffix(".tmp")

        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Replace atomically so a crash doesn't leave
        # a half-written JSON session.
        temp_path.replace(path)

    def load(
        self,
        session_id: str,
    ) -> SessionState:
        path = self._path(session_id)

        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        data = json.loads(path.read_text(encoding="utf-8"))

        state = SessionState(
            task=data["task"],
            messages=data["messages"],
        )
        state.turn_count = int(data.get("turn_count", 0))
        return state

    def list(
        self,
    ) -> list[dict]:
        sessions: list[dict] = []

        for path in self.directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(
                    {
                        "id": data["id"],
                        "task": data["task"],
                        "status": data.get("status", "unknown"),
                        "turn_count": data.get("turn_count", 0),
                        "updated_at": data.get("updated_at"),
                    }
                )
            except (
                OSError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ):
                continue

        sessions.sort(
            key=lambda item: item.get("updated_at") or "",
            reverse=True,
        )
        return sessions

    def delete(
        self,
        session_id: str,
    ) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def _path(
        self,
        session_id: str,
    ) -> Path:
        if not session_id:
            raise ValueError("Session id is required.")
        if "/" in session_id or "\\" in session_id or ".." in session_id:
            raise ValueError("Invalid session id.")
        return self.directory / f"{session_id}.json"

    @staticmethod
    def _sanitize(obj: Any) -> Any:
        """Recursively convert bytes to strings for JSON serialization."""
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if isinstance(obj, dict):
            return {k: JsonSessionStore._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [JsonSessionStore._sanitize(v) for v in obj]
        return obj
