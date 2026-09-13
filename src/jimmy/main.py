"""Jimmy CLI entry point."""

from __future__ import annotations

import typer

from jimmy.config import get_settings
from jimmy.llm.litellm_provider import LiteLLMProvider
from tui.app import JimmyApp

app = typer.Typer(add_completion=False, help="Jimmy — terminal-native coding assistant")


@app.callback(invoke_without_command=True)
def main(prompt: str | None = typer.Argument(None, help="Optional first message to Jimmy")) -> None:
    """Start Jimmy."""

    settings = get_settings()
    if not settings.groq_api_key:
        typer.echo("Missing GROQ_API_KEY. Put it in .env and run Jimmy again.")
        raise typer.Exit(code=2)

    provider = LiteLLMProvider(model=settings.jimmy_model, api_key=settings.groq_api_key)
    JimmyApp(provider=provider, initial_prompt=prompt).run()
