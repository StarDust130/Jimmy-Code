from dataclasses import dataclass
from typing import Any


@dataclass
class LLMProviderError(RuntimeError):
    """Normalized error from an LLM provider."""

    message: str
    code: str
    retryable: bool = False
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.message


def normalize_groq_error(
    exc: Exception,
) -> LLMProviderError:
    """Convert a Groq SDK error into a Jimmy error."""

    status_code = getattr(
        exc,
        "status_code",
        None,
    )

    response = getattr(
        exc,
        "response",
        None,
    )

    if status_code is None and response is not None:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

    retry_after = _get_retry_after(
        exc,
        response,
    )

    if status_code == 401:
        return LLMProviderError(
            message=("❌ Groq authentication failed.\nCheck your GROQ_API_KEY."),
            code="authentication_error",
        )

    if status_code == 403:
        return LLMProviderError(
            message=("❌ Groq permission denied.\nCheck your account or model access."),
            code="permission_error",
        )

    if status_code == 404:
        return LLMProviderError(
            message=(f"❌ Groq model was not found.\nDetails: {exc}"),
            code="model_not_found",
        )

    if status_code == 413:
        return LLMProviderError(
            message=("❌ Groq request is too large.\nReduce the context and try again."),
            code="request_too_large",
        )

    if status_code == 429:
        message = "⚠️ Groq rate limit reached."

        if retry_after is not None:
            message += f"\nTry again in about {retry_after:g} seconds."

        return LLMProviderError(
            message=message,
            code="rate_limit",
            retryable=True,
            retry_after=retry_after,
        )

    if status_code in {500, 502, 503, 504}:
        return LLMProviderError(
            message=("⚠️ Groq is temporarily unavailable.\nPlease try again."),
            code="provider_unavailable",
            retryable=True,
            retry_after=retry_after,
        )

    if isinstance(exc, TimeoutError):
        return LLMProviderError(
            message=("⏱️ Groq request timed out.\nThe model did not respond in time."),
            code="timeout",
            retryable=True,
        )

    return LLMProviderError(
        message=(f"❌ Groq request failed.\n{exc}"),
        code="provider_error",
    )


def _get_retry_after(
    exc: Exception,
    response: Any,
) -> float | None:
    candidates = [
        getattr(exc, "headers", None),
        getattr(response, "headers", None) if response is not None else None,
    ]

    for headers in candidates:
        if not headers:
            continue

        value = headers.get("retry-after")

        if value is None:
            value = headers.get("Retry-After")

        if value is None:
            continue

        try:
            return float(value)
        except (TypeError, ValueError):
            continue

    return None
