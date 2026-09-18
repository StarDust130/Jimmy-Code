"""🛡️ Agent-loop permission integration — ask · deny · session · full.

Self-contained fakes matching the loop's REAL contracts:
    * provider.stream() is STATEFUL — one result per call (the loop
      keeps the LAST done event of a stream, so yielding two results
      in one call would skip tool execution entirely)
    * tool.execute() returns an object with `.output` (the loop reads it)
    * usage carries input/output/total tokens + `available` for CostTracker

The fakes deliberately do NOT implement the full LLMProvider protocol
or the ToolRegistry class — like conftest.py, they are `cast()` into
the parameter types at the construction site.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel

from jimmy.agent.loop import Agent
from jimmy.llm.provider import LLMProvider
from jimmy.permissions import Decision, PermissionManager, PermissionMode
from jimmy.tools.core.registry import ToolRegistry

pytestmark = pytest.mark.asyncio

# ── fakes ──────────────────────────────────────────────────────────────


class _Args(BaseModel):
    command: str = ""
    path: str = ""


class FakeToolResult:
    """The loop reads `.output` off the tool's return value."""

    def __init__(self, output: str) -> None:
        self.output = output


class FakeUsage:
    """Everything CostTracker / llm_done bookkeeping might touch."""

    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 5
        self.total_tokens = 15
        self.cached_tokens = 0
        self.available = True


class FakeTool:
    name = "shell"
    args_schema = _Args

    def __init__(self) -> None:
        self.calls: list[_Args] = []

    def execute(self, args: _Args) -> FakeToolResult:
        self.calls.append(args)
        return FakeToolResult(f"ok:{args.command or args.path}")


class WriteTool(FakeTool):
    name = "write_file"


class _StreamEvent:
    def __init__(self, kind: str, text: str | None = None, result: Any = None) -> None:
        self.kind = kind
        self.text = text
        self.result = result


class FakeProvider:
    """Stateful provider — ONE result per stream() call.

    The agent loop keeps the LAST `done` event of each stream, so a
    fake that dumps every queued result into a single stream would end
    the turn before any tool call is ever inspected.  Real providers
    (and Jimmy's own test conftest) return one response per call.
    """

    model = "fake/test-model"

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self._calls = 0

    async def stream(self, messages: Any, tools: Any = None) -> AsyncIterator[_StreamEvent]:
        # Extra calls keep getting the final result (defensive).
        index = min(self._calls, len(self._results) - 1)
        self._calls += 1
        result = self._results[index]
        if result.content:
            yield _StreamEvent("text", text=result.content)
        yield _StreamEvent("done", result=result)


class FakeRegistry:
    def __init__(self, *tools: FakeTool) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> FakeTool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def schemas(self) -> list:
        return []


# ── helpers ────────────────────────────────────────────────────────────


def _call(call_id: str, name: str, arguments: dict) -> Any:
    return SimpleNamespace(id=call_id, name=name, arguments=arguments)


def _result(tool_calls: tuple = ()) -> Any:
    return SimpleNamespace(
        content="" if tool_calls else "all done",
        tool_calls=tool_calls,
        usage=FakeUsage(),
        model="fake/test-model",
    )


def _agent(mode: PermissionMode, tool: FakeTool, *calls: Any) -> tuple[Agent, FakeTool]:
    # call #1 → the tool-call result · call #2 → the final answer
    provider = FakeProvider([_result(tuple(calls)), _result()])
    perms = PermissionManager(mode=mode)
    agent = Agent(
        cast(LLMProvider, provider),
        tools=cast(ToolRegistry, FakeRegistry(tool)),
        permissions=perms,
        max_steps=5,
    )
    return agent, tool


async def _collect(agent: Agent, on_request: Any = None) -> list:
    events = []
    async for ev in agent.stream("go"):
        events.append(ev)
        if ev.type == "approval_request" and on_request is not None:
            on_request(ev.data)
    return events


# ── tests ──────────────────────────────────────────────────────────────


async def test_auto_mode_asks_for_shell_then_allow() -> None:
    agent, tool = _agent(PermissionMode.AUTO, FakeTool(), _call("c1", "shell", {"command": "ls"}))

    def approve(data: dict) -> None:
        assert data["risk"] == "dangerous"
        agent.permissions.gate.resolve(data["id"], Decision.ALLOW)

    events = await asyncio.wait_for(_collect(agent, approve), timeout=5)

    assert any(e.type == "approval_request" for e in events)
    assert any(e.type == "tool_done" for e in events)
    assert len(tool.calls) == 1


async def test_deny_blocks_execution_and_tells_model() -> None:
    agent, tool = _agent(
        PermissionMode.AUTO, FakeTool(), _call("c1", "shell", {"command": "rm -rf /"})
    )

    def deny(data: dict) -> None:
        agent.permissions.gate.resolve(data["id"], Decision.DENY)

    events = await asyncio.wait_for(_collect(agent, deny), timeout=5)

    assert any(e.type == "tool_denied" for e in events)
    assert any(e.type == "tool_error" for e in events) is False
    assert tool.calls == []
    # the model was told, in the saved history
    assert any(
        m.role == "tool" and m.content is not None and "Permission denied" in m.content
        for m in agent.history
    )


async def test_auto_mode_runs_writes_without_prompting() -> None:
    agent, tool = _agent(
        PermissionMode.AUTO, WriteTool(), _call("c1", "write_file", {"path": "a.py"})
    )
    events = await asyncio.wait_for(_collect(agent), timeout=5)

    assert not any(e.type == "approval_request" for e in events)
    assert any(e.type == "tool_done" for e in events)
    assert len(tool.calls) == 1


async def test_ask_mode_prompts_even_for_writes() -> None:
    agent, tool = _agent(
        PermissionMode.ASK, WriteTool(), _call("c1", "write_file", {"path": "a.py"})
    )

    def approve(data: dict) -> None:
        assert data["risk"] == "write"
        agent.permissions.gate.resolve(data["id"], Decision.ALLOW)

    events = await asyncio.wait_for(_collect(agent, approve), timeout=5)
    assert any(e.type == "approval_request" for e in events)
    assert len(tool.calls) == 1


async def test_session_grant_skips_approval() -> None:
    agent, tool = _agent(PermissionMode.AUTO, FakeTool(), _call("c1", "shell", {"command": "ls"}))
    agent.permissions.grant_for_session("shell")

    events = await asyncio.wait_for(_collect(agent), timeout=5)

    assert not any(e.type == "approval_request" for e in events)
    assert len(tool.calls) == 1


async def test_full_access_never_asks() -> None:
    agent, tool = _agent(PermissionMode.FULL, FakeTool(), _call("c1", "shell", {"command": "ls"}))
    events = await asyncio.wait_for(_collect(agent), timeout=5)

    assert not any(e.type == "approval_request" for e in events)
    assert len(tool.calls) == 1


async def test_bare_agent_defaults_to_no_prompts() -> None:
    # library default keeps old behavior — the TUI wires AUTO explicitly
    tool = FakeTool()
    provider = FakeProvider([_result((_call("c1", "shell", {"command": "ls"}),)), _result()])
    agent = Agent(
        cast(LLMProvider, provider),
        tools=cast(ToolRegistry, FakeRegistry(tool)),
        max_steps=5,
    )

    events = await asyncio.wait_for(_collect(agent), timeout=5)

    assert not any(e.type == "approval_request" for e in events)
    assert len(tool.calls) == 1


async def test_cancel_while_pending_cleans_gate() -> None:
    agent, _tool = _agent(
        PermissionMode.AUTO, FakeTool(), _call("c1", "shell", {"command": "sleep"})
    )

    task = asyncio.create_task(_collect(agent))
    for _ in range(100):
        if agent.permissions.gate.pending():
            break
        await asyncio.sleep(0.01)

    assert agent.permissions.gate.pending()  # 🛡️ approval is being awaited

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert agent.permissions.gate.pending() == ()  # 🛡️ no leak
