"""🔴 BIG suite — the long-task failures, measured hermetically.

landing_page_build       ideal 5-step build: efficiency + zero dups
dumb_loop_endurance      model repeats forever → loop survives;
                         duplicate_ratio is the headline 'dumb' metric
context_integrity        50 steps + 10k-char outputs: clipping works,
                         pruned view shrinks, canonical stays complete
event_flood_agent        300 chunks: agent-side throughput
tui_flood_responsive     REAL JimmyApp: 200-chunk turn must finish
                         promptly — the freeze test
resume_midtask           mirror a turn to SQLite → 💥 → rebuild →
                         continue on the same history (invariants)
"""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from jimmy.llm.provider import LLMProvider
from jimmy.sessions import SessionRecorder, SessionStore

from ..harness import FakeTool, ScriptedProvider, Trajectory, call, make_agent, result
from ..scoring import Check, ok

BIG_OUTPUT = "line\n" * 2000  # ≈ 10k chars


async def landing_page_build() -> tuple[list[Check], dict[str, Any]]:
    """Plan + 3 writes + build + summary = 5 steps, 0 duplicates."""
    files = FakeTool("write_file", output="written")
    shell = FakeTool("shell", output="built in 1.2s")
    provider = ScriptedProvider(
        [
            result(
                "Plan: hero, features, footer.",
                (call("c1", "write_file", {"path": "index.html", "content": "<html>…"}),),
            ),
            result("", (call("c2", "write_file", {"path": "styles.css", "content": "body{}"}),)),
            result(
                "", (call("c3", "write_file", {"path": "app.js", "content": "console.log(1)"}),)
            ),
            result("", (call("c4", "shell", {"command": "npm run build"}),)),
            result("Landing page built: hero, features, footer. Build ✓"),
        ]
    )
    agent, _ = make_agent(provider, [files, shell])
    traj = Trajectory()
    await traj.consume(agent.stream("create a landing page"))

    # ✅ FakeTool records plain dicts (the loop validates via pydantic)
    written = {c.get("path") for c in files.calls}
    dups, ratio = traj.duplicates()
    # user + 4×(asst + tool) + final asst = 10
    checks = [
        ok(
            "all_files_created",
            {"index.html", "styles.css", "app.js"} <= written,
            f"written={sorted(written)}",
        ),
        ok(
            "build_command_ran",
            any(
                c["name"] == "shell"
                and "build" in str((c.get("arguments") or {}).get("command", ""))
                for c in traj.tool_events
            ),
            f"used={traj.tool_names()}",
        ),
        ok("step_efficient", traj.steps == 5, f"steps={traj.steps} optimal=5"),
        ok("zero_duplicate_calls", dups == 0, f"dups={dups} ratio={ratio:.2f}"),
        ok("completed_with_summary", "built" in traj.final_text.lower(), traj.final_text[:60]),
        ok(
            "history_complete",
            len(agent.history) == 10,
            f"history={len(agent.history)} expected=10",
        ),
    ]
    return checks, {"steps": traj.steps, "tools": traj.tool_names(), "dups": dups}


async def dumb_loop_endurance() -> tuple[list[Check], dict[str, Any]]:
    tool = FakeTool("write_file", output="written")
    provider = ScriptedProvider(
        [
            lambda step, hlen: result(
                "", (call(f"c{step}", "write_file", {"path": "index.html", "content": "<html>…"}),)
            )
        ]
    )
    agent, _ = make_agent(provider, [tool], max_steps=25)
    traj = Trajectory()
    await traj.consume(agent.stream("create a landing page"))

    dups, ratio = traj.duplicates()
    # user + 25×(asst + tool) = 51
    checks = [
        ok(
            "survives_to_budget_gracefully",
            traj.steps == 25 and len(traj.of("max_steps")) == 1 and len(traj.of("error")) == 0,
            f"steps={traj.steps}",
        ),
        ok(
            "history_saved_for_continue",
            len(agent.history) == 51,
            f"history={len(agent.history)} expected=51",
        ),
    ]
    return checks, {"steps": traj.steps, "dups": dups, "duplicate_ratio": round(ratio, 3)}


async def context_integrity() -> tuple[list[Check], dict[str, Any]]:
    big = FakeTool("read_files", output=BIG_OUTPUT)
    script = [
        result("", (call(f"c{i}", "read_files", {"paths": [f"f{i}.py"]}),)) for i in range(50)
    ]
    script.append(result("summary of everything read"))
    provider = ScriptedProvider(script)
    agent, _ = make_agent(provider, [big], max_steps=60)
    traj = Trajectory()
    await traj.consume(agent.stream("read the whole project"))

    ctx = agent.context
    canonical = sum(len(m.content or "") for m in agent.history)
    view = sum(len(m.content or "") for m in ctx.prune(agent.history))
    clipped = len(ctx.clip_tool_output(BIG_OUTPUT))

    checks = [
        ok(
            "clip_caps_output",
            0 < clipped < len(BIG_OUTPUT),
            f"clipped={clipped} original={len(BIG_OUTPUT)} "
            "(contract: oversized output must shrink)",
        ),
        ok("canonical_kept_complete", canonical > 1000, f"canonical={canonical}"),
        ok(
            "pruned_view_shrinks_hard",
            view < canonical // 5,
            f"view={view} canonical={canonical} ({view * 100 // max(1, canonical)}% of canonical)",
        ),
        ok("long_run_completes", "summary" in traj.final_text.lower(), traj.final_text[:50]),
    ]
    return checks, {"steps": traj.steps, "canonical": canonical, "view": view, "clipped": clipped}


async def event_flood_agent() -> tuple[list[Check], dict[str, Any]]:
    chunks = [f"word{i} " for i in range(300)]
    provider = ScriptedProvider([])

    async def fast_stream(messages: Any, tools: Any = None) -> Any:
        for c in chunks:
            yield type("E", (), {"kind": "text", "text": c})()
        yield type("E", (), {"kind": "done", "result": result("".join(chunks))})()

    provider.stream = fast_stream  # type: ignore[method-assign]
    agent, _ = make_agent(provider, [])
    traj = Trajectory()
    await traj.consume(agent.stream("explain the plan"))

    checks = [
        ok(
            "flood_delivered_complete",
            len(traj.of("text")) == 300,
            f"text_events={len(traj.of('text'))}",
        ),
        ok("throughput_healthy", traj.eps >= 500, f"eps={traj.eps:.0f}"),
        ok("wall_bounded", traj.wall < 3.0, f"wall={traj.wall:.2f}s"),
    ]
    return checks, {
        "events": len(traj.events),
        "eps": round(traj.eps),
        "wall_s": round(traj.wall, 2),
    }


async def tui_flood_responsive() -> tuple[list[Check], dict[str, Any]]:
    """🖥️ THE freeze test — real JimmyApp, real widgets, 200-chunk turn."""
    from tui.app import JimmyApp
    from tui.screens.home import HomeScreen
    from tui.widgets.rows import TurnSummary

    chunks = [f"word{i} " for i in range(200)]
    provider = ScriptedProvider([])

    async def fast_stream(messages: Any, tools: Any = None) -> Any:
        for c in chunks:
            yield type("E", (), {"kind": "text", "text": c})()
        yield type("E", (), {"kind": "done", "result": result("".join(chunks))})()

    provider.stream = fast_stream  # type: ignore[method-assign]

    wall = 0.0
    with TemporaryDirectory() as td:
        store = SessionStore(Path(td) / "s.db")
        app = JimmyApp(provider=cast(LLMProvider, provider), session_store=store)
        t0 = time.perf_counter()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            if isinstance(app.screen, HomeScreen):
                app.pop_screen()
                await pilot.pause()
            app.submit("explain the plan")
            completed = False
            for _ in range(1200):  # hang ⇒ FAIL, never a frozen runner
                if not app._busy:
                    completed = True
                    break
                await pilot.pause()
            wall = time.perf_counter() - t0
            summaries = list(app.chat.query(TurnSummary))
            texts = [t for role, t in app._transcript if role == "assistant"]
        store.close()

    checks = [
        ok("turn_completed_not_hung", completed, f"wall={wall:.1f}s"),
        ok("summary_row_rendered", len(summaries) == 1, f"summaries={len(summaries)}"),
        ok(
            "all_chunks_rendered",
            bool(texts) and "word199" in texts[-1],
            f"assistant_len={len(texts[-1]) if texts else 0}",
        ),
        ok("tui_wall_bounded", wall < 30.0, f"wall={wall:.1f}s (freeze feel ⇒ drive down)"),
    ]
    return checks, {"wall_s": round(wall, 1)}


async def resume_midtask() -> tuple[list[Check], dict[str, Any]]:
    """Mirror a 3-write turn into SQLite → 💥 crash → rebuild history →
    continuation finishes on the same record.  Asserts INVARIANTS
    (roles, tool outputs present, history grows) — not internal counts."""
    files = FakeTool("write_file", output="written")
    provider = ScriptedProvider(
        [
            result("", (call("c1", "write_file", {"path": "index.html", "content": "x"}),)),
            result("", (call("c2", "write_file", {"path": "styles.css", "content": "x"}),)),
            result("", (call("c3", "write_file", {"path": "app.js", "content": "x"}),)),
            result("done"),
        ]
    )
    agent, _ = make_agent(provider, [files])

    with TemporaryDirectory() as td:
        store = SessionStore(Path(td) / "s.db")
        sid = store.create_session(model="eval/model").id
        mirror = SessionRecorder(store, sid)
        mirror.user_message("build it")

        def record(ev: Any) -> None:
            if ev.type == "llm_start":
                mirror.begin_step()
            elif ev.type == "text":
                mirror.step_text(str(ev.data.get("text", "")))
            elif ev.type == "tool_start":
                mirror.tool_started(ev.data["id"], ev.data["name"], ev.data.get("arguments") or {})
            elif ev.type == "tool_done":
                out = ev.data.get("output")
                mirror.tool_finished(
                    ev.data["id"],
                    out if isinstance(out, str) else "",
                    float(ev.data.get("latency", 0)),
                )

        traj = Trajectory()
        await traj.consume(agent.stream("build it"), on_event=record)
        mirror.assistant_flush()

        history = store.build_history(sid)
        roles = [m.role for m in history]
        tool_msgs = [m for m in history if m.role == "tool"]

        survivor = type(agent)(agent.provider, tools=agent.tools, permissions=agent.permissions)
        survivor.history = history
        before = len(survivor.history)
        survivor.provider = ScriptedProvider([result("resumed and finished")])  # type: ignore[assignment]

        traj2 = Trajectory()
        await traj2.consume(survivor.stream("continue"))

        checks = [
            ok("pre_crash_work_recorded", len(files.calls) == 3, f"writes={len(files.calls)}"),
            ok(
                "history_rebuilt_from_sqlite",
                bool(roles)
                and roles[0] == "user"
                and len(tool_msgs) == 3
                and all(m.content for m in tool_msgs),
                f"rebuilt={len(history)} roles={roles[:4]}… tool_msgs={len(tool_msgs)}",
            ),
            ok("continuation_completes", bool(traj2.final_text), traj2.final_text[:50]),
            ok(
                "no_work_lost",
                len(survivor.history) > before,
                f"after={len(survivor.history)} before={before}",
            ),
        ]
        metrics: dict[str, Any] = {"rebuilt": len(history), "tool_msgs": len(tool_msgs)}
        store.close()

    return checks, metrics


BIG_SUITE = [
    ("landing_page_build", landing_page_build),
    ("dumb_loop_endurance", dumb_loop_endurance),
    ("context_integrity", context_integrity),
    ("event_flood_agent", event_flood_agent),
    ("tui_flood_responsive", tui_flood_responsive),
    ("resume_midtask", resume_midtask),
]
