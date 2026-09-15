"""Jimmy's core tool-using agent loop."""

import time
from collections.abc import AsyncIterator, Callable

from jimmy.context import ContextBuilder
from jimmy.llm.provider import LLMProvider
from jimmy.llm.types import Message
from jimmy.tools.core.factory import create_default_registry
from jimmy.tools.core.registry import ToolRegistry

AgentEvent = Callable[[str, dict], None]


class Agent:
    """Runs the LLM ↔ tool loop."""

    def __init__(
        self,
        provider: LLMProvider,
        context: ContextBuilder | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.provider = provider
        self.context = context or ContextBuilder()
        self.tools = tools or create_default_registry()
        self.history: list[Message] = []

    async def stream(
        self,
        user_text: str,
        on_event: AgentEvent | None = None,
    ) -> AsyncIterator[str]:
        messages = self.context.build(user_text, self.history)

        while True:
            # 🤖 Ask the model
            llm_started = time.perf_counter()

            try:
                result = await self.provider.complete(
                    messages,
                    tools=self.tools.schemas(),
                )
            except Exception as exc:
                if on_event:
                    on_event(
                        "error",
                        {
                            "source": "llm",
                            "error": exc,
                        },
                    )
                raise

            llm_latency = time.perf_counter() - llm_started

            if on_event:
                on_event(
                    "llm_done",
                    {
                        "latency": llm_latency,
                        "usage": result.usage,
                        "model": result.model,
                    },
                )

            # ✅ Final answer
            if not result.tool_calls:
                answer = result.content

                self.history.append(Message(role="user", content=user_text))
                self.history.append(Message(role="assistant", content=answer))

                if answer:
                    yield answer

                return

            # 🛠️ Save tool request
            messages.append(
                Message(
                    role="assistant",
                    content=result.content or "",
                    tool_calls=result.tool_calls,
                )
            )

            # 🔧 Run tools
            for call in result.tool_calls:
                tool = self.tools.get(call.name)

                arguments = tool.args_schema.model_validate(call.arguments)

                if on_event:
                    on_event(
                        "tool_start",
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    )

                tool_started = time.perf_counter()

                try:
                    tool_result = tool.execute(arguments)
                except Exception as exc:
                    if on_event:
                        on_event(
                            "error",
                            {
                                "source": "tool",
                                "name": call.name,
                                "error": exc,
                            },
                        )
                    raise

                tool_latency = time.perf_counter() - tool_started

                if on_event:
                    on_event(
                        "tool_done",
                        {
                            "name": call.name,
                            "latency": tool_latency,
                        },
                    )

                messages.append(
                    Message(
                        role="tool",
                        content=tool_result.output,
                        tool_call_id=call.id,
                    )
                )
