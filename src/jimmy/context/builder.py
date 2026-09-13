"""Minimal V1 context builder.

V1 deliberately sends only stable instructions plus the current user message.
The smarter state-aware context system comes later.
"""

from collections.abc import Sequence

from jimmy.llm.types import Message

SYSTEM_PROMPT = """You are Jimmy, a terminal-native coding assistant.
For V1 you are chat-only: do not claim to edit files or run commands because tools are not enabled yet.
Be concise, useful, and honest about what you can do."""


class ContextBuilder:
    """Build the small, provider-independent context for V1."""

    def build(self, user_text: str, history: Sequence[Message] = ()) -> list[Message]:
        messages = [Message(role="system", content=SYSTEM_PROMPT)]
        messages.extend(history)
        messages.append(Message(role="user", content=user_text))
        return messages
