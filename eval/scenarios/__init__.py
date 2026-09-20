"""🧪 Scenario registry — each suite is a list of (case_id, async fn)."""

from __future__ import annotations

from typing import Any

from .big import BIG_SUITE
from .live import LIVE_SUITE
from .small import SMALL_SUITE

Scenario = tuple[str, Any]
SUITES: dict[str, list[Scenario]] = {"small": SMALL_SUITE, "big": BIG_SUITE}
LIVE_SUITE_NAME = "live"

__all__ = ["BIG_SUITE", "LIVE_SUITE", "LIVE_SUITE_NAME", "SMALL_SUITE", "Scenario", "SUITES"]
