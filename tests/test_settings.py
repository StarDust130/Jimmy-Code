from jimmy.config import Settings


def test_default_model() -> None:
    settings = Settings()
    assert settings.jimmy_model == "groq/openai/gpt-oss-120b"
