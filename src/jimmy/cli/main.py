from pathlib import Path

import typer

from jimmy.agent.loop import AgentLoop
from jimmy.config.settings import Settings
from jimmy.llm.groq import GroqProvider
from jimmy.tools.defaults import create_default_registry

app = typer.Typer()


@app.command()
def run(task: str):
    """Run Jimmy on a coding task."""
    settings = Settings()  # pyright: ignore[reportCallIssue]

    llm = GroqProvider(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
    )

    project_root = Path.cwd()
    tools = create_default_registry(project_root)

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        max_turns=20,
    )

    result = agent.run(task)

    typer.echo(f"\n🤖 Jimmy:\n{result}")


if __name__ == "__main__":
    app()
