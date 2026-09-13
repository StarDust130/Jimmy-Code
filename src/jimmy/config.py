"""Application configuration for Jimmy."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"


class Settings(BaseSettings):
    """Environment-backed settings."""

    # 🤖 Default AI model
    model: str = DEFAULT_MODEL

    # 🔑 Gemini API key
    gemini_api_key: str | None = None

    # 📄 Load values from .env
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_model() -> str:
    # 🤖 Read custom model or use default
    return os.getenv("JIMMY_MODEL", DEFAULT_MODEL)


def get_api_key(model: str) -> str | None:
    # 🔑 Use Gemini key for Gemini models
    if model.startswith("gemini/"):
        return os.getenv("GEMINI_API_KEY")

    return None


def get_settings() -> Settings:
    # 📦 Load current settings
    return Settings()
