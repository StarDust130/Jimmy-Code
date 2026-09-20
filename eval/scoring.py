"""🧪 Scoring — checks · weighted scores · global records.

A scenario returns (checks, metrics); the runner packages them into a
Record.  Records drive the scorecard, JSON results and baseline diffs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    weight: float = 1.0


def ok(name: str, condition: bool, detail: str = "", weight: float = 1.0) -> Check:
    return Check(name, bool(condition), detail, weight)


def score(checks: Sequence[Check]) -> float:
    total = sum(c.weight for c in checks) or 1.0
    return round(100.0 * sum(c.weight for c in checks if c.passed) / total, 1)


@dataclass
class Record:
    suite: str
    case: str
    score: float
    passed: bool
    failed: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    wall_s: float = 0.0
    error: str | None = None


RECORDS: list[Record] = []


def reset_records() -> None:
    RECORDS.clear()


def submit_record(
    suite: str,
    case: str,
    checks: Sequence[Check],
    metrics: dict[str, Any] | None = None,
    wall: float = 0.0,
) -> Record:
    rec = Record(
        suite=suite,
        case=case,
        score=score(checks),
        passed=all(c.passed for c in checks),
        failed=[c.name for c in checks if not c.passed],
        details={c.name: c.detail for c in checks},
        metrics=metrics or {},
        wall_s=round(wall, 2),
    )
    RECORDS.append(rec)
    return rec


def submit_crash(suite: str, case: str, error: str) -> Record:
    rec = Record(
        suite=suite,
        case=case,
        score=0.0,
        passed=False,
        failed=["💥 crashed"],
        error=error,
        wall_s=0.0,
    )
    RECORDS.append(rec)
    return rec


def overall() -> float:
    return round(sum(r.score for r in RECORDS) / len(RECORDS), 1) if RECORDS else 0.0


def grade(v: float) -> str:
    return "🟢" if v >= 85 else "🟡" if v >= 70 else "🔴"