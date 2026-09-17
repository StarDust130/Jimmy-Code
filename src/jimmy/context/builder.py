"""Jimmy's context builder.

Builds a token-efficient context each LLM call:
 📌 system prompt (always, stable → cache friendly)
 ✂️ old tool results collapsed to stubs
 🎯 only the last few tool results stay raw
 📏 oversized outputs clipped when they arrive
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from jimmy.llm.types import Message

# 🧠 core system prompt — keep lean and stable
SYSTEM_PROMPT = """You are Jimmy, a terminal-native coding assistant.

You can inspect and modify the user's workspace using the available tools.

Use the smallest number of tools needed.
Prefer specific tools over shell when a specific tool exists.
Do not claim an action happened unless the tool result confirms it.
"""

# 🪦 placeholder for consumed tool results
TOOL_STUB = "[tool result consumed — it succeeded]"


class ContextBuilder:
    """Token-efficient context builder.

    - clip_tool_output(): call when a tool result arrives (step 0)
    - build():            call before each LLM call (prunes history)
    """

    def __init__(
        self,
        *,
        keep_raw_tools: int = 2,  # last N tool results stay verbatim
        max_tool_output: int = 2_000,  # chars allowed in one tool result
    ) -> None:
        self.keep_raw_tools = keep_raw_tools
        self.max_tool_output = max_tool_output

    # ─────────────────────────────────────
    # ✂️ Step 0: clip when result arrives
    # ─────────────────────────────────────

    def clip_tool_output(self, output: str) -> str:
        """Clip oversized tool output BEFORE it enters the loop."""
        if len(output) <= self.max_tool_output:
            return output

        head = output[: self.max_tool_output // 2]
        tail = output[-self.max_tool_output // 4 :]
        dropped = len(output) - len(head) - len(tail)

        return f"{head}\n...[{dropped} chars truncated]...\n{tail}"

    # ─────────────────────────────────────
    # 🏗️ Build context for one LLM call
    # ─────────────────────────────────────

    def build(self, user_text: str, history: Sequence[Message] = ()) -> list[Message]:
        messages: list[Message] = [Message(role="system", content=SYSTEM_PROMPT)]
        messages.extend(self.prune(history))
        messages.append(Message(role="user", content=user_text))
        return messages

    # ─────────────────────────────────────
    # 🧹 Prune: collapse old tool results
    # ─────────────────────────────────────

    def prune(self, history: Sequence[Message]) -> list[Message]:
        """Keep only the last N tool results raw, stub the rest."""
        pruned: list[Message] = []
        raw_tool_budget = self.keep_raw_tools

        # 🔄 walk backwards so the RECENT tools keep their budget
        for message in reversed(history):
            if message.role == "tool" and raw_tool_budget <= 0:
                # 🪦 old tool output already consumed → stub it
                message = replace(message, content=TOOL_STUB)
            elif message.role == "tool":
                raw_tool_budget -= 1

            pruned.append(message)

        pruned.reverse()
        return pruned
