from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

EventKind = Literal[
    "turn_start",
    "turn_end",
    "tool_start",
    "tool_end",
    "llm_usage",
    "complete",
    "error",
]


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """UI-neutral event emitted by the agent."""

    kind: EventKind
    turn: int = 0

    # Human-readable event information.
    message: str | None = None

    # Tool information.
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None

    # Duration of the operation represented by this event.
    elapsed: float | None = None

    # LLM observability information.
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
