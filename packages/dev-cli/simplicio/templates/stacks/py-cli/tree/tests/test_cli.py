from typer.testing import CliRunner

from app.cli import app


def test_hello() -> None:
    result = CliRunner().invoke(app, ["hello", "--name", "Simplicio"])

    assert result.exit_code == 0
    assert "hello Simplicio" in result.output
