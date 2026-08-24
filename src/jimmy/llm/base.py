from abc import ABC, abstractmethod
from typing import Any

from jimmy.llm.models import LLMResponse


class LLMProvider(ABC):
    """Interface every LLM provider must implement."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
