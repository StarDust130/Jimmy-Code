"""Jimmy CLI entry point."""

from __future__ import annotations

import typer

from jimmy.config import get_settings
from jimmy.llm.litellm_provider import LiteLLMProvider
from tui.app import JimmyApp

# 🚀 Create the Jimmy CLI
app = typer.Typer(
    add_completion=False,
    help="Jimmy — terminal-native coding assistant",
)


@app.callback(invoke_without_command=True)
def main(
    prompt: str | None = typer.Argument(
        None,
        help="Optional first message to Jimmy",
    ),
) -> None:
    """Start Jimmy."""

    # 1️⃣ Load Jimmy settings
    settings = get_settings()

    # 2️⃣ Make sure Gemini API key exists
    if not settings.gemini_api_key:
        typer.echo("❌ Missing GEMINI_API_KEY.\nAdd it to your .env file and run Jimmy again.")
        raise typer.Exit(code=2)

    # 3️⃣ Create the LLM provider
    provider = LiteLLMProvider(
        model=settings.model,
        api_key=settings.gemini_api_key,
    )

    # 4️⃣ Start the terminal UI
    JimmyApp(
        provider=provider,
        initial_prompt=prompt,
    ).run()
