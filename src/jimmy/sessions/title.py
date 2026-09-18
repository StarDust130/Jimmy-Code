"""🏷️ Session titles — heuristic fallback + AI generation.

AI generation streams a tiny prompt through the ACTIVE provider (the
same one already carrying the conversation — no new config, no new
secrets).  Every failure falls back to the heuristic; title generation
must never disturb the chat.
"""

from __future__ import annotations

from typing import Any

from jimmy.llm.types import Message

_TITLE_SYSTEM = (
    "You name coding-agent chat sessions. Reply with ONLY the title: "
    "3-6 words, no quotes, no trailing punctuation, no emoji."
)


def sanitize_title(raw: str, limit: int = 48) -> str:
    """Collapse whitespace, strip wrapping quotes/backticks, clip."""
    text = " ".join(str(raw or "").split())
    for ch in ("`", '"', "'", "“", "”", "‘", "’", "*"):
        text = text.replace(ch, "")
    text = " ".join(text.strip(" .:-–—").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def heuristic_title(user_texts: list[str], limit: int = 48) -> str:
    """Fallback: the first user message, clipped."""
    for text in user_texts:
        clean = sanitize_title(text, limit)
        if clean:
            return clean
    return "New session"


async def generate_title(provider: Any, user_texts: list[str], limit: int = 48) -> str | None:
    """Stream a title from the active provider; None on empty output.

    Raises on provider failure — callers fall back to the heuristic.
    """
    context = "\n".join(f"- {t}" for t in user_texts if t)[:2000]
    if not context:
        return None
    messages = [
        Message(role="system", content=_TITLE_SYSTEM),
        Message(role="user", content=f"Name this session:\n{context}"),
    ]
    parts: list[str] = []
    async for event in provider.stream(messages, tools=[]):
        kind = getattr(event, "kind", "")
        if kind == "text":
            chunk = getattr(event, "text", None)
            if chunk:
                parts.append(chunk)
        elif kind == "done":
            break
    return sanitize_title("".join(parts), limit) or None
