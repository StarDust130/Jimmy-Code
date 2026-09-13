"""LiteLLM-backed provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from litellm import acompletion

from .types import LLMResult, Message, ToolCall, Usage


class LiteLLMProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
    ) -> None:
        # 1️⃣ Store the model
        self.model = model

        # 2️⃣ Store the optional API key
        self.api_key = api_key

    @staticmethod
    def _message(message: Message) -> dict[str, Any]:
        # 3️⃣ Convert our message to LiteLLM format
        data: dict[str, Any] = {
            "role": message.role,
        }

        # 💬 Add message text
        if message.content is not None:
            data["content"] = message.content

        # 🔧 Add previous tool calls
        if message.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]

        # 🔗 Link tool result to its call
        if message.tool_call_id:
            data["tool_call_id"] = message.tool_call_id

        return data

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult:
        # 4️⃣ Build the model request
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(message) for message in messages],
        }

        # 🛠️ Give the model available tools
        if tools:
            kwargs["tools"] = list(tools)

        # 🔑 Add API key
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # 5️⃣ Get one complete response
        response = cast(
            Any,
            await acompletion(**kwargs),
        )

        # 6️⃣ Read the model message
        message = response.choices[0].message

        # 7️⃣ Parse tool calls
        tool_calls: list[ToolCall] = []

        for call in getattr(message, "tool_calls", None) or []:
            arguments = json.loads(call.function.arguments)

            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        # 8️⃣ Read token usage
        usage_data = getattr(response, "usage", None)

        usage = Usage(
            input_tokens=getattr(
                usage_data,
                "prompt_tokens",
                0,
            )
            or 0,
            output_tokens=getattr(
                usage_data,
                "completion_tokens",
                0,
            )
            or 0,
            total_tokens=getattr(
                usage_data,
                "total_tokens",
                0,
            )
            or 0,
        )

        # 9️⃣ Return our standard result
        return LLMResult(
            content=message.content or "",
            usage=usage,
            model=self.model,
            tool_calls=tuple(tool_calls),
        )

    async def stream(
        self,
        messages: Sequence[Message],
    ) -> AsyncIterator[str]:
        # 🔟 Build the streaming request
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(message) for message in messages],
            "stream": True,
        }

        # 🔑 Add API key
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # 1️⃣1️⃣ Get the streaming response
        response = cast(
            AsyncIterator[Any],
            await acompletion(**kwargs),
        )

        # 1️⃣2️⃣ Read chunks as they arrive
        async for chunk in response:
            content = None

            try:
                content = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                content = None

            # 📤 Send each text chunk
            if content:
                yield content
