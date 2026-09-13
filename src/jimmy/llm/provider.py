from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from .types import LLMResult, Message


class LLMProvider(Protocol):
    # 🤖 Model name used by the provider
    model: str

    # 1️⃣ Get one complete response
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult:
        """💬 Get one complete response, optionally using tools."""
        ...

    # 2️⃣ Stream a normal chat response
    # ⚠️ def is correct because this returns an async generator
    def stream(
        self,
        messages: Sequence[Message],
    ) -> AsyncIterator[str]:
        """⚡ Stream text chunks as they arrive."""
        ...
