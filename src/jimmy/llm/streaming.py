from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from jimmy.llm.base import LLMResponse


@dataclass(frozen=True)
class LLMStreamChunk:
    """One provider-neutral streaming update."""

    text: str = ""
    response: LLMResponse | None = None


LLMStream = Iterator[LLMStreamChunk]
