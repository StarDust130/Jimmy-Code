"""Jimmy's core tool-using agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from jimmy.context import ContextBuilder
from jimmy.llm.provider import LLMProvider
from jimmy.llm.types import (
    Message,
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

    async def stream(
        self,
        user_text: str,
    ) -> AsyncIterator[AgentEvent]:

        messages = self.context.build(
            user_text,
            self.history,
        )

        for step in range(
            1,
            self.max_steps + 1,
        ):
            yield AgentEvent(
                type="llm_start",
                data={
                    "step": step,
                    "model": self.provider.model,
                },
            )

            started = asyncio.get_running_loop().time()

            result = None

            try:
                async for event in self.provider.stream(
                    messages,
                    tools=self.tools.schemas(),
                ):
                    if event.kind == "text":
                        if event.text:
                            yield AgentEvent(
                                type="text",
                                data={
                                    "text": event.text,
                                },
                            )

                    elif event.kind == "done":
                        result = event.result

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                yield AgentEvent(
                    type="error",
                    data={
                        "source": "llm",
                        "error": exc,
                    },
                )
                raise

            latency = asyncio.get_running_loop().time() - started

            if result is None:
                error = RuntimeError("LLM stream ended without a result.")

                yield AgentEvent(
                    type="error",
                    data={
                        "source": "llm",
                        "error": error,
                    },
                )

                raise error

            yield AgentEvent(
                type="llm_done",
                data={
                    "step": step,
                    "model": (result.model or self.provider.model),
                    "latency": latency,
                    "usage": result.usage,
                },
            )

            # Keep the model response in THIS turn's context.
            messages.append(
                Message(
                    role="assistant",
                    content=result.content,
                    tool_calls=result.tool_calls,
                )
            )

            # ─────────────────────────────────────
            # Final answer
            # ─────────────────────────────────────

            if not result.tool_calls:
                self.history.append(
                    Message(
                        role="user",
                        content=user_text,
                    )
                )

                self.history.append(
                    Message(
                        role="assistant",
                        content=result.content,
                    )
                )

                return

            # ─────────────────────────────────────
            # Tool calls
            # ─────────────────────────────────────

            for call in result.tool_calls:
                tool_name = call.name

                # UI row starts BEFORE validation so an error
                # can update the same row.
                yield AgentEvent(
                    type="tool_start",
                    data={
                        "id": call.id,
                        "name": tool_name,
                        "arguments": call.arguments,
                    },
                )

                try:
                    tool = self.tools.get(tool_name)
                except Exception as exc:
                    yield AgentEvent(
                        type="tool_error",
                        data={
                            "id": call.id,
                            "name": tool_name,
                            "error": exc,
                        },
                    )

                    messages.append(
                        Message(
                            role="tool",
                            content=(f"Unknown tool '{tool_name}'. {exc}"),
                            tool_call_id=call.id,
                        )
                    )

                    continue

                # ─────────────────────────────
                # Validate arguments
                # ─────────────────────────────

                try:
                    arguments = tool.args_schema.model_validate(call.arguments)
                except Exception as exc:
                    # IMPORTANT:
                    # Do NOT throw.
                    # Give the error back to the model.
                    yield AgentEvent(
                        type="tool_error",
                        data={
                            "id": call.id,
                            "name": tool_name,
                            "error": exc,
                        },
                    )

                    messages.append(
                        Message(
                            role="tool",
                            content=(
                                f"Invalid arguments for "
                                f"tool '{tool_name}'.\n"
                                "Fix the arguments and "
                                "call the tool again.\n"
                                f"{exc}"
                            ),
                            tool_call_id=call.id,
                        )
                    )

                    continue

                # ─────────────────────────────
                # Execute
                # ─────────────────────────────

                tool_started = asyncio.get_running_loop().time()

                try:
                    tool_result = await asyncio.to_thread(
                        tool.execute,
                        arguments,
                    )

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    tool_latency = asyncio.get_running_loop().time() - tool_started

                    yield AgentEvent(
                        type="tool_error",
                        data={
                            "id": call.id,
                            "name": tool_name,
                            "error": exc,
                            "latency": tool_latency,
                        },
                    )

                    messages.append(
                        Message(
                            role="tool",
                            content=(f"Tool '{tool_name}' failed.\n{type(exc).__name__}: {exc}"),
                            tool_call_id=call.id,
                        )
                    )

                    continue

                tool_latency = asyncio.get_running_loop().time() - tool_started

                yield AgentEvent(
                    type="tool_done",
                    data={
                        "id": call.id,
                        "name": tool_name,
                        "latency": tool_latency,
                    },
                )

                messages.append(
                    Message(
                        role="tool",
                        content=(tool_result.output),
                        tool_call_id=call.id,
                    )
                )

        error = RuntimeError("Jimmy stopped because the maximum number of agent steps was reached.")

        yield AgentEvent(
            type="error",
            data={
                "source": "agent",
                "error": error,
            },
        )

        raise error
