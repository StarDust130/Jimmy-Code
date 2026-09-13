"""LiteLLM-backed provider for V1."""

from collections.abc import AsyncIterator, Sequence

import litellm
from litellm import acompletion

from .types import LLMResult, Message, Usage


class LiteLLMProvider:
    """Keep LiteLLM details isolated from the agent and UI layers."""

    def __init__(self, *, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key

    @staticmethod
    def _messages(messages: Sequence[Message]) -> list[dict[str, str]]:
        return [{"role": message.role, "content": message.content} for message in messages]

    async def complete(self, messages: Sequence[Message]) -> LLMResult:
        kwargs = {
            "model": self.model,
            "messages": self._messages(messages),
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = await acompletion(**kwargs)
        message = response.choices[0].message
        usage_data = getattr(response, "usage", None)
        usage = Usage(
            input_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage_data, "total_tokens", 0) or 0,
        )
        return LLMResult(
            content=message.content or "",
            usage=usage,
            model=self.model,
        )

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[str]:
        kwargs = {
            "model": self.model,
            "messages": self._messages(messages),
            "stream": True,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = await acompletion(**kwargs)
        async for chunk in response:
            content = None
            try:
                content = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                content = None
            if content:
                yield content
