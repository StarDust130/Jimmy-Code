"""🌐 LIVE probes — real model + REAL tools in a throwaway workspace.

The truth serum: build a landing page, then CONTINUE on the same
history (add a Pricing section).  Continuation is where big tasks
historically go dumb.  Run with:  python -m eval.run --live
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from jimmy.agent import Agent
from jimmy.tools.core.factory import create_default_registry

from ..harness import Trajectory
from ..scoring import Check, ok


def _dups(tool_events: list[dict]) -> int:
    seen: set[str] = set()
    dups = 0
    for d in tool_events:
        key = json.dumps((d.get("name"), d.get("arguments")),
                         sort_keys=True, default=str)
        if key in seen:
            dups += 1
        seen.add(key)
    return dups


async def live_small_edit() -> tuple[list[Check], dict[str, Any]]:
    from .live_runtime import active_provider  # lazy — set up in run.py

    provider = active_provider()
    with TemporaryDirectory() as td, contextlib.chdir(td):
        agent = Agent(provider, tools=create_default_registry(), max_steps=12)
        traj = Trajectory()
        t0 = time.perf_counter()
        await traj.consume(agent.stream(
            "Create the file hello.py in the current directory containing "
            "exactly: print('jimmy eval')  — nothing else."
        ))
        wall = time.perf_counter() - t0

        target = Path("hello.py")
        content = target.read_text() if target.exists() else ""
        checks = [
            ok("file_created", target.exists(),
               f"steps={traj.steps} wall={wall:.0f}s"),
            ok("content_correct", "print('jimmy eval')" in content,
               repr(content[:60])),
            ok("within_step_budget", traj.steps <= 6, f"steps={traj.steps}"),
            ok("no_error_events", len(traj.of("error")) == 0),
        ]
        return checks, {"steps": traj.steps, "wall_s": round(wall)}


async def live_big_build_and_continue() -> tuple[list[Check], dict[str, Any]]:
    from .live_runtime import active_provider

    provider = active_provider()
    with TemporaryDirectory() as td, contextlib.chdir(td):
        agent = Agent(provider, tools=create_default_registry(), max_steps=30)
        traj = Trajectory()
        t0 = time.perf_counter()
        await traj.consume(agent.stream(
            "Create a polished dark-mode startup landing page: index.html, "
            "styles.css, app.js in the current directory. Hero + features + "
            "footer. Then verify all 3 files exist."
        ))
        wall = time.perf_counter() - t0

        made = {p for p in ("index.html", "styles.css", "app.js")
                if Path(p).exists()}
        dups = _dups(traj.tool_events)
        html = Path("index.html")
        checks = [
            ok("all_files_created", len(made) == 3, f"made={sorted(made)}"),
            ok("html_nontrivial", html.exists() and html.stat().st_size > 500,
               f"bytes={html.stat().st_size if html.exists() else 0}"),
            ok("step_efficient", traj.steps <= 22, f"steps={traj.steps}"),
            ok("low_duplicate_calls", dups <= 3, f"dups={dups}"),
            ok("no_error_events", len(traj.of("error")) == 0),
        ]

        # ── 🔁 CONTINUATION — turn 2 on top of turn 1's history ─────
        if not all(c.passed for c in checks):
            return checks, {"steps": traj.steps, "dups": dups,
                            "wall_s": round(wall), "continuation": "skipped"}

        survivor = Agent(provider, tools=create_default_registry(), max_steps=20)
        survivor.history = agent.history
        traj2 = Trajectory()
        t1 = time.perf_counter()
        await traj2.consume(survivor.stream(
            "Add a 'Pricing' section with three tiers to index.html. "
            "Modify only index.html."
        ))
        wall2 = time.perf_counter() - t1

        text = html.read_text() if html.exists() else ""
        dups2 = _dups(traj2.tool_events)
        checks += [
            ok("continuation_applied", "Pricing" in text,
               "index.html missing Pricing"),
            ok("continuation_efficient", traj2.steps <= 12,
               f"steps={traj2.steps}"),
            ok("continuation_focused", dups2 <= 2, f"dups={dups2}"),
            ok("other_files_untouched",
               Path("styles.css").exists() and Path("app.js").exists(),
               "sibling files were removed"),
        ]
        return checks, {"steps": traj.steps, "dups": dups, "wall_s": round(wall),
                        "continue_steps": traj2.steps, "continue_dups": dups2,
                        "continue_wall_s": round(wall2)}

LIVE_SUITE = [
    ("live_small_edit", live_small_edit),
    ("live_big_build_and_continue", live_big_build_and_continue),
]    