"""Default --help advertises only the five public agent verbs."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from simplicio_mapper.cli import main
from simplicio_mapper.cli._shared import HELP_TEXT, PUBLIC_COMMANDS


def _invoke_help(argv: list[str]) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        try:
            code = main(argv)
        except SystemExit as error:
            code = int(error.code or 0)
    return code, output.getvalue()


def test_public_commands_are_the_five_agent_verbs() -> None:
    assert PUBLIC_COMMANDS == frozenset({"scan", "inspect", "handoff", "ask", "sync"})


def test_default_help_lists_only_public_verbs() -> None:
    code, output = _invoke_help(["--help"])
    assert code == 0
    assert output == HELP_TEXT or HELP_TEXT in output
    for name in PUBLIC_COMMANDS:
        assert name in output
    for hidden in (
        "release-governance",
        "ecc doctor",
        "visualize",
        "fleet",
        "business",
        "canonical gc",
    ):
        assert hidden not in output
        assert hidden not in HELP_TEXT


def test_internal_release_governance_still_dispatches() -> None:
    code, output = _invoke_help(["release-governance", "--help"])
    assert code == 0
    assert "usage:" in output.lower() or "parity" in output.lower()
