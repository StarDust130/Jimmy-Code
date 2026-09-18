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

Permissions:
🛡️ EVERY tool execution passes ``PermissionManager.check()``.  A call
   that needs a human emits an ``approval_request`` event and the loop
   suspends on the ApprovalGate until the UI resolves it (allow / deny
   / session grant).  A denial goes BACK to the model as a tool
   message — never a crash, never a silent execution.
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
from jimmy.permissions import (
    Decision,
    PermissionManager,
    PermissionMode,
    classify_risk,
    describe_action,
)
from jimmy.tools.core.factory import create_default_registry
from jimmy.tools.core.registry import ToolRegistry

AgentEventType = Literal[
    "llm_start",
    "text",
    "llm_done",
    "tool_start",
    "tool_done",
    "tool_error",
    "approval_request",
    "tool_denied",
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
        permissions: PermissionManager | None = None,
    ) -> None:
        self.provider = provider
        self.context = context or ContextBuilder()
        self.tools = tools or create_default_registry()

        self.history: list[Message] = []
        self.max_steps = max_steps

        self.cost = CostTracker()  # 💰 session-wide tokens + cost

        # 🛡️ Permissions.  Library default = FULL (no prompting) so a
        #    bare Agent keeps its old behavior; the TUI app owns the
        #    session default (AUTO).
        self.permissions = permissions or PermissionManager(mode=PermissionMode.FULL)

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

            # 🔧 Execute tool calls — events STREAM out as they happen,
            #    so approval prompts reach the UI before we wait on them.
            tool_messages: list[Message] = []
            async for event in self._run_tool_calls(result.tool_calls, step, tool_messages):
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
    # 🔧 Tool execution (streams events, fills tool_messages)
    # ─────────────────────────────────────────

    async def _run_tool_calls(
        self,
        tool_calls: tuple[ToolCall, ...],
        step: int,
        tool_messages: list[Message],
    ) -> AsyncIterator[AgentEvent]:
        """Resolve → validate → 🛡️ authorize → execute each tool call.

        Streams events while running (approval prompts MUST reach the
        UI before the gate waits).  Never throws — errors and denials
        go BACK to the model as tool messages so it can correct itself.
        """
        for call in tool_calls:
            yield AgentEvent(
                type="tool_start",
                data={
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "step": step,  # 🧭 UI groups batches per step
                },
            )

            # 1️⃣ resolve the tool
            try:
                tool = self.tools.get(call.name)
            except Exception as exc:
                yield AgentEvent(
                    type="tool_error",
                    data={"id": call.id, "name": call.name, "error": exc},
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
                yield AgentEvent(
                    type="tool_error",
                    data={"id": call.id, "name": call.name, "error": exc},
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

            # 3️⃣ 🛡️ permission gate — EVERY execution passes the policy
            try:
                decision = self.permissions.check(call.name, call.arguments)
            except Exception:
                decision = Decision.ASK  # policy hiccup → fail closed

            if decision is Decision.ASK:
                request = self.permissions.gate.new_request(
                    tool_name=call.name,
                    arguments=call.arguments,
                    risk=classify_risk(call.name, call.arguments),
                    summary=describe_action(call.name, call.arguments),
                )
                yield AgentEvent(type="approval_request", data=request)

                decision = await self.permissions.gate.wait(str(request["id"]))

                if decision is not Decision.ALLOW:
                    yield AgentEvent(
                        type="tool_denied",
                        data={"id": call.id, "name": call.name, "reason": "denied by the user"},
                    )
                    tool_messages.append(
                        Message(
                            role="tool",
                            content=(
                                f"Permission denied by the user for tool '{call.name}'.\n"
                                "Do not silently retry the same call. Explain what you "
                                "wanted to do and ask how to proceed, or propose a "
                                "safer alternative."
                            ),
                            tool_call_id=call.id,
                        )
                    )
                    continue

            # 4️⃣ execute (approved / granted / full-access)
            tool_started = asyncio.get_running_loop().time()

            try:
                tool_result = await asyncio.to_thread(tool.execute, arguments)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                yield AgentEvent(
                    type="tool_error",
                    data={
                        "id": call.id,
                        "name": call.name,
                        "error": exc,
                        "latency": asyncio.get_running_loop().time() - tool_started,
                    },
                )
                tool_messages.append(
                    Message(
                        role="tool",
                        content=(f"Tool '{call.name}' failed.\n{type(exc).__name__}: {exc}"),
                        tool_call_id=call.id,
                    )
                )
                continue

            # 5️⃣ report success
            yield AgentEvent(
                type="tool_done",
                data={
                    "id": call.id,
                    "name": call.name,
                    "latency": asyncio.get_running_loop().time() - tool_started,
                },
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

    # ─────────────────────────────────────────
    # 💾 History (memory across user turns)
    # ─────────────────────────────────────────

    def _save_turn(self, turn: list[Message]) -> None:
        """Save the canonical record (minus system prompt) to history."""
        self.history.extend(turn[1:])  # 🚫 skip system prompt
