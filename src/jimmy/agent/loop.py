"""V1 agent loop: user message -> context -> one LLM answer."""

from collections.abc import AsyncIterator

from jimmy.context import ContextBuilder
from jimmy.llm.provider import LLMProvider
from jimmy.llm.types import Message


class Agent:
    """The future home of Jimmy's real tool-using loop."""

    def __init__(self, provider: LLMProvider, context: ContextBuilder | None = None) -> None:
        self.provider = provider
        self.context = context or ContextBuilder()
        self.history: list[Message] = []

    async def stream(self, user_text: str) -> AsyncIterator[str]:
        messages = self.context.build(user_text, self.history)
        answer_parts: list[str] = []

        async for chunk in self.provider.stream(messages):
            answer_parts.append(chunk)
            yield chunk

        answer = "".join(answer_parts)
        self.history.append(Message(role="user", content=user_text))
        self.history.append(Message(role="assistant", content=answer))
