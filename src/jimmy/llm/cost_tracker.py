"""💰 Session-wide token + cost tracking.

📊 TUI header reads .totals() → "1.2k in / 340 out · $0.004"
💵 cost via LiteLLM's built-in pricing table (per model, automatic)
"""

from __future__ import annotations

import litellm

from .types import Usage


class CostTracker:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def add(self, usage: Usage, model: str) -> None:
        """Add one LLM call's usage. Safe if pricing unknown."""
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens

        try:
            # 💵 litellm knows pricing for most models
            self.cost_usd += litellm.completion_cost(
                model=model,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
            )
        except Exception:
            pass  # 🤷 unknown model → tokens still tracked, cost stays

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def totals(self) -> str:
        """📊 One-line summary for the TUI header."""
        cost = f"${self.cost_usd:.4f}" if self.cost_usd > 0 else ""
        return f"{self.input_tokens:,} in / {self.output_tokens:,} out {cost}".strip()
