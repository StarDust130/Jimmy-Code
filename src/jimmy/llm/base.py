from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """Normalized tool call returned by any LLM provider."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response returned by any LLM provider."""

    content: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


class LLMProvider(ABC):
    """Common interface for every Jimmy model provider."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
