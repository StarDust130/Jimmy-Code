import typer

app = typer.Typer()


@app.command()
def main(task: list[str]):
    prompt = " ".join(task)
    print(f"🤖 Jimmy received: {prompt}")


if __name__ == "__main__":
    app()
