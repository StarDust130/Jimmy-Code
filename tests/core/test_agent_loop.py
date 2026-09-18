"""🧪 Agent loop with fakes: 2 tool steps → final answer, pruning verified."""

import pytest
from pydantic import BaseModel

from jimmy.agent import Agent
from jimmy.context import TOOL_STUB
from jimmy.context.builder import ContextBuilder
from jimmy.llm.types import LLMResult, LLMStreamEvent, Message, ToolCall, Usage
from jimmy.tools.core.base import Tool, ToolResult

# ───────────────────────────
# 🤖 Fakes
# ───────────────────────────


class FakeProvider:
    """🤖 Step 1 + 2: call a tool. Step 3: final answer. Records every request."""

    model = "fake"

    def __init__(self) -> None:
        self.step = 0
        self.requests: list[list[Message]] = []

    def _result(self) -> LLMResult:
        if self.step in (1, 2):
            # 📞 two tool calls → guarantees one result goes "old"
            return LLMResult(
                content=f"reading file (step {self.step})",
                tool_calls=(ToolCall(id=f"c{self.step}", name="read", arguments={}),),
                usage=Usage(total_tokens=100),
            )
        return LLMResult(content="done!", usage=Usage(total_tokens=50))

    async def _stream(self, messages, tools=()):
        self.step += 1
        self.requests.append(list(messages))

        result = self._result()

        yield LLMStreamEvent(kind="text", text=result.content)
        yield LLMStreamEvent(kind="done", result=result)

    def stream(self, messages, tools=()):
        return self._stream(messages, tools)

    async def complete(self, messages, tools=()):  # ✅ satisfies LLMProvider
        self.step += 1
        self.requests.append(list(messages))
        return self._result()


class FakeToolArgs(BaseModel):
    """✅ Real pydantic model — matches Tool.args_schema type."""

    path: str = "fake.txt"


class FakeTool(Tool):
    """✅ Real Tool subclass returning huge output (forces clipping)."""

    def __init__(self) -> None:
        self.name = "read"
        self.description = "fake read tool"
        self.args_schema = FakeToolArgs

    def execute(self, arguments: FakeToolArgs) -> ToolResult:
        return ToolResult(
            success=True,
            output="BIG FILE " * 5000,  # 📏 way over the clip limit
        )


# ───────────────────────────
# 🧪 The loop test
# ───────────────────────────


@pytest.mark.asyncio
async def test_loop_runs_and_prunes():
    provider = FakeProvider()
    agent = Agent(provider=provider, context=ContextBuilder(keep_raw_tools=1))
    agent.tools.register(FakeTool())

    texts: list[str] = []
    async for event in agent.stream("fix auth bug"):
        if event.type == "text":
            texts.append(event.data["text"])

    # ✅ got the final answer streamed
    assert "".join(texts).endswith("done!")

    # ─────────────────────────────────────────
    # 🎯 THE money assertion: step 3 saw step 1's
    #    tool result STUBBED (it's now "old")
    # ─────────────────────────────────────────
    step3 = provider.requests[2]
    step3_tools = {m.tool_call_id: m.content for m in step3 if m.role == "tool"}

    assert step3_tools["c1"] == TOOL_STUB  # 🪦 old → stubbed
    assert step3_tools["c2"] is not None
    assert step3_tools["c2"] != TOOL_STUB  # 🎯 recent → raw
    assert "truncated" in str(step3_tools["c2"])  # ✂️ also clipped

    # ─────────────────────────────────────────
    # 💾 history: full exchange saved (minus system)
    # user → asst → tool → asst → tool → asst(final)
    # ─────────────────────────────────────────
    roles = [m.role for m in agent.history]
    assert roles == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]

    # ✂️ clipping verified in stored history too
    history_tools = [m.content for m in agent.history if m.role == "tool"]
    assert all(c is not None and "truncated" in c for c in history_tools)


@pytest.mark.asyncio
async def test_agent_can_swap_provider_mid_session():
    """🤖 New model continues the SAME conversation."""

    class Provider2(FakeProvider):
        model = "fake-2"

    agent = Agent(provider=FakeProvider(), context=ContextBuilder())
    agent.tools.register(FakeTool())
    agent.history.append(Message(role="user", content="old turn"))

    provider2 = Provider2()
    agent.set_provider(provider2)

    async for _ in agent.stream("new turn"):
        pass

    # ✅ new provider got the full history + new message
    first_request = provider2.requests[0]
    contents = [m.content for m in first_request]
    assert "old turn" in contents  # 💾 history survived the swap
    assert "new turn" in contents
