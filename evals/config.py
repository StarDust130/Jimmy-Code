from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalConfig:
    requests_per_minute: int = 15
    request_window_seconds: float = 60.0
    max_turns: int = 20
    max_rate_limit_retries: int = 6
    keep_workspaces: bool = False
    report_path: Path = Path("evals/traces/latest.json")
