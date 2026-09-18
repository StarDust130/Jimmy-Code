"""💰 Session-wide token + cost tracking.

💵 pricing with a manual fallback (the $0-in-navbar fix):
    1. litellm.completion_cost(model=...)   ← authoritative, RAISES for
                                              unknown models
    2. litellm.model_cost[table] per-token  ← try the full litellm
       prices                                  string AND the bare id
                                               ("zai/glm-x" usually isn't
                                               in the table; "glm-x" is)
    3. 0.0                                  ← free/local/unknown —
                                               tokens still tracked

Tracked in exactly ONE place: Agent.stream() → cost.add(usage, model)
after every LLM call.  The TUI never calls add() (that would double).
"""

from __future__ import annotations

import litellm

from .types import Usage


class CostTracker:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        # 1️⃣ authoritative path (raises for unknown models — caught)
        try:
            cost = litellm.completion_cost(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            if cost and float(cost) > 0:
                return float(cost)
        except Exception:
            pass

        # 2️⃣ manual per-token pricing from LiteLLM's own table —
        #    full litellm string first, then the bare model id.
        table = getattr(litellm, "model_cost", None) or {}
        candidates = [model]
        if "/" in model:
            candidates.append(model.split("/", 1)[1])

        for candidate in candidates:
            entry = table.get(candidate)
            if not isinstance(entry, dict):
                continue
            in_price = entry.get("input_cost_per_token")
            out_price = entry.get("output_cost_per_token")
            if in_price is None or out_price is None:
                continue
            try:
                return prompt_tokens * float(in_price) + completion_tokens * float(out_price)
            except Exception:
                continue

        return 0.0  # 🟢 free / local / unpriced — tokens still tracked

    def add(self, usage: Usage, model: str) -> None:
        """Add ONE LLM call's usage (Agent.stream calls this per step)."""
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += self._estimate_cost(model, usage.input_tokens, usage.output_tokens)

    def reset(self) -> None:
        """Fresh ledger (used on /clear and model switch)."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def totals(self) -> str:
        """📊 One-line summary for the TUI header."""
        cost = f"${self.cost_usd:.4f}" if self.cost_usd > 0 else ""
        return f"{self.input_tokens:,} in / {self.output_tokens:,} out {cost}".strip()
