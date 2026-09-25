import typer
from rich.console import Console


app = typer.Typer()
console = Console()


@app.command()
def hello(name: str = "world") -> None:
    console.print(f"hello {name}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
