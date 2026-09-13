"""Minimal V1 context builder.

V1 deliberately sends only stable instructions plus the current user message.
The smarter state-aware context system comes later.
"""

from collections.abc import Sequence

from jimmy.llm.types import Message

SYSTEM_PROMPT = """You are Jimmy, a terminal-native coding assistant.

You can inspect and modify the user's workspace using the available tools.

Use the smallest number of tools needed.
Prefer specific tools over shell when a specific tool exists.
Do not claim an action happened unless the tool result confirms it.
"""


class ContextBuilder:
    """Build the small, provider-independent context for V1."""

    def build(self, user_text: str, history: Sequence[Message] = ()) -> list[Message]:
        messages = [Message(role="system", content=SYSTEM_PROMPT)]
        messages.extend(history)
        messages.append(Message(role="user", content=user_text))
        return messages
