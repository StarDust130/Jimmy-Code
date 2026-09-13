"""Application configuration for Jimmy V1."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings kept small for V1."""

    groq_api_key: str | None = None
    jimmy_model: str = "groq/openai/gpt-oss-120b"
    jimmy_stream: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    """Load the current Jimmy settings."""

    return Settings()
