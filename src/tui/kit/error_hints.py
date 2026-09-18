"""🫱 Human-friendly error messages — no scary tracebacks in the UI.

Turns common LLM/provider failures into short, clear messages
that tell the user what happened and what to do next.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FriendlyError:
    title: str
    hint: str
    is_model: bool = False


def friendly_error(exc: Exception) -> FriendlyError:
    """Classify an exception → friendly title + next step. Never raises."""
    text = f"{type(exc).__name__}: {exc}".lower()

    # 🤖 Model unavailable
    if (
        "model_not_found" in text
        or "does not exist" in text
        or isinstance_name(exc, "NotFoundError")
    ):
        model = _extract_model(text)
        return FriendlyError(
            title=f"🤖 {model} disappeared on me 😭",
            hint="👉 This model isn't available anymore. Try another one with Ctrl+M.",
            is_model=True,
        )

    # 🔑 API key / authentication
    if (
        "authentication" in text
        or "invalid api key" in text
        or "unauthorized" in text
        or "401" in text
    ):
        return FriendlyError(
            title="🔑 Your API key got rejected 😵",
            hint="👉 Check your key in ~/.jimmy/.env, then try again.",
        )

    # 💳 Quota / billing
    if "quota" in text or "billing" in text or "402" in text or "insufficient" in text:
        return FriendlyError(
            title="💸 Free quota is finished 😭",
            hint="👉 You've used the free limit. Add your own API key/credits, or switch model.",
        )

    # ⏳ Rate limit
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return FriendlyError(
            title="🐌 Provider says: slow down 😅",
            hint="👉 Too many requests. Wait a few seconds and try again.",
        )

    # 🌐 Network
    if "timeout" in text or "connection" in text or "network" in text or "unreachable" in text:
        return FriendlyError(
            title="🌐 Internet went on vacation 🏖️",
            hint="👉 Check your connection and try again.",
        )

    # 🌐 Bad endpoint
    if "api_base" in text or "base_url" in text:
        return FriendlyError(
            title="🌐 Provider URL looks wrong 🤔",
            hint="👉 Open Ctrl+M and check the model/API endpoint.",
        )

    # 🤷 Unknown error
    first_line = str(exc).strip().splitlines()[0][:160]

    return FriendlyError(
        title="💥 Jimmy tripped over something 😵‍💫",
        hint=f"👉 {first_line}",
    )


def _extract_model(text: str) -> str:
    """Pull model name from provider error text."""
    import re

    match = re.search(r"model `([^`]+)`", text)
    return match.group(1) if match else "Selected model"


def isinstance_name(exc: Exception, name: str) -> bool:
    """Check exception class name without importing provider exceptions."""
    return type(exc).__name__ == name
