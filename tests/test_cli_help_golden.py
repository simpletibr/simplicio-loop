"""Golden snapshot of the whole CLI surface: the `--help` text of every command (#1818).

The cli_impl.py split into per-command-group modules must not change one byte of what a user sees.
This test renders `--help` for the top level, every command path of the parser tree and the commands that
parse their own argv, and compares the result with tests/golden/cli_help.txt (generated from main before the split).

An intentional CLI change regenerates the file:
    UPDATE_CLI_HELP_GOLDEN=1 python3 -m pytest -q tests/test_cli_help_golden.py
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import os
import re
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden" / "cli_help.txt"
# Commands dispatched before the cli_impl parser is built: each parses its own argv, so its --help is part of the surface.
PRE_DISPATCHED = ("tasks", "intake", "handoff", "author", "run", "daemon")


def _command_paths(monkeypatch) -> list[str]:
    """Every command path of the cli_impl parser tree, aliases included, read from the parser main() builds."""
    from simplicio_loop import cli_impl

    captured: dict = {}

    class _Stop(Exception):
        pass

    def _capture(self, *args, **kwargs):
        captured.setdefault("root", self)
        raise _Stop()

    with monkeypatch.context() as patch:  # the capture is for this walk only; the renders below parse for real
        patch.setattr(argparse.ArgumentParser, "parse_args", _capture)
        try:
            cli_impl.main(["--help"])
        except _Stop:
            pass
    assert "root" in captured, "main() no longer builds the parser before parsing"

    paths: set[str] = set()
    seen: set[int] = set()

    def walk(parser: argparse.ArgumentParser, prefix: list[str]) -> None:
        if id(parser) in seen:
            return
        seen.add(id(parser))
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    paths.add(" ".join([*prefix, name]))
                    walk(sub, [*prefix, name])

    walk(captured["root"], [])
    return sorted(paths)


def _render(monkeypatch) -> dict[str, str]:
    from simplicio_loop import cli_impl

    monkeypatch.setenv("COLUMNS", "100")  # argparse wraps to the terminal width; pin it
    labels = ["(top level)", *_command_paths(monkeypatch), *PRE_DISPATCHED, "(version)"]
    blocks: dict[str, str] = {}
    for label in labels:
        if label == "(top level)":
            argv = ["--help"]
        elif label == "(version)":
            argv = ["--version"]
        else:
            argv = [*label.split(), "--help"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli_impl.main(argv)
            except SystemExit as exc:
                code = exc.code
        blocks[label] = f"=== {label} rc={code}\n{out.getvalue()}{err.getvalue()}"
    return blocks


_PER_OPTION_METAVAR = re.compile(r"(--?[\w-]+) (\S+), (--?[\w-]+) \2(?=[\s,])")
_USAGE = re.compile(r"^usage: .*?\n\n", re.MULTILINE | re.DOTALL)


def _comparable(block: str) -> str:
    """What the golden compares for one block. argparse changed two layouts between CPython releases: it wraps a
    usage line at other words, and 3.11 and 3.12 repeat the metavar after every alias of an option. Both are folded
    to the 3.13 layout the golden records. The usage is compared word for word, every other line byte for byte."""
    previous = None
    while previous != block:
        previous, block = block, _PER_OPTION_METAVAR.sub(r"\1, \3 \2", block)
    return _USAGE.sub(lambda m: " ".join(m.group(0).split()) + "\n\n", block, count=1)


def _parse_golden(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    label = None
    for line in text.splitlines(keepends=True):
        if line.startswith("=== "):
            label = line[4:].rsplit(" rc=", 1)[0].rstrip("\n")
            blocks[label] = line
        elif label is not None:
            blocks[label] += line
    return blocks


def test_every_command_help_matches_the_golden_snapshot(monkeypatch):
    rendered = _render(monkeypatch)
    if os.environ.get("UPDATE_CLI_HELP_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text("".join(rendered[label] for label in rendered), encoding="utf-8")
    golden = _parse_golden(GOLDEN.read_text(encoding="utf-8"))

    missing = sorted(set(golden) - set(rendered))
    added = sorted(set(rendered) - set(golden))
    changed = sorted(label for label in set(golden) & set(rendered)
                     if _comparable(golden[label]) != _comparable(rendered[label]))
    if not (missing or added or changed):
        return
    details = []
    for label in changed[:5]:
        diff = difflib.unified_diff(golden[label].splitlines(), rendered[label].splitlines(),
                                    "golden", "current", lineterm="", n=1)
        details.append("\n".join(list(diff)[:30]))
    pytest_message = (
        f"CLI help drifted from tests/golden/cli_help.txt. changed={changed} missing={missing} added={added}.\n"
        + "\n\n".join(details)
        + "\nIf the change is intentional, regenerate with UPDATE_CLI_HELP_GOLDEN=1."
    )
    raise AssertionError(pytest_message)


def test_dashboard_mode_flags_are_declared_side_by_side():
    # argparse 3.11-3.13 renders a mutually exclusive group only when its members are adjacent in declaration
    # order. An option declared between two members turns the group into plain optionals, and the usage then
    # hides the exclusion that argparse still enforces at parse time.
    from simplicio_loop.dashboard import cli as dashboard_cli

    parser = argparse.ArgumentParser(prog="simplicio-loop dashboard")
    dashboard_cli.add_arguments(parser)
    (group,) = parser._mutually_exclusive_groups
    positions = sorted(parser._actions.index(action) for action in group._group_actions)
    assert positions == list(range(positions[0], positions[0] + len(positions))), (
        f"dashboard mode flags are split by another option at positions {positions}")


def test_usage_comparison_ignores_wrapping_but_not_words():
    wrapped = """=== dashboard rc=0
usage: prog [-h] [--stop | --status |
    --tui] [--tokens]

help
"""
    flat = """=== dashboard rc=0
usage: prog [-h] [--stop | --status | --tui] [--tokens]

help
"""
    plain_group = """=== dashboard rc=0
usage: prog [-h] [--stop] [--status] [--tui] [--tokens]

help
"""
    assert _comparable(wrapped) == _comparable(flat)
    assert _comparable(flat) != _comparable(plain_group)
    assert _comparable(flat) != _comparable(flat.replace("--tokens", "--token"))
    assert _comparable(flat) != _comparable(flat.replace("help", "Help"))


def test_option_comparison_accepts_both_metavar_layouts_but_flags_a_renamed_alias():
    once = """=== drain rc=0
  --snapshot, --snapshot-file SNAPSHOT_PATH
"""
    per_option = """=== drain rc=0
  --snapshot SNAPSHOT_PATH, --snapshot-file SNAPSHOT_PATH
"""
    renamed_alias = """=== drain rc=0
  --snapshot, --snapshot-path SNAPSHOT_PATH
"""
    assert _comparable(per_option) == _comparable(once)
    assert _comparable(renamed_alias) != _comparable(once)
