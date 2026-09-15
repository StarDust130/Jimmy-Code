"""LiteLLM-backed provider."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from litellm import acompletion

from .types import (
    LLMResult,
    LLMStreamEvent,
    Message,
    ToolCall,
    Usage,
)


class LiteLLMProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key

    @staticmethod
    def _message(
        message: Message,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": message.role,
        }

        if message.content is not None:
            data["content"] = message.content

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

        if message.tool_call_id:
            data["tool_call_id"] = message.tool_call_id

        return data

    def _kwargs(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(message) for message in messages],
        }

        if tools:
            kwargs["tools"] = list(tools)

        if self.api_key:
            kwargs["api_key"] = self.api_key

        return kwargs

    @staticmethod
    def _usage(raw: Any) -> Usage:
        if raw is None:
            return Usage()

        def read(name: str) -> int:
            value = getattr(raw, name, None)

            if value is None and isinstance(raw, dict):
                value = raw.get(name)

            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return Usage(
            input_tokens=read("prompt_tokens"),
            output_tokens=read("completion_tokens"),
            total_tokens=read("total_tokens"),
        )

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> LLMResult:
        kwargs = self._kwargs(messages, tools)

        response = cast(
            Any,
            await acompletion(**kwargs),
        )

        message = response.choices[0].message

        tool_calls: list[ToolCall] = []

        for call in getattr(message, "tool_calls", None) or []:
            raw_args = getattr(call.function, "arguments", None) or "{}"

            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        return LLMResult(
            content=message.content or "",
            usage=self._usage(getattr(response, "usage", None)),
            model=(getattr(response, "model", None) or self.model),
            tool_calls=tuple(tool_calls),
        )

    def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] = (),
    ) -> AsyncIterator[LLMStreamEvent]:
        return self._stream(messages, tools)

    async def _stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[LLMStreamEvent]:

        kwargs = self._kwargs(messages, tools)

        kwargs["stream"] = True

        # Request provider usage on the final stream chunk.
        kwargs["stream_options"] = {
            "include_usage": True,
        }

        response = cast(
            AsyncIterator[Any],
            await acompletion(**kwargs),
        )

        text_parts: list[str] = []

        tool_buffers: dict[
            int,
            dict[str, str],
        ] = {}

        usage = Usage()
        response_model = self.model

        async for chunk in response:
            model_name = getattr(
                chunk,
                "model",
                None,
            )

            if model_name:
                response_model = model_name

            chunk_usage = self._usage(getattr(chunk, "usage", None))

            if chunk_usage.available:
                usage = chunk_usage

            choices = getattr(
                chunk,
                "choices",
                None,
            )

            if not choices:
                # Important: usage-only final chunks can have
                # no choices.
                continue

            delta = getattr(
                choices[0],
                "delta",
                None,
            )

            if delta is None:
                continue

            content = getattr(
                delta,
                "content",
                None,
            )

            if content:
                text_parts.append(content)

                yield LLMStreamEvent(
                    kind="text",
                    text=content,
                )

            delta_tool_calls = (
                getattr(
                    delta,
                    "tool_calls",
                    None,
                )
                or []
            )

            for tool_delta in delta_tool_calls:
                index = int(
                    getattr(
                        tool_delta,
                        "index",
                        0,
                    )
                    or 0
                )

                buffer = tool_buffers.setdefault(
                    index,
                    {
                        "id": "",
                        "name": "",
                        "arguments": "",
                    },
                )

                call_id = getattr(
                    tool_delta,
                    "id",
                    None,
                )

                if call_id:
                    buffer["id"] = call_id

                function = getattr(
                    tool_delta,
                    "function",
                    None,
                )

                if function is None:
                    continue

                name = getattr(
                    function,
                    "name",
                    None,
                )

                if name:
                    buffer["name"] += name

                arguments = getattr(
                    function,
                    "arguments",
                    None,
                )

                if arguments:
                    buffer["arguments"] += arguments

        tool_calls: list[ToolCall] = []

        for index in sorted(tool_buffers):
            buffer = tool_buffers[index]

            if not buffer["name"]:
                continue

            raw_arguments = buffer["arguments"] or "{}"

            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                # Agent validation will safely report
                # malformed arguments back to the model.
                arguments = {}

            tool_calls.append(
                ToolCall(
                    id=(buffer["id"] or f"call_{index}"),
                    name=buffer["name"],
                    arguments=arguments,
                )
            )

        result = LLMResult(
            content="".join(text_parts),
            usage=usage,
            model=response_model,
            tool_calls=tuple(tool_calls),
        )

        yield LLMStreamEvent(
            kind="done",
            result=result,
        )
