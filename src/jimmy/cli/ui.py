import threading
import time

import typer
from rich.console import Console
from rich.live import Live
from rich.text import Text

console = Console()


def run_with_loading(agent, prompt: str) -> str:
    """Run Jimmy with a live terminal loading indicator."""

    result = ""
    error: Exception | None = None

    def run_agent():
        nonlocal result, error

        try:
            result = agent.run(prompt)
        except RuntimeError as exc:
            error = exc

    thread = threading.Thread(target=run_agent)
    thread.start()

    start = time.time()

    with Live(console=console, refresh_per_second=10) as live:
        while thread.is_alive():
            elapsed = time.time() - start

            live.update(
                Text.assemble(
                    ("⠋ ", "cyan"),
                    ("Jimmy is thinking ", "bold cyan"),
                    (f"{elapsed:.1f}s", "dim"),
                )
            )

            time.sleep(0.1)

    thread.join()

    if error is not None:
        typer.echo(f"\n🛑 {error}", err=True)
        raise typer.Exit(code=1)

    return result


def show_result(result: str):
    """Display Jimmy's final response."""
    console.print()
    console.print("[bold cyan]🤖 Jimmy[/bold cyan]")
    console.print(result)
    console.print()
