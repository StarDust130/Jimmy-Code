from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .types import LLMResult, Message


class LLMProvider(Protocol):
    # 🤖 Model name used by the provider
    model: str

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult:
        """💬 Get one complete response, optionally with tools."""
        ...

    async def stream(
        self,
        messages: Sequence[Message],
    ):
        """⚡ Stream a normal chat response."""
        ...