"""Jimmy CLI entry point."""

from __future__ import annotations

import typer

from jimmy.config import get_settings
from jimmy.llm.model_config import ModelStore
from jimmy.llm.provider_factory import MissingAPIKeyError, create_provider
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

    # 2️⃣ Make sure the default (Gemini) key exists for first boot
    if not settings.gemini_api_key:
        typer.echo("❌ Missing GEMINI_API_KEY.\nAdd it to your .env file and run Jimmy again.")
        raise typer.Exit(code=2)

    # 3️⃣ 🤖 Load the user's saved model config
    #    (falls back to Gemini default if no ~/.jimmy/models.json)
    store = ModelStore()

    # 🗝️ seed the active model's key into the environment if
    #    it's the default and not already set (from settings)
    import os

    active = store.active()

    if active.api_key_env == "GEMINI_API_KEY" and not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    # 4️⃣ 🏭 Build the provider for the active model
    try:
        provider = create_provider(active)
    except MissingAPIKeyError as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(code=2)

    # 5️⃣ Start the terminal UI
    JimmyApp(
        provider=provider,
        initial_prompt=prompt,
    ).run()
