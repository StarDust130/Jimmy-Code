"""Agent loop: streaming, pruning, budget, and history saving.

Stubs now KEEP the gist (anti-re-run fix), so stub assertions check
``startswith(TOOL_STUB)`` + the gist instead of exact equality.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jimmy.agent import Agent
from jimmy.context import TOOL_STUB, ContextBuilder
from jimmy.llm.types import (
    LLMResult,
    LLMStreamEvent,
    Message,
    ToolCall,
    Usage,
)
from jimmy.tools.core.base import Tool, ToolResult
from jimmy.tools.core.registry import ToolRegistry

# ─────────────────────────────────────────
# 🧪 fakes
# ─────────────────────────────────────────


class FakeArgs(BaseModel):
    """Real pydantic schema — registry.schemas() calls
    args_schema.model_json_schema(), which only exists on BaseModel."""

    x: int = 0


class FakeTool(Tool):
    name = "fake_tool"
    description = "A fake tool for tests."
    args_schema = FakeArgs

    def execute(self, arguments: FakeArgs) -> ToolResult:
        return ToolResult(success=True, output="BIG FILE " * 20)


class FakeProvider:
    """Scripted provider: emits tool calls, then a final answer.

    Each call to stream() pops one script entry.  ``complete`` exists
    so the fake satisfies the LLMProvider Protocol (Pylance).
    """

    model = "fake/test-model"

    def __init__(self, script: list[LLMResult]) -> None:
        self.script = list(script)
        self.requests: list[list[Message]] = []

    async def complete(self, messages, tools=()) -> LLMResult:
        raise NotImplementedError("tests drive stream() only")

    async def stream(self, messages, tools=()):
        self.requests.append(list(messages))
        result = self.script.pop(0)

        for part in result.content.split(" "):
            if part:
                yield LLMStreamEvent(kind="text", text=part + " ")

        yield LLMStreamEvent(kind="done", result=result)


def _result(
    content: str,
    tool_calls: tuple[ToolCall, ...] = (),
    usage: Usage | None = None,
) -> LLMResult:
    return LLMResult(
        content=content,
        usage=usage or Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        model="fake/test-model",
        tool_calls=tool_calls,
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FakeTool())
    return registry


# ─────────────────────────────────────────
# tests
# ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_runs_and_prunes():
    provider = FakeProvider(
        [
            # step 1 → calls the fake tool
            _result(
                "running the tool",
                tool_calls=(ToolCall(id="c1", name="fake_tool", arguments={"x": 1}),),
            ),
            # step 2 → calls it again
            _result(
                "calling again",
                tool_calls=(ToolCall(id="c2", name="fake_tool", arguments={"x": 2}),),
            ),
            # step 3 → final answer
            _result("all done!"),
        ]
    )
    agent = Agent(provider=provider, context=ContextBuilder(keep_raw_tools=1))
    agent.tools = _registry()

    texts: list[str] = []
    async for event in agent.stream("fix auth bug"):
        if event.type == "text":
            texts.append(event.data["text"])

    # ✅ got the final answer streamed
    # ✅ got the final answer streamed (chunks carry trailing spaces,
    #    so the joined stream needs stripping before the check)
    assert "".join(texts).rstrip().endswith("done!")

    # ─────────────────────────────────────────
    # 🎯 THE money assertion: step 3 saw step 1's tool result STUBBED —
    #    with the GIST kept, so the model never re-runs it to remember.
    # ─────────────────────────────────────────
    step3 = provider.requests[2]
    step3_tools = {m.tool_call_id: (m.content or "") for m in step3 if m.role == "tool"}

    assert step3_tools["c1"].startswith(TOOL_STUB)
    assert "BIG FILE" in step3_tools["c1"]  # gist kept
    assert "Do not re-run" in step3_tools["c1"]  # anti-re-run nudge
    assert step3_tools["c2"] == "BIG FILE " * 20  # recent stays raw


@pytest.mark.asyncio
async def test_history_saved_after_final_answer():
    provider = FakeProvider([_result("all done!")])
    agent = Agent(provider=provider)
    agent.tools = _registry()

    async for _ in agent.stream("hello"):
        pass

    assert agent.history[-1].role == "assistant"
    assert agent.history[-1].content == "all done!"


@pytest.mark.asyncio
async def test_max_steps_is_event_not_crash():
    """🛑 Budget exhausted → max_steps EVENT + saved progress (no raise)."""
    looping = FakeProvider(
        [
            _result(
                "",
                tool_calls=(ToolCall(id="c1", name="fake_tool", arguments={}),),
            ),
            _result(
                "",
                tool_calls=(ToolCall(id="c2", name="fake_tool", arguments={}),),
            ),
        ]
    )
    agent = Agent(
        provider=looping,
        context=ContextBuilder(keep_raw_tools=5),
        max_steps=1,
    )
    agent.tools = _registry()

    kinds = [event.type async for event in agent.stream("loop forever")]

    assert kinds[-1] == "max_steps"
    assert "error" not in kinds

    # ⏸ progress saved for the ▶ Continue turn
    assert agent.history[0].role == "user"
    assert agent.history[0].content == "loop forever"
