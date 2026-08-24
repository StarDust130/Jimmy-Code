from typing import Any

from jimmy.llm.base import LLMProvider, LLMResponse
from jimmy.llm.errors import LLMProviderError


class FallbackProvider(LLMProvider):
    """Use the fallback provider when the primary provider fails."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        try:
            return self.primary.chat(
                messages=messages,
                tools=tools,
            )

        except LLMProviderError:
            return self.fallback.chat(
                messages=messages,
                tools=tools,
            )
