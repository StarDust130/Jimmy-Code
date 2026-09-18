"""Jimmy's context builder.

Builds a token-efficient context each LLM call:
 📌 system prompt (always, stable → cache friendly)
 ✂️ oversized outputs clipped on arrival (head+tail, bigger budget)
 🧾 old tool results collapsed to TOOL_STUB + a one-line SUMMARY of
    the gist — the model keeps the key fact, so it never re-runs a
    tool just to "remember" what it said (the token furnace fix)
 🎯 the last few tool results stay verbatim
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from jimmy.llm.types import Message

# 🧠 system prompt — the discipline layer.  This is the single biggest
#    lever for agent quality: it defines SCOPE (do exactly what was
#    asked), EFFICIENCY (batch calls, never repeat), and STOP conditions.
SYSTEM_PROMPT = """\
You are Jimmy, a senior software engineer working in the user's terminal.

## Prime directive
Do EXACTLY what the user asked — nothing more, nothing less.
- If asked to "commit all files one by one": create one commit per file \
(`git add <file>` then `git commit`), each with a short imperative \
message and one emoji. Do NOT run tests, do NOT fix bugs, do NOT \
review or refactor anything unless explicitly asked.
- Never expand scope. Extra "helpful" work wastes the user's money.
- If the request is ambiguous, pick the most literal interpretation \
and proceed — do not interrogate the user.

## Working rules
1. PLAN briefly (1-3 sentences) before your first tool call.
2. BATCH independent tool calls into ONE response (e.g. several \
`git diff` calls together). Every extra round-trip re-sends the whole \
conversation and costs real tokens.
3. NEVER repeat a tool call with the same arguments — you already have \
the result. Older results are summarized below; their key facts are \
kept in the summary line, so TRUST the summary instead of re-running.
4. Prefer compact output: `git diff --stat` / `--name-only` over full \
diffs; read only the files you need.
5. Use dedicated tools over shell when one exists.
6. Never claim an action happened unless a tool result confirms it.
7. STOP as soon as the goal is met: give a short final summary. Do not \
run verification, tests, or cleanup unless the user asked for them.
8. Git safety: never `push`, `reset --hard`, or force-anything unless \
explicitly asked.
"""

# 🪦 stable public stub constant (imported by tests and the package
#    __init__) — summary stubs START with this, so containment checks
#    like ``TOOL_STUB in message.content`` keep working.
TOOL_STUB = "[tool result summarized to save context]"


def _summarize(content: str) -> str:
    """First meaningful line of a tool result, trimmed — the gist."""
    for line in content.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return "(empty result)"


class ContextBuilder:
    """Token-efficient context builder.

    - clip_tool_output(): call when a tool result arrives (arrival-time)
    - prune():            call before each LLM call (summarizes old tools)
    - build():            convenience for simple one-shot use
    """

    def __init__(
        self,
        *,
        keep_raw_tools: int = 6,  # last N tool results stay verbatim
        max_tool_output: int = 8_000,  # chars allowed in one tool result
    ) -> None:
        self.keep_raw_tools = keep_raw_tools
        self.max_tool_output = max_tool_output

    # ─────────────────────────────────────
    # ✂️ clip on arrival
    # ─────────────────────────────────────

    def clip_tool_output(self, output: str) -> str:
        """Clip oversized tool output BEFORE it enters the loop.

        head 60% + tail 25% keeps both the summary AND the final state,
        which is what models actually need from long outputs.
        """
        if len(output) <= self.max_tool_output:
            return output

        head = output[: int(self.max_tool_output * 0.6)]
        tail = output[-int(self.max_tool_output * 0.25) :]
        dropped = len(output) - len(head) - len(tail)

        return f"{head}\n...[{dropped} chars truncated]...\n{tail}"

    # ─────────────────────────────────────
    # 🏗️ one-shot convenience
    # ─────────────────────────────────────

    def build(self, user_text: str, history: Sequence[Message] = ()) -> list[Message]:
        messages: list[Message] = [Message(role="system", content=SYSTEM_PROMPT)]
        messages.extend(self.prune(history))
        messages.append(Message(role="user", content=user_text))
        return messages

    # ─────────────────────────────────────
    # 🧹 prune: summarize old tool results
    # ─────────────────────────────────────

    def prune(self, history: Sequence[Message]) -> list[Message]:
        """Keep the last N tool results verbatim; older ones become
        stubs that START with TOOL_STUB and keep the gist — the model
        retains the key fact instead of re-running tools to recover it."""
        pruned: list[Message] = []
        raw_budget = self.keep_raw_tools

        # 🔄 walk backwards so the RECENT tools keep their budget
        for message in reversed(history):
            if message.role == "tool":
                if raw_budget <= 0:
                    gist = _summarize(message.content or "")
                    message = replace(
                        message,
                        content=(
                            f"{TOOL_STUB} — {gist}. Do not re-run this tool to see the full text."
                        ),
                    )
                else:
                    raw_budget -= 1

            pruned.append(message)

        pruned.reverse()
        return pruned
