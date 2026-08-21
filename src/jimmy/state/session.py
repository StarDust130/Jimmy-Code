from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    """State for one Jimmy coding session."""

    task: str

    messages: list[dict[str, Any]] = field(default_factory=list)

    turn_count: int = 0

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)

    def next_turn(self) -> int:
        """Move to the next agent turn and return its number."""
        self.turn_count += 1
        return self.turn_count
