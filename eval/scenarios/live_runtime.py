"""🌐 Holder for the live-eval provider (set once by eval.run --live)."""

from __future__ import annotations

from typing import Any

_provider: Any | None = None


def set_provider(provider: Any) -> None:
    global _provider
    _provider = provider


def active_provider() -> Any:
    if _provider is None:
        raise RuntimeError("live provider not set — run `python -m eval.run --live`")
    return _provider