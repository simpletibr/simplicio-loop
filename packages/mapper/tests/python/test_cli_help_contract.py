"""Public command help must be discoverable at every routed CLI level."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from simplicio_mapper.cli import main


def _invoke_help(argv: list[str]) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        try:
            code = main(argv)
        except SystemExit as error:
            code = int(error.code)
    return code, output.getvalue()


def test_routed_commands_explain_themselves_with_help() -> None:
    cases = [
        ["contract", "--help"],
        ["contract", "validate", "--help"],
        ["contracts", "--help"],
        ["contracts", "validate", "--help"],
        ["doctor", "--help"],
        ["benchmark", "--help"],
        ["benchmark", "pipeline-threshold", "--help"],
        ["background", "--help"],
        ["mapper-store", "--help"],
        ["mapper-store", "plan", "--help"],
        ["store-migrations", "--help"],
        ["prototype-context", "--help"],
    ]
    for argv in cases:
        code, output = _invoke_help(argv)
        assert code == 0, (argv, output)
        assert "usage:" in output.lower(), (argv, output)
