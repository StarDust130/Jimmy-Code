"""Prompt discipline + graceful max-steps + continue flow."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from jimmy.agent import Agent
from jimmy.context import SYSTEM_PROMPT
from jimmy.llm.types import LLMResult, LLMStreamEvent, ToolCall, Usage
from jimmy.tools.core.base import Tool, ToolResult
from jimmy.tools.core.registry import ToolRegistry

# ── prompt discipline ──────────────────────────────────────────────────


def test_prompt_has_scope_discipline() -> None:
    low = SYSTEM_PROMPT.lower()
    assert "exactly" in low and "nothing more" in low
    assert "one commit per file" in low
    assert "do not run tests" in low or "do not run verification" in low


def test_prompt_forbids_repeats_and_demands_batching() -> None:
    low = SYSTEM_PROMPT.lower()
    assert "never repeat a tool call" in low
    assert "batch" in low


# ── fake tool + always-calling provider ───────────────────────────────


class _NoopArgs(BaseModel):
    """No arguments."""


class NoopTool(Tool):
    name = "noop"
    description = "does nothing"

    args_schema = _NoopArgs

    def execute(self, arguments: BaseModel) -> ToolResult:
        return ToolResult(success=True, output="ok")


class LoopingProvider:
    """Always answers with one TOOL CALL — never finishes on its own,
    so max_steps is the only exit.  (A no-tool result legitimately
    ends the turn after one step — that was the bug in this fake.)"""

    model = "test/loop"

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools=()):
        self.calls += 1
        yield LLMStreamEvent(
            kind="done",
            result=LLMResult(
                content="",
                usage=Usage(input_tokens=10, output_tokens=2, total_tokens=12),
                model=self.model,
                tool_calls=(ToolCall(id=f"c{self.calls}", name="noop", arguments={}),),
            ),
        )


def _looping_agent(max_steps: int) -> Agent:
    registry = ToolRegistry()
    registry.register(NoopTool())
    return Agent(LoopingProvider(), tools=registry, max_steps=max_steps)


async def _collect(agent: Agent, text: str) -> list:
    return [event async for event in agent.stream(text)]


# ── graceful max-steps ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_max_steps_is_event_not_crash(anyio_backend) -> None:
    agent = _looping_agent(max_steps=2)
    events = await _collect(agent, "do a thing")

    kinds = [e.type for e in events]
    assert kinds[-1] == "max_steps"  # clean ending, no error
    assert "error" not in kinds


@pytest.mark.anyio
async def test_max_steps_saves_history_for_continue(anyio_backend) -> None:
    agent = _looping_agent(max_steps=2)
    await _collect(agent, "do a thing")

    # ⏸ progress saved: the continuation turn sees the prior work
    assert agent.history, "partial turn must be saved"
    assert agent.history[0].role == "user"
    assert agent.history[0].content == "do a thing"


@pytest.mark.anyio
async def test_continue_turn_resumes_context(anyio_backend) -> None:
    agent = _looping_agent(max_steps=1)
    await _collect(agent, "commit files one by one")

    events = await _collect(agent, "Continue the previous task.")
    assert any(e.type == "max_steps" for e in events)
