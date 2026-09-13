"""The small provider contract the agent depends on."""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from .types import LLMResult, Message


class LLMProvider(Protocol):
    """Minimal interface. Concrete SDK details stay behind this boundary."""

    model: str

    async def complete(self, messages: Sequence[Message]) -> LLMResult:
        """Return one completed response."""
        ...

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        """Yield response text chunks in order."""
        ...
