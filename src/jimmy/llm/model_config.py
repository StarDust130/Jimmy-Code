"""🤖 Model configuration + local storage.

💾 Saved at ~/.jimmy/models.json
📦 One model marked active
🔑 API keys stay LOCAL — never shipped in code
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """One user-configurable model. `name` = LiteLLM model string."""

    name: str
    api_key_env: str = ""
    api_base: str | None = None
    is_active: bool = False


# 🌟 Built-in default — always present, never deleted
DEFAULT_MODEL = ModelConfig(
    name="gemini/gemini-3.5-flash-lite",
    api_key_env="GEMINI_API_KEY",
    is_active=True,
)


def default_models() -> list[ModelConfig]:
    """Return the built-in default model."""
    return [DEFAULT_MODEL]


class ModelStore:
    """💾 Load/save user models from ~/.jimmy/models.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".jimmy" / "models.json")

    def load(self) -> list[ModelConfig]:
        """Load models, falling back to the built-in default."""
        if not self.path.exists():
            return default_models()

        try:
            raw = json.loads(self.path.read_text())
            return [ModelConfig(**item) for item in raw]
        except (json.JSONDecodeError, TypeError, KeyError):
            # 🛟 Corrupted file → safe fallback, never crash the TUI
            return default_models()

    def save(self, models: list[ModelConfig]) -> None:
        """Save models. Ensures exactly ONE active model."""
        active = [m for m in models if m.is_active]

        if len(active) != 1:
            raise ValueError("Exactly one model must be active.")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                [asdict(model) for model in models],
                indent=2,
            )
        )

    def add(self, model: ModelConfig) -> list[ModelConfig]:
        """➕ Add a model (no duplicates by name)."""
        models = self.load()

        if any(m.name == model.name for m in models):
            raise ValueError(f"Model already exists: {model.name}")

        models.append(model)
        self.save(models)
        return models

    def remove(self, name: str) -> list[ModelConfig]:
        """🗑️ Remove a model. Default model cannot be removed."""
        models = self.load()

        if name == DEFAULT_MODEL.name:
            raise ValueError("Cannot remove the built-in default model.")

        remaining = [m for m in models if m.name != name]

        if len(remaining) == len(models):
            raise ValueError(f"Unknown model: {name}")

        # 🛟 If we removed the active model → activate default
        if not any(m.is_active for m in remaining):
            remaining = [
                ModelConfig(
                    **{
                        **asdict(m),
                        "is_active": m.name == DEFAULT_MODEL.name,
                    }
                )
                for m in remaining
            ]

        self.save(remaining)
        return remaining

    def set_active(self, name: str) -> list[ModelConfig]:
        """🔄 Switch the active model."""
        models = self.load()

        if not any(m.name == name for m in models):
            raise ValueError(f"Unknown model: {name}")

        models = [
            ModelConfig(
                **{
                    **asdict(m),
                    "is_active": m.name == name,
                }
            )
            for m in models
        ]

        self.save(models)
        return models

    def active(self) -> ModelConfig:
        """✅ Get the currently active model."""
        models = self.load()
        return next(m for m in models if m.is_active)
