"""Provider-independent LLM types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def available(self) -> bool:
        return self.total_tokens > 0


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str = ""
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    kind: Literal["text", "done"]
    text: str = ""
    result: LLMResult | None = None
