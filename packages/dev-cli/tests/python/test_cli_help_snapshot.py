"""Snapshot test: `simplicio-py --help` and every subcommand's `--help`
output must stay byte-identical across the cli.py refactor (issue #103).

Fixtures under `tests/python/fixtures/cli_help/*.txt` were captured from the
CLI *before* extracting subcommand handlers into `simplicio/commands/*.py`,
so this test is the regression gate proving the refactor didn't change any
user-visible flag, help text, or argparse structure. `argparse` writes
`--help` output to stdout and calls `sys.exit(0)`, so each subprocess-free
invocation is captured via `capsys` + `SystemExit`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "cli_help"

TOP_LEVEL_SUBCOMMANDS = [
    "index",
    "task",
    "proposal",
    "run",
    "bench",
    "cache",
    "smoke",
    "init",
    "detect",
    "status",
    "claims",
    "inspect",
    "intake",
    "doctor",
    "fast",
    "versions",
    "release-train",
    "env-export",
    "mechanical-edit",
    "changeset",
    "edit",
    "file",
    "test",
    "token",
    "score-skill",
    "runtime",
    "memory",
    "capabilities",
]

# Commands routed through `_dispatch_nested` before the main argparse parser
# even runs (gate/nest/scratch/skill) — each has its own argv[0]-based
# dispatch and its own --help wiring.
NESTED_SUBCOMMANDS = ["gate", "nest", "scratch", "skill"]


def _run_help(args: list[str]) -> str:
    """Invoke the real `simplicio-py` console-script entrypoint as a
    subprocess so argparse's SystemExit(0) and the exact stdout stream are
    captured without any in-process state (module-level caches, the
    ecosystem freshness sentinel, etc.) leaking between fixtures.

    `COLUMNS` is pinned to argparse's own non-tty fallback width (80):
    without pinning it, this byte-identical snapshot test's outcome depends
    on the ambient terminal width of whatever shell/CI runner happens to
    invoke pytest (argparse's `HelpFormatter` reads
    `COLUMNS`/`shutil.get_terminal_size`), which a snapshot test may not
    depend on. Fixtures under `fixtures/cli_help/*.txt` are captured at this
    same pinned width."""
    env = dict(os.environ)
    env["COLUMNS"] = "80"
    result = subprocess.run(
        [sys.executable, "-m", "simplicio.cli", *args, "--help"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    return result.stdout + result.stderr


def _fixture_names() -> list[str]:
    return sorted(p.stem for p in FIXTURES.glob("*.txt"))


@pytest.mark.parametrize("name", _fixture_names())
def test_help_output_matches_fixture(name):
    expected = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    args = [] if name == "_top" else [name]
    actual = _run_help(args)
    assert actual == expected


def test_fixtures_cover_every_documented_subcommand():
    names = set(_fixture_names())
    assert "_top" in names
    for cmd in TOP_LEVEL_SUBCOMMANDS + NESTED_SUBCOMMANDS:
        assert cmd in names, f"missing --help fixture for {cmd!r}"
