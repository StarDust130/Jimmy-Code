"""Jimmy's core tool-using agent loop.

🔁 One user turn = one loop of LLM calls + tool executions.

Token efficiency (Option A):
✂️ oversized tool outputs clipped when they arrive
🧹 the LLM sees a PRUNED VIEW of the turn before every call
   (old tool results → stubs); the canonical record is never touched
💾 the canonical record (clipped, unstubbed) is saved to history
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from jimmy.context import SYSTEM_PROMPT, ContextBuilder
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

    # ─────────────────────────────────────────
    # 🔁 Main entry point (only generator)
    # ─────────────────────────────────────────

    async def stream(
        self,
        user_text: str,
    ) -> AsyncIterator[AgentEvent]:
        # 💾 CANONICAL RECORD — the source of truth for this turn.
        #    Only ever APPENDED to. Never pruned. Never mutated.
        #    Structure: [system] + prior history + [user message]
        turn: list[Message] = [
            Message(role="system", content=SYSTEM_PROMPT),
            *self.history,  # ✂️ already clipped when saved last turn
            Message(role="user", content=user_text),
        ]

        for step in range(1, self.max_steps + 1):
            # 👁️ LLM VIEW — fresh pruned copy of the canonical record.
            #    Old tool results (beyond keep_raw_tools) appear as
            #    stubs HERE ONLY; `turn` keeps the clipped originals.
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

            yield AgentEvent(
                type="llm_done",
                data={
                    "step": step,
                    "model": (result.model or self.provider.model),
                    "latency": latency,
                    "usage": result.usage,  # 📊 watch this stay flat across steps
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

            # ─────────────────────────────────
            # ✅ Final answer → close the turn
            # ─────────────────────────────────

            if not result.tool_calls:
                self._save_turn(turn)
                return

            # ─────────────────────────────────
            # 🔧 Execute tool calls
            # (helper returns events, we yield them here)
            # ─────────────────────────────────

            tool_events, tool_messages = await self._run_tool_calls(result.tool_calls)

            for event in tool_events:
                yield event

            # ✂️ tool_messages are ALREADY clipped → safe for the record
            turn.extend(tool_messages)

        # 🛑 step budget exhausted
        error = RuntimeError("Jimmy stopped because the maximum number of agent steps was reached.")
        yield AgentEvent(type="error", data={"source": "agent", "error": error})
        raise error

    # ─────────────────────────────────────────
    # 🔧 Tool execution (returns events + messages)
    # ─────────────────────────────────────────

    async def _run_tool_calls(
        self,
        tool_calls: tuple[ToolCall, ...],
    ) -> tuple[list[AgentEvent], list[Message]]:
        """Resolve → validate → execute each tool call.

        Never throws — errors go BACK to the model as tool messages
        so it can correct itself.
        """
        events: list[AgentEvent] = []
        tool_messages: list[Message] = []

        for call in tool_calls:
            # UI row starts BEFORE validation so an error
            # can update the same row.
            events.append(
                AgentEvent(
                    type="tool_start",
                    data={
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
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
        """Save the canonical record (minus system prompt) to history.

        The record contains CLIPPED (never stubbed) tool results,
        so the NEXT user turn remembers the real content of what
        Jimmy read/edited. Stubs are a VIEW-only concern, applied
        fresh by ContextBuilder.prune() before each LLM call.
        """
        self.history.extend(turn[1:])  # 🚫 skip system prompt
