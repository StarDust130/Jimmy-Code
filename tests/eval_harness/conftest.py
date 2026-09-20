"""🧪 Print the eval scorecard after the harness meta-tests run."""

from __future__ import annotations


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    try:
        from eval import scoring
        from eval.report import render_summary, write_results
    except Exception:
        return
    if not scoring.RECORDS:
        return
    for line in render_summary():
        terminalreporter.write_line(line)
    try:
        terminalreporter.write_line(f"🗂 results → {write_results('offline')}")
    except Exception:
        pass