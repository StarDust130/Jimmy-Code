from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from .types import (
    LLMResult,
    LLMStreamEvent,
    Message,
)


class LLMProvider(Protocol):
    model: str

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult: ...

    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> AsyncIterator[LLMStreamEvent]: ...
