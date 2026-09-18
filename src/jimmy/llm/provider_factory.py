"""🏭 Build a LiteLLMProvider from a ModelConfig."""

from __future__ import annotations

import os

from .litellm_provider import LiteLLMProvider
from .model_config import ModelConfig


class MissingAPIKeyError(Exception):
    """🔑 Raised when the model's API key env var isn't set."""


def create_provider(config: ModelConfig) -> LiteLLMProvider:
    """Build a provider for any LiteLLM-compatible model."""
    api_key: str | None = None

    if config.api_key_env:
        api_key = os.environ.get(config.api_key_env)

        if not api_key:
            raise MissingAPIKeyError(
                f"🔑 Missing API key: set {config.api_key_env} "
                f"in your .env or environment to use '{config.name}'."
            )

    return LiteLLMProvider(
        model=config.name,
        api_key=api_key,
        # 🌐 custom providers (z.ai, openrouter, ollama…) pass api_base
        #    through — LiteLLM handles the rest
        **({"api_base": config.api_base} if config.api_base else {}),
    )
