"""🧪 Reporting — scorecard (plain + rich) · JSON · baseline diff."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval_results"
REGRESSION_THRESHOLD = 5.0
_WIDTH = 96


def _short(v: object) -> str:
    text = str(v)
    return text if len(text) <= 34 else text[:33] + "…"


def render_summary() -> list[str]:
    """Plain scorecard — works in pytest output and dumb terminals."""
    from .scoring import RECORDS, grade, overall

    lines = ["", f"🧪 JIMMY EVAL SCORECARD — overall {overall()} {grade(overall())}", "─" * _WIDTH]
    for r in RECORDS:
        icon = "🟢" if r.passed and r.score >= 85 else "🟡" if r.score >= 50 else "🔴"
        metrics = " · ".join(f"{k}={_short(v)}" for k, v in list(r.metrics.items())[:4])
        head = f"{icon} {r.suite:<5} {r.case:<28} {r.score:>5.1f}  {r.wall_s:>6.1f}s"
        if r.error:
            lines.append(f"{head}  💥 {r.error[:60]}")
        elif r.failed:
            lines.append(f"{head}  ✗ {', '.join(r.failed[:3])}")
            for name in r.failed[:2]:
                lines.append(f"{'':44}    ↳ {r.details.get(name, '')[: _WIDTH - 50]}")
        else:
            lines.append(f"{head}  {metrics}")
    lines.append("─" * _WIDTH)

    base = RESULTS_DIR / "baseline.json"
    if base.exists():
        try:
            prev = float(json.loads(base.read_text()).get("overall", 0.0))
            delta = overall() - prev
            mark = (
                "🔺"
                if delta >= REGRESSION_THRESHOLD
                else ("🔻" if delta <= -REGRESSION_THRESHOLD else "·")
            )
            lines.append(f"baseline {prev} {grade(prev)} → now {overall()}  {mark} {delta:+.1f}")
        except Exception:
            pass

    for r in RECORDS:
        if "duplicate_ratio" in r.metrics and r.metrics["duplicate_ratio"] > 0.5:
            lines.append(
                f"⚠ duplicate_ratio={r.metrics['duplicate_ratio']} on "
                f"{r.case} — the 'dumb on big tasks' driver"
            )
    lines.append("")
    return lines


def render_rich(live: bool = False) -> None:
    """Rich table for the CLI."""
    from rich.console import Console
    from rich.table import Table

    from .scoring import RECORDS, grade, overall

    console = Console()
    total = overall()
    table = Table(
        title=f"{'🌐 LIVE' if live else '🧪 OFFLINE'} EVAL — "
        f"overall [bold]{total}[/] {grade(total)}"
    )
    table.add_column("suite", style="bold")
    table.add_column("case")
    table.add_column("score", justify="right")
    table.add_column("")
    table.add_column("metrics / failure detail", overflow="fold")

    last_suite = None
    for r in RECORDS:
        icon = "🟢" if r.passed and r.score >= 85 else "🟡" if r.score >= 50 else "🔴"
        if r.error:
            detail = f"[red]💥 {r.error}[/red]"
        elif r.failed:
            detail = (
                "[red]✗ "
                + ", ".join(r.failed)
                + "[/red]"
                + "".join(f"\n[dim]↳ {r.details.get(n, '')}[/dim]" for n in r.failed[:2])
            )
        else:
            detail = " · ".join(f"{k}={_short(v)}" for k, v in list(r.metrics.items())[:4])
        table.add_row(
            r.suite if r.suite != last_suite else "", r.case, f"{r.score:.0f}", icon, detail
        )
        last_suite = r.suite

    console.print(table)

    base = RESULTS_DIR / "baseline.json"
    if base.exists():
        try:
            prev = float(json.loads(base.read_text()).get("overall", 0.0))
            delta = total - prev
            if abs(delta) >= REGRESSION_THRESHOLD:
                mark = "🔺 improved" if delta > 0 else "🔻 REGRESSION"
                console.print(
                    f"  [bold {'green' if delta > 0 else 'red'}]"
                    f"{mark}: baseline {prev} → {total} ({delta:+.1f})[/]"
                )
        except Exception:
            pass


def write_results(mode: str = "offline") -> Path:
    """Persist all records → eval_results/latest.json."""
    from .scoring import RECORDS, overall

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "overall": overall(),
        "records": [
            {
                "suite": r.suite,
                "case": r.case,
                "score": r.score,
                "passed": r.passed,
                "failed": r.failed,
                "metrics": r.metrics,
                "wall_s": r.wall_s,
                "error": r.error,
            }
            for r in RECORDS
        ],
    }
    path = RESULTS_DIR / "latest.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def compare_baseline(records: list) -> list[str]:
    """Regression warnings — score dropped ≥ threshold vs baseline.json."""
    base = RESULTS_DIR / "baseline.json"
    if not base.exists():
        return []
    try:
        data = json.loads(base.read_text())
    except Exception:
        return []
    prev_by_case = {r["case"]: r["score"] for r in data.get("records", [])}
    return [
        f"🔻 REGRESSION {r.suite}/{r.case}: {prev_by_case[r.case]} → {r.score}"
        for r in records
        if r.case in prev_by_case and (prev_by_case[r.case] - r.score) >= REGRESSION_THRESHOLD
    ]
