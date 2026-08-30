from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any


class RequestLimiter:
    """Sequential sliding-window request limiter."""

    def __init__(
        self,
        requests_per_minute: int,
        window_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self.limit = requests_per_minute
        self.window = window_seconds
        self._timestamps: deque[float] = deque()
        self._sleep = sleep
        self.wait_count = 0
        self.wait_seconds = 0.0

    def before_request(self) -> float:
        waited = 0.0

        while True:
            now = time.monotonic()

            while self._timestamps and now - self._timestamps[0] >= self.window:
                self._timestamps.popleft()

            if len(self._timestamps) < self.limit:
                self._timestamps.append(now)
                if waited:
                    self.wait_count += 1
                    self.wait_seconds += waited
                return waited

            delay = max(0.05, self.window - (now - self._timestamps[0]))
            self._sleep(delay)
            waited += delay


class RateLimitedProvider:
    """Wrap Jimmy's real provider with request limiting and 429 retries."""

    def __init__(
        self,
        provider: Any,
        limiter: RequestLimiter,
        max_rate_limit_retries: int = 6,
    ) -> None:
        self._provider = provider
        self._limiter = limiter
        self._max_retries = max_rate_limit_retries

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("chat", *args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        self._limiter.before_request()
        method = getattr(self._provider, "stream", None)
        if method is None or not callable(method):
            raise AttributeError("Provider does not support streaming")
        return method(*args, **kwargs)

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self._max_retries + 1):
            self._limiter.before_request()
            try:
                method = getattr(self._provider, name)
                return method(*args, **kwargs)
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt >= self._max_retries:
                    raise

                delay = _retry_delay(exc, attempt)
                self._limiter._sleep(delay)
                self._limiter.wait_count += 1
                self._limiter.wait_seconds += delay

        raise RuntimeError("Rate-limit retry loop ended unexpectedly")


def _is_rate_limit_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code in {429, "429", "rate_limit", "resource_exhausted"}:
        return True

    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "too many requests",
            "resource exhausted",
            "quota",
        )
    )


def _retry_delay(exc: Exception, attempt: int) -> float:
    for attr in ("retry_after", "retry_after_seconds"):
        value = getattr(exc, attr, None)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

    return min(60.0, 5.0 * (2 ** attempt))
