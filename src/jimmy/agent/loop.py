"""Jimmy's core tool-using agent loop.

🔁 One user turn = one loop of LLM calls + tool executions.

Token efficiency:
✂️ oversized tool outputs clipped when they arrive
🧹 the LLM sees a PRUNED VIEW before every call (old tool results →
   summary stubs that keep the gist); the canonical record is untouched
🛑 max_steps is NOT a crash: progress is saved and a ``max_steps``
   event is emitted — the TUI shows ▶ Continue and the next turn
   resumes the same conversation.

Multi-model:
🤖 set_provider() hot-swaps models mid-session (history kept)
💰 CostTracker accumulates session tokens + cost (ONE add per LLM call)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from jimmy.context import SYSTEM_PROMPT, ContextBuilder
from jimmy.llm.cost_tracker import CostTracker
from jimmy.llm.provider import LLMProvider
from jimmy.llm.types import LLMResult, Message, ToolCall
from jimmy.tools.core.factory import create_default_registry
from jimmy.tools.core.registry import ToolRegistry

AgentEventType = Literal[
    "llm_start",
    "text",
    "llm_done",
    "tool_start",
    "tool_done",
    "tool_error",
    "max_steps",
    "error",
]


@dataclass(frozen=True, slots=True)
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)


class Agent:
    """Runs the LLM ↔ tool loop."""

    def __init__(
        self,
        provider: LLMProvider,
        context: ContextBuilder | None = None,
        tools: ToolRegistry | None = None,
        *,
        max_steps: int = 25,
    ) -> None:
        self.provider = provider
        self.context = context or ContextBuilder()
        self.tools = tools or create_default_registry()

        self.history: list[Message] = []
        self.max_steps = max_steps

        self.cost = CostTracker()  # 💰 session-wide tokens + cost

    # ─────────────────────────────────────────
    # 🤖 Multi-model support (hot-swap)
    # ─────────────────────────────────────────

    def set_provider(self, provider: LLMProvider) -> None:
        """🤖 Swap the active model mid-session.  History is kept."""
        self.provider = provider

    # ─────────────────────────────────────────
    # 🔁 Main entry point (only generator)
    # ─────────────────────────────────────────

    async def stream(
        self,
        user_text: str,
    ) -> AsyncIterator[AgentEvent]:
        # 💾 CANONICAL RECORD — appended only, never pruned/mutated.
        turn: list[Message] = [
            Message(role="system", content=SYSTEM_PROMPT),
            *self.history,  # ✂️ already clipped when saved last turn
            Message(role="user", content=user_text),
        ]

        for step in range(1, self.max_steps + 1):
            # 👁️ LLM VIEW — pruned copy; old tool results become
            #    summary stubs.  `turn` keeps the clipped originals.
            messages = [turn[0], *self.context.prune(turn[1:])]

            yield AgentEvent(
                type="llm_start",
                data={"step": step, "model": self.provider.model},
            )

            started = asyncio.get_running_loop().time()
            result: LLMResult | None = None

            # 🌊 stream the LLM response
            try:
                async for event in self.provider.stream(
                    messages,
                    tools=self.tools.schemas(),
                ):
                    if event.kind == "text" and event.text:
                        yield AgentEvent(type="text", data={"text": event.text})

                    elif event.kind == "done":
                        result = event.result

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                yield AgentEvent(type="error", data={"source": "llm", "error": exc})
                raise

            latency = asyncio.get_running_loop().time() - started

            if result is None:
                error = RuntimeError("LLM stream ended without a result.")
                yield AgentEvent(type="error", data={"source": "llm", "error": error})
                raise error

            model_used = result.model or self.provider.model

            # 💰 accumulate session tokens + cost (single tracking point)
            self.cost.add(result.usage, model_used)

            yield AgentEvent(
                type="llm_done",
                data={
                    "step": step,
                    "model": model_used,
                    "latency": latency,
                    "usage": result.usage,
                    "usage_ok": result.usage.available,  # 📊 gaps visible
                    "session_totals": self.cost.totals(),
                },
            )

            # 💭 append the model response to the CANONICAL record
            turn.append(
                Message(
                    role="assistant",
                    content=result.content,
                    tool_calls=result.tool_calls,
                )
            )

            # ✅ Final answer → close the turn
            if not result.tool_calls:
                self._save_turn(turn)
                return

            # 🔧 Execute tool calls
            tool_events, tool_messages = await self._run_tool_calls(result.tool_calls, step)

            for event in tool_events:
                yield event

            # ✂️ tool_messages are ALREADY clipped → safe for the record
            turn.extend(tool_messages)

        # 🛑 Step budget exhausted — NOT an error.  The record is
        #    consistent here (assistant → tool results), so saving it
        #    preserves all progress; the TUI shows ▶ Continue.
        self._save_turn(turn)
        yield AgentEvent(
            type="max_steps",
            data={"steps": self.max_steps, "model": self.provider.model},
        )

    # ─────────────────────────────────────────
    # 🔧 Tool execution (returns events + messages)
    # ─────────────────────────────────────────

    async def _run_tool_calls(
        self,
        tool_calls: tuple[ToolCall, ...],
        step: int,
    ) -> tuple[list[AgentEvent], list[Message]]:
        """Resolve → validate → execute each tool call.

        Never throws — errors go BACK to the model as tool messages
        so it can correct itself.
        """
        events: list[AgentEvent] = []
        tool_messages: list[Message] = []

        for call in tool_calls:
            events.append(
                AgentEvent(
                    type="tool_start",
                    data={
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                        "step": step,  # 🧭 UI groups batches per step
                    },
                )
            )

            # 1️⃣ resolve the tool
            try:
                tool = self.tools.get(call.name)
            except Exception as exc:
                events.append(
                    AgentEvent(
                        type="tool_error",
                        data={"id": call.id, "name": call.name, "error": exc},
                    )
                )
                tool_messages.append(
                    Message(
                        role="tool",
                        content=f"Unknown tool '{call.name}'. {exc}",
                        tool_call_id=call.id,
                    )
                )
                continue

            # 2️⃣ validate arguments
            try:
                arguments = tool.args_schema.model_validate(call.arguments)
            except Exception as exc:
                events.append(
                    AgentEvent(
                        type="tool_error",
                        data={"id": call.id, "name": call.name, "error": exc},
                    )
                )
                tool_messages.append(
                    Message(
                        role="tool",
                        content=(
                            f"Invalid arguments for tool '{call.name}'.\n"
                            "Fix the arguments and call the tool again.\n"
                            f"{exc}"
                        ),
                        tool_call_id=call.id,
                    )
                )
                continue

            # 3️⃣ execute
            tool_started = asyncio.get_running_loop().time()

            try:
                tool_result = await asyncio.to_thread(tool.execute, arguments)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                events.append(
                    AgentEvent(
                        type="tool_error",
                        data={
                            "id": call.id,
                            "name": call.name,
                            "error": exc,
                            "latency": asyncio.get_running_loop().time() - tool_started,
                        },
                    )
                )
                tool_messages.append(
                    Message(
                        role="tool",
                        content=(f"Tool '{call.name}' failed.\n{type(exc).__name__}: {exc}"),
                        tool_call_id=call.id,
                    )
                )
                continue

            # 4️⃣ report success
            events.append(
                AgentEvent(
                    type="tool_done",
                    data={
                        "id": call.id,
                        "name": call.name,
                        "latency": asyncio.get_running_loop().time() - tool_started,
                    },
                )
            )

            # ✂️ clip oversized output BEFORE it enters the record
            clipped = self.context.clip_tool_output(tool_result.output)

            tool_messages.append(
                Message(
                    role="tool",
                    content=clipped,
                    tool_call_id=call.id,
                )
            )

        return events, tool_messages

    # ─────────────────────────────────────────
    # 💾 History (memory across user turns)
    # ─────────────────────────────────────────

    def _save_turn(self, turn: list[Message]) -> None:
        """Save the canonical record (minus system prompt) to history."""
        self.history.extend(turn[1:])  # 🚫 skip system prompt
