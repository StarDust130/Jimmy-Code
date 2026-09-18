"""🫱 Human error messages — no tracebacks in the user's face.

Maps common LLM failures (bad model, bad key, rate limit, network)
to a short headline + what the user should DO about it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FriendlyError:
    title: str  # 🏷️ one line, plain language
    hint: str  # 👉 what to do next
    is_model: bool = False  # 🤖 True → "change model" action makes sense


def friendly_error(exc: Exception) -> FriendlyError:
    """Classify an exception → (headline, hint). Never raises."""
    text = f"{type(exc).__name__}: {exc}".lower()

    # 🤖 model doesn't exist / no access
    if (
        "model_not_found" in text
        or "does not exist" in text
        or isinstance_name(exc, "NotFoundError")
    ):
        model = _extract_model(text)
        return FriendlyError(
            title=f"Model '{model}' isn't available on this provider",
            hint="It may be retired or need a different plan. Press ctrl+m to pick another model.",
            is_model=True,
        )

    # 🔑 auth
    if (
        "authentication" in text
        or "invalid api key" in text
        or "unauthorized" in text
        or "401" in text
    ):
        return FriendlyError(
            title="API key rejected",
            hint="Check the key in ~/.jimmy/.env or press ctrl+m to re-add it.",
        )

    # 💳 quota / billing
    if "quota" in text or "billing" in text or "402" in text or "insufficient" in text:
        return FriendlyError(
            title="Account out of quota or credit ",
            hint="Top up your provider account, or press ctrl+m to switch models.",
        )

    # ⏳ rate limit
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return FriendlyError(
            title="Rate limited by the provider",
            hint="Wait a few seconds and retry — or press ctrl+m to switch models.",
        )

    # 🌐 network
    if "timeout" in text or "connection" in text or "network" in text or "unreachable" in text:
        return FriendlyError(
            title="Can't reach the provider",
            hint="Check your internet connection, then hit retry.",
        )

    # 🌐 bad custom endpoint
    if "api_base" in text or "base_url" in text:
        return FriendlyError(
            title="Provider endpoint looks wrong",
            hint="Press ctrl+m, re-add the model with the correct API base URL.",
        )

    # 🤷 fallback — still friendly, no walls of text
    first_line = str(exc).strip().splitlines()[0][:160]
    return FriendlyError(title="Something went wrong", hint=first_line)


def _extract_model(text: str) -> str:
    """Pull the model name out of a provider error message."""
    import re

    m = re.search(r"model `([^`]+)`", text)
    return m.group(1) if m else "selected model"


def isinstance_name(exc: Exception, name: str) -> bool:
    return type(exc).__name__ == name
