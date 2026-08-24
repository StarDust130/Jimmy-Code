import json
from typing import Any, cast

from groq import Groq
from groq.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from jimmy.llm.base import (
    LLMProvider,
    LLMResponse,
    ToolCall,
)
from jimmy.llm.errors import normalize_groq_error


class GroqProvider(LLMProvider):
    """Groq implementation for Jimmy."""

    def __init__(
        self,
        api_key: str,
        model: str,
    ) -> None:
        self.model = model

        self.client = Groq(
            api_key=api_key,
            timeout=60.0,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
    ) -> LLMResponse:
        # 🔄 Convert Jimmy's generic messages/tools
        # into the types expected by the Groq SDK.
        groq_messages = cast(
            list[ChatCompletionMessageParam],
            messages,
        )

        groq_tools = cast(
            list[ChatCompletionToolParam],
            tools or [],
        )

        # 🤖 Call Groq.
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=groq_messages,
                tools=groq_tools or None,
                tool_choice=tool_choice or "auto",
            )
        except Exception as exc:
            # 🛡️ Normalize provider-specific errors.
            raise normalize_groq_error(exc) from exc

        # 📩 Read model response.
        message = response.choices[0].message

        tool_calls: list[ToolCall] = []

        # 🔧 Parse tool calls.
        if message.tool_calls:
            for call in message.tool_calls:
                arguments = self._parse_arguments(
                    call.function.arguments,
                )

                tool_calls.append(
                    ToolCall(
                        id=call.id,
                        name=call.function.name,
                        arguments=arguments,
                    )
                )

        # 💬 Build assistant message.
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }

        # 🔧 Preserve tool calls for the next LLM turn.
        if message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ]

        # 📦 Return Jimmy's normalized response.
        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )

    @staticmethod
    def _parse_arguments(
        arguments: str,
    ) -> dict[str, Any]:
        # 🧩 Parse tool arguments from JSON.
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("Model returned invalid JSON tool arguments.") from exc

        # 🛡️ Tool arguments must be an object.
        if not isinstance(value, dict):
            raise TypeError("Tool arguments must be a JSON object.")

        return value
