"""🧪 Eval CLI — the scorecard driver.

    python -m eval.run                        # offline: small + big
    python -m eval.run --suite big            # one suite
    python -m eval.run --save-baseline        # 📌 pin scores
    python -m eval.run --live                 # 🌐 real model + real tools
    python -m eval.run --fail-under 85        # CI gate (default 70)

--live is a shorthand for --suite live: it loads the ACTIVE model
(the one configured via jimmy → ctrl+m), hands it to the live scenarios
through eval/scenarios/live_runtime.py, and runs REAL tool executions
inside a throwaway workspace.  Costs real tokens.

Exit code: 0 when overall >= --fail-under, 1 otherwise, 2 when live
mode cannot start (no active model).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from .report import RESULTS_DIR, render_rich, render_summary, write_results
from .scenarios import LIVE_SUITE, LIVE_SUITE_NAME, SUITES
from .scoring import overall, reset_records, submit_crash, submit_record

FAIL_UNDER_DEFAULT = 70.0


def run_case(suite: str, case_id: str, fn) -> None:
    """Run one scenario; a crash becomes a 💥 record, never an abort."""
    t0 = time.perf_counter()
    try:
        checks, metrics = asyncio.run(fn())
        submit_record(suite, case_id, checks, metrics, time.perf_counter() - t0)
    except Exception as exc:
        submit_crash(suite, case_id, f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval", description="🧪 Jimmy agent evaluation")
    parser.add_argument("--suite", choices=["all", "small", "big", "live"], default="all")
    parser.add_argument(
        "--live", action="store_true", help="shorthand for --suite live (real model + real tools)"
    )
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--fail-under", type=float, default=FAIL_UNDER_DEFAULT)
    args = parser.parse_args(argv)

    if args.live:
        args.suite = "live"  # 🔀 --live is an alias for --suite live

    reset_records()
    live = args.suite == "live"

    if live:
        try:
            from jimmy.llm.model_config import ModelStore
            from jimmy.llm.provider_factory import create_provider

            provider = create_provider(ModelStore().active())
        except Exception as exc:
            print(f"🔴 live mode needs an active model — open jimmy → ctrl+m first.\n   ({exc})")
            return 2
        from .scenarios import live_runtime

        live_runtime.set_provider(provider)
        for cid, fn in LIVE_SUITE:
            run_case(LIVE_SUITE_NAME, cid, fn)
    else:
        wanted = list(SUITES) if args.suite == "all" else [args.suite]
        for name in wanted:
            for cid, fn in SUITES[name]:
                run_case(name, cid, fn)

    render_rich(live=live)
    for line in render_summary():
        print(line)
    path = write_results("live" if live else "offline")
    print(f"🗂 results → {path}")

    if args.save_baseline and not live:
        base = RESULTS_DIR / "baseline.json"
        base.write_text(path.read_text())
        print(f"📌 baseline saved → {base}")

    return 0 if overall() >= args.fail_under else 1


if __name__ == "__main__":
    sys.exit(main())
