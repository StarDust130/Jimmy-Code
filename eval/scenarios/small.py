"""🟢 SMALL suite — the floor: tool choice · args · recovery · gating.

Hermetic + deterministic.  These must stay 100 while big-task behavior
is being fixed.

History contract (verified): the loop saves
user + steps×(assistant + tool) messages — the user message IS part of
the record, so a 3-step turn with 2 tool calls = 6 history messages.
"""

from __future__ import annotations

from typing import Any

from jimmy.permissions import Decision, PermissionMode

from ..harness import FakeTool, ScriptedProvider, Trajectory, call, make_agent, result
from ..scoring import Check, ok


async def tool_choice_read() -> tuple[list[Check], dict[str, Any]]:
    """'find where JWT is handled' → search_files (NOT shell), 1 call, 2 steps."""
    search = FakeTool("search_files", output="src/auth.py: jwt.verify")
    shell = FakeTool("shell")
    provider = ScriptedProvider(
        [
            result("", (call("c1", "search_files", {"query": "jwt"}),)),
            result("JWT is verified in src/auth.py."),
        ]
    )
    agent, _ = make_agent(provider, [search, shell])
    traj = Trajectory()
    await traj.consume(agent.stream("find where JWT is handled"))

    calls = traj.tool_events
    checks = [
        ok(
            "uses_search_not_shell",
            len(calls) == 1 and calls[0]["name"] == "search_files",
            f"used={traj.tool_names()}",
        ),
        ok(
            "argument_correct",
            bool(calls) and calls[0]["arguments"].get("query") == "jwt",
            f"args={calls[0]['arguments'] if calls else {}}",
        ),
        ok("single_step_efficient", traj.steps == 2, f"steps={traj.steps} optimal=2"),
        ok("final_answer_answers", "auth" in traj.final_text.lower(), traj.final_text[:60]),
        ok("tool_executed_once", len(search.calls) == 1, f"exec={len(search.calls)}"),
    ]
    return checks, {"steps": traj.steps, "tools": traj.tool_names()}


async def error_recovery() -> tuple[list[Check], dict[str, Any]]:
    """Tool fails once → error goes back to the model → retry succeeds."""
    flaky = FakeTool("write_file", output="written", fail_first=1)
    provider = ScriptedProvider(
        [
            result("", (call("c1", "write_file", {"path": "", "content": "x"}),)),
            result("", (call("c2", "write_file", {"path": "a.py", "content": "x"}),)),
            result("written a.py"),
        ]
    )
    agent, _ = make_agent(provider, [flaky])
    traj = Trajectory()
    await traj.consume(agent.stream("write a.py"))

    # user + (asst + tool-err) + (asst + tool-ok) + final asst = 6
    checks = [
        ok(
            "failure_reported_not_crash",
            len(traj.of("tool_error")) == 1,
            f"tool_errors={len(traj.of('tool_error'))}",
        ),
        ok("model_recovered_next_step", len(flaky.calls) == 2, f"exec={len(flaky.calls)}"),
        ok("turn_completed", bool(traj.final_text), traj.final_text[:50]),
        ok(
            "history_consistent",
            len(agent.history) == 6,
            f"history={len(agent.history)} expected=6 (user, asst, tool-err, asst, tool-ok, asst)",
        ),
    ]
    return checks, {"steps": traj.steps, "recoveries": len(traj.of("tool_error"))}


async def permission_gate() -> tuple[list[Check], dict[str, Any]]:
    """🛡️ AUTO mode: shell gates → allow executes, deny blocks cleanly.
    A deadlock here IS the freeze class of bug."""
    shell = FakeTool("shell", output="listed")
    provider = ScriptedProvider(
        [result("", (call("c1", "shell", {"command": "ls"}),)), result("done")]
    )
    agent, _ = make_agent(provider, [shell], mode=PermissionMode.AUTO)

    traj = Trajectory()

    def on_event(ev: Any) -> None:
        if ev.type == "approval_request":
            agent.permissions.gate.resolve(ev.data["id"], Decision.ALLOW)

    await traj.consume(agent.stream("list files"), on_event=on_event)
    checks = [
        ok(
            "gate_prompted",
            len(traj.of("approval_request")) == 1,
            f"prompts={len(traj.of('approval_request'))}",
        ),
        ok(
            "no_deadlock_after_allow",
            len(shell.calls) == 1,
            f"exec={len(shell.calls)} (hang ⇒ freeze bug)",
        ),
        ok("turn_completed", bool(traj.final_text), traj.final_text[:50]),
    ]

    shell2 = FakeTool("shell")
    provider2 = ScriptedProvider(
        [result("", (call("c1", "shell", {"command": "ls"}),)), result("ok, skipped")]
    )
    agent2, _ = make_agent(provider2, [shell2], mode=PermissionMode.AUTO)
    traj2 = Trajectory()

    def on_event2(ev: Any) -> None:
        if ev.type == "approval_request":
            agent2.permissions.gate.resolve(ev.data["id"], Decision.DENY)

    await traj2.consume(agent2.stream("list files"), on_event=on_event2)
    checks += [
        ok(
            "deny_blocks_execution",
            len(traj2.of("tool_denied")) == 1 and len(shell2.calls) == 0,
            f"denied={len(traj2.of('tool_denied'))} exec={len(shell2.calls)}",
        ),
        ok(
            "deny_told_model_gracefully",
            any(
                m.role == "tool" and m.content and "denied" in m.content.lower()
                for m in agent2.history
            ),
            f"history={len(agent2.history)}",
        ),
    ]
    return checks, {"prompts": len(traj.of("approval_request"))}


async def max_steps_graceful() -> tuple[list[Check], dict[str, Any]]:
    """💀 Endless loop must end at the budget: ▶ continue, never crash."""
    tool = FakeTool("read_files", output="data")
    provider = ScriptedProvider(
        [lambda step, hlen: result("", (call(f"c{step}", "read_files", {"paths": ["x.py"]}),))]
    )
    agent, _ = make_agent(provider, [tool], max_steps=5)
    traj = Trajectory()
    await traj.consume(agent.stream("read everything"))

    # user + 5×(asst + tool) = 11
    checks = [
        ok("hits_budget_cleanly", traj.steps == 5, f"steps={traj.steps}"),
        ok(
            "max_steps_event_emitted",
            len(traj.of("max_steps")) == 1,
            f"events={len(traj.of('max_steps'))}",
        ),
        ok("no_error_event", len(traj.of("error")) == 0),
        ok(
            "history_saved_for_continue",
            len(agent.history) == 11,
            f"history={len(agent.history)} expected=11",
        ),
    ]
    return checks, {"steps": traj.steps}


SMALL_SUITE = [
    ("tool_choice_read", tool_choice_read),
    ("error_recovery", error_recovery),
    ("permission_gate", permission_gate),
    ("max_steps_graceful", max_steps_graceful),
]
