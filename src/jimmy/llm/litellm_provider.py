"""LiteLLM-backed provider."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from litellm import acompletion

from .types import LLMResult, Message, ToolCall, Usage


class LiteLLMProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
    ) -> None:
        # 🤖 Model to use
        self.model = model

        # 🔑 Optional API key
        self.api_key = api_key

    @staticmethod
    def _message(message: Message) -> dict[str, Any]:
        # 📨 Convert our Message into LiteLLM format
        data: dict[str, Any] = {
            "role": message.role,
        }

        # 💬 Add text when present
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

        # 🔗 Link a tool result to its tool call
        if message.tool_call_id:
            data["tool_call_id"] = message.tool_call_id

        return data

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult:
        # 📦 Build the model request
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                self._message(message)
                for message in messages
            ],
        }

        # 🛠️ Give the model available tools
        if tools:
            kwargs["tools"] = list(tools)

        # 🔑 Add API key when provided
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # 🚀 Call the LLM
        response = await acompletion(**kwargs)

        # 📥 Get the model's response message
        message = response.choices[0].message

        # 🔧 Parse requested tool calls
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

        # 📊 Get token usage
        usage_data = getattr(response, "usage", None)

        usage = Usage(
            input_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
        )

        # 📤 Return a clean result for the agent
        return LLMResult(
            content=message.content or "",
            usage=usage,
            model=self.model,
            tool_calls=tuple(tool_calls),
        )