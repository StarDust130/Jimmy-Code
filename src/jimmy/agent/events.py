from dataclasses import dataclass
from typing import Any, Literal

EventKind = Literal[
    "turn_start",
    "turn_end",
    "tool_start",
    "tool_end",
    "complete",
    "error",
]


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """UI-neutral event emitted by the agent."""

    kind: EventKind
    turn: int = 0
    tool_name: str | None = None
    elapsed: float | None = None
    arguments: dict[str, Any] | None = None
    message: str | None = None
