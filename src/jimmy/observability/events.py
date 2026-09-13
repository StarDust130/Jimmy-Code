"""Tiny observability events for V1; richer metrics/tracing come later."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
