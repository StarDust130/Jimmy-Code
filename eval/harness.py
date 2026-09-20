"""🧪 Harness — hermetic agent scenarios with recorded metrics.

Contracts mirrored from the real loop:
    provider.stream(messages, tools) → events .kind = "text" | "done";
        done.result carries .content / .tool_calls / .usage / .model
    tool.execute(args) → object with .output
    registry.get(name) · registry.schemas()

The loop VALIDATES arguments (pydantic) before executing, so
FakeTool.records are normalized to plain dicts via model_dump().
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any, cast

from pydantic import BaseModel

from jimmy.agent import Agent
from jimmy.llm.provider import LLMProvider
from jimmy.permissions import PermissionManager, PermissionMode
from jimmy.tools.core.registry import ToolRegistry

# ── data fakes ──────────────────────────────────────────────────────────


def make_usage(inp: int = 100, out: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=inp + out,
        cached_tokens=0,
        available=True,
    )


def call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(id=call_id, name=name, arguments=arguments)


def result(
    content: str = "", tool_calls: tuple = (), usage: Any | None = None, model: str = "eval/model"
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content, tool_calls=tool_calls, usage=usage or make_usage(), model=model
    )


class _StreamEvent:
    def __init__(self, kind: str, text: str | None = None, result: Any = None) -> None:
        self.kind = kind
        self.text = text
        self.result = result


class ScriptedProvider:
    """Stateful fake provider — ONE result per stream() call.

    Script items are pre-built results OR callables
    `(step:int, history_len:int) -> result`.  The last item replays on
    extra calls.  Captures the last prompt for context metrics.
    """

    model = "eval/model"

    def __init__(self, script: Sequence[Any]) -> None:
        self._script = list(script)
        self._i = 0
        self.calls = 0
        self.last_messages: list = []

    def _next(self) -> Any:
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return item(self._i, len(self.last_messages)) if callable(item) else item

    async def stream(self, messages: Any, tools: Any = None) -> AsyncIterator[_StreamEvent]:
        self.calls += 1
        self.last_messages = list(messages)
        out = self._next()
        if out.content:
            yield _StreamEvent("text", text=out.content)
        yield _StreamEvent("done", result=out)


class _Permissive(BaseModel):
    model_config = {"extra": "allow"}


class FakeTool:
    """Duck-typed tool — records executions (as plain dicts); optional
    failure script (`fail_first`) and forced delay."""

    name = "fake"
    args_schema = _Permissive

    def __init__(
        self, name: str, output: str = "ok", *, fail_first: int = 0, delay: float = 0.0
    ) -> None:
        self.name = name
        self._output = output
        self._fail_first = int(fail_first)
        self._delay = delay
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _as_dict(args: Any) -> dict[str, Any]:
        """The loop passes VALIDATED pydantic args — normalize to dict."""
        dump = getattr(args, "model_dump", None)
        return dump() if callable(dump) else dict(args)

    def execute(self, args: Any) -> SimpleNamespace:
        n = len(self.calls)
        self.calls.append(self._as_dict(args))
        if self._delay:
            time.sleep(self._delay)
        if n < self._fail_first:
            raise ValueError(f"injected failure #{n + 1}")
        return SimpleNamespace(output=self._output)


class FakeRegistry:
    def __init__(self, *tools: FakeTool) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> FakeTool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def schemas(self) -> list:
        return []

    def __getitem__(self, name: str) -> FakeTool:
        return self._tools[name]


def make_agent(
    provider: Any,
    tools: Sequence[FakeTool],
    *,
    mode: PermissionMode = PermissionMode.FULL,
    max_steps: int = 25,
) -> tuple[Agent, FakeRegistry]:
    """Real Agent + scripted provider + fake tools."""
    registry = FakeRegistry(*tools)
    agent = Agent(
        cast(LLMProvider, provider),
        tools=cast(ToolRegistry, registry),
        permissions=PermissionManager(mode=mode),
        max_steps=max_steps,
    )
    return agent, registry


# ── trajectory ──────────────────────────────────────────────────────────


class Trajectory:
    """Consumes an AgentEvent stream → metrics + timeline."""

    def __init__(self) -> None:
        self.events: list[Any] = []
        self._t0 = time.perf_counter()

    async def consume(self, agen: AsyncIterator[Any], on_event: Any = None) -> None:
        async for ev in agen:
            self.events.append(ev)
            if on_event is not None:
                on_event(ev)

    @property
    def wall(self) -> float:
        return time.perf_counter() - self._t0

    def of(self, kind: str) -> list[Any]:
        return [e for e in self.events if e.type == kind]

    @property
    def steps(self) -> int:
        return len(self.of("llm_start"))

    @property
    def tool_events(self) -> list[dict]:
        return [e.data for e in self.of("tool_start")]

    def tool_names(self) -> list[str]:
        return [str(d.get("name")) for d in self.tool_events]

    def duplicates(self) -> tuple[int, float]:
        """(count, ratio) — same tool + same arguments executed twice."""
        seen: set[str] = set()
        dups = total = 0
        for data in self.tool_events:
            total += 1
            key = json.dumps(
                (str(data.get("name")), data.get("arguments")), sort_keys=True, default=str
            )
            if key in seen:
                dups += 1
            seen.add(key)
        ratio = dups / total if total else 0.0
        return dups, ratio

    @property
    def final_text(self) -> str:
        return "".join(str(e.data.get("text", "")) for e in self.of("text")).strip()

    @property
    def tokens(self) -> tuple[int, int]:
        tin = tout = 0
        for e in self.of("llm_done"):
            u = e.data.get("usage")
            tin += int(getattr(u, "input_tokens", 0) or 0)
            tout += int(getattr(u, "output_tokens", 0) or 0)
        return tin, tout

    @property
    def eps(self) -> float:
        return len(self.events) / self.wall if self.wall > 0 else 0.0
