"""LiteLLM-backed provider.

🌐 Works with ANY LiteLLM model string:
   gemini/gemini-3.5-flash-lite, openai/gpt-4o,
   anthropic/claude-sonnet-4-5, or custom api_base (z.ai, ollama…)

🔑 Token ground truth (the 900-vs-108 fix):
   * ONLY ``usage.prompt_tokens`` (input) and
     ``usage.completion_tokens`` (output) are trusted.
   * ``total_tokens`` is NEVER used as input — it is the SUM; reading
     it as input is the classic double-count.
   * If a provider omits ``total_tokens``, it is COMPUTED as
     input + output — so usage is never silently dropped (the old
     ``available`` check required total_tokens > 0 and threw away
     perfectly good usage from providers that omit it).
   * Aliases accepted: input_tokens / output_tokens (some
     OpenAI-compatible servers use those names).

🌊 Streaming: ``stream_options={"include_usage": True}`` asks the
   provider for a final usage chunk; the LAST usage-bearing chunk wins
   (OpenAI-compatible semantics: it is cumulative).  Providers that
   reject ``stream_options`` are retried once without it.
"""

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
        api_base: str | None = None,  # 🌐 custom provider URL (z.ai, ollama…)
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base

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

        if self.api_base:  # 🌐 pass through for custom providers
            kwargs["api_base"] = self.api_base

        return kwargs

    @staticmethod
    def _usage(raw: Any) -> Usage:
        """🔑 Canonical usage reader — the ONLY place tokens are read.

        * trusts prompt_tokens / completion_tokens (and their aliases)
        * computes total_tokens when the provider omits it
        * never derives tokens from text, never trusts total as input
        """
        if raw is None:
            return Usage()

        def read(*names: str) -> int:
            for name in names:
                value = getattr(raw, name, None)
                if value is None and isinstance(raw, dict):
                    value = raw.get(name)
                if value is None:
                    continue
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    continue
            return 0

        input_tokens = read("prompt_tokens", "input_tokens")
        output_tokens = read("completion_tokens", "output_tokens")
        total = read("total_tokens") or (input_tokens + output_tokens)

        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
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

        response: AsyncIterator[Any]
        try:
            response = cast(
                AsyncIterator[Any],
                await acompletion(**kwargs),
            )
        except Exception as exc:
            # 🛟 Some OpenAI-compatible servers reject stream_options.
            #    Retry once WITHOUT it — tokens may be missing for those,
            #    but the turn still works (better than crashing).
            if "stream_options" in kwargs and "stream_options" in str(exc).lower():
                kwargs.pop("stream_options", None)
                response = cast(
                    AsyncIterator[Any],
                    await acompletion(**kwargs),
                )
            else:
                raise

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

            if chunk_usage.total_tokens > 0:
                # LAST usage-bearing chunk wins (OpenAI-compatible:
                # the final one is the call's cumulative total).
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
