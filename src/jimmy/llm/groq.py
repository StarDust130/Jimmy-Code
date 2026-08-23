import json
from typing import Any, cast

from groq import Groq
from groq.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from jimmy.llm.base import LLMProvider
from jimmy.llm.models import LLMResponse, ToolCall


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = Groq(api_key=api_key)
        self.model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:

        groq_messages = cast(
            list[ChatCompletionMessageParam],
            messages,
        )

        groq_tools = cast(
            list[ChatCompletionToolParam],
            tools or [],
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=groq_messages,
            tools=groq_tools,
            tool_choice="auto",
        )

        message = response.choices[0].message

        tool_calls: list[ToolCall] = []

        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid tool arguments from model for {call.function.name}"
                ) from exc

            if not isinstance(arguments, dict):
                raise TypeError(f"Tool arguments must be an object for {call.function.name}")

            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }

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

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )
