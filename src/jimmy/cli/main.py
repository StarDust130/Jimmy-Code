from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from jimmy.agent.main_loop.agent_loop import AgentLoop
from jimmy.cli.tui.app import run_tui
from jimmy.config.settings import Settings
from jimmy.git.state import GitState
from jimmy.llm.gemini import GeminiProvider
from jimmy.permissions.manager import PermissionManager
from jimmy.tools.defaults import create_default_registry

__version__ = version("jimmy")

console = Console()

app = typer.Typer(
    name="jimmy",
    help="Jimmy — a terminal-native coding agent.",
    no_args_is_help=False,
)

permission_manager = PermissionManager()  # Manages user permission prompts


@app.command()
def main(
    task: Annotated[
        list[str] | None,
        typer.Argument(
            help="Optional first task for Jimmy.",
        ),
    ] = None,
    show_time: Annotated[
        bool,
        typer.Option(
            "--show-time",
            help="Show timestamps in activity.",
        ),
    ] = False,
    version_flag: Annotated[
        bool,
        typer.Option(
            "--version",
            is_eager=True,
            help="Show Jimmy version.",
        ),
    ] = False,
) -> None:
    """Start Jimmy."""

    if version_flag:  # Check version flag 🏷️
        console.print(f"Jimmy {__version__}")
        raise typer.Exit(code=0)

    settings = Settings()  # pyright: ignore[reportCallIssue]  # Load user settings ⚙️

    project_root = Path.cwd().resolve()  # Get project root directory 📂

    # groq = GroqProvider(
    #     api_key=settings.groq_api_key,
    #     model=settings.groq_model,
    # )

    gemini = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )

    llm = gemini

    git_state = GitState(project_root)

    tools = create_default_registry(
        root=project_root,
        llm=llm,
        git_state=git_state,
    )

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=project_root,
        git_state=git_state,
        max_turns=20,
        permission_manager=permission_manager,
    )

    initial_task = None

    if task:
        initial_task = " ".join(task).strip()

    try:
        run_tui(
            agent=agent,
            initial_task=initial_task,
            version=__version__,
            workspace=project_root,
            show_time=show_time,
            permission_manager=permission_manager,
        )

    except KeyboardInterrupt:
        console.print("\nInterrupted.")
        raise typer.Exit(code=130)

    except RuntimeError as exc:
        console.print(
            f"error: {exc}",
            style="bold red",
        )
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
