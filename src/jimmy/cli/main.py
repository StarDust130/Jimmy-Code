import typer

from jimmy.config.settings import Settings
from jimmy.llm.groq import GroqProvider

app = typer.Typer()


@app.command()
def run(task: list[str]) -> None:
    """Run Jimmy on a coding task."""
    settings = Settings() # type: ignore

    llm = GroqProvider(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
    )

    prompt = " ".join(task)

    response = llm.chat(prompt)

    typer.echo(f"\n🤖 Jimmy:\n{response.content}")


if __name__ == "__main__":
    app()
