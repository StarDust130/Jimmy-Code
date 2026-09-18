"""🏭 Build a LiteLLMProvider from a ModelConfig.

🔑 Key resolution order:
  1. os.environ (real shell env / .zshrc / docker)
  2. ~/.jimmy/.env  ← keys pasted in the TUI are saved here; the factory
     loads that file ON DEMAND before giving up, so a key added through
     the TUI survives restarts with ZERO main.py changes.
"""

from __future__ import annotations

import os

from .litellm_provider import LiteLLMProvider
from .model_config import ModelConfig


class MissingAPIKeyError(Exception):
    """🔑 Raised when the model's API key env var isn't set."""


def create_provider(config: ModelConfig) -> LiteLLMProvider:
    """Build a provider for any LiteLLM-compatible model."""

    def _current() -> str | None:
        if not config.api_key_env:
            return None
        value = os.environ.get(config.api_key_env)
        value = value.strip() if value else ""
        return value or None

    api_key = _current()

    if config.api_key_env and api_key is None:
        # 🔑 Second chance: load ~/.jimmy/.env (where the TUI persists
        #    pasted keys).  Real environment variables always WIN —
        #    load_env_file never overrides existing os.environ entries.
        try:
            from .catalog import load_env_file

            load_env_file()
        except Exception:
            pass  # 🔑 env loading must never crash the boot

        api_key = _current()

    if config.api_key_env and api_key is None:
        raise MissingAPIKeyError(
            f"🔑 Missing API key: set {config.api_key_env} "
            f"in ~/.jimmy/.env or your environment to use '{config.name}'."
        )

    return LiteLLMProvider(
        model=config.name,
        api_key=api_key,
        # 🌐 custom providers (z.ai, openrouter, ollama…) pass api_base
        #    through — LiteLLM handles the rest
        **({"api_base": config.api_base} if config.api_base else {}),
    )
