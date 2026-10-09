"""The repo's own `.simplicio/loop.toml` (self-host opt-in, #1589): present, tracked, minimal and safe.

The 24/7 watcher reads this file from the default branch (`intake_gate.repo_config`). Only `enabled` and `verify`
are allowed here: a file that widens who may start work (`allowed_authors`) or that points `verify` at the whole
suite must fail, so a later edit cannot loosen the gate without a test change.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOOP_TOML = REPO / ".simplicio" / "loop.toml"
ALLOWED_KEYS = {"enabled", "verify"}
FULL_SUITE = {"python3 -m pytest", "python3 -m pytest -q", "pytest", "pytest -q"}


def problems(table: dict) -> list[str]:
    """Why `table` is not an acceptable self-host opt-in; empty when it is."""
    found = []
    if table.get("enabled") is not True:  # intake_gate.repo_opted_in needs the literal true
        found.append("enabled must be the literal true")
    if extra := sorted(set(table) - ALLOWED_KEYS):
        found.append(f"keys beyond enabled/verify: {extra}")
    verify = table.get("verify")
    if not isinstance(verify, str) or not verify.strip():
        found.append("verify must be a non-empty command")
    elif verify.strip() in FULL_SUITE or "--full" in verify:
        found.append("verify must be a targeted gate, not the whole suite")
    return found


def test_the_file_exists_and_is_tracked():
    assert LOOP_TOML.is_file(), ".simplicio/loop.toml is missing"
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".simplicio/loop.toml"], cwd=REPO,
                             capture_output=True, text=True)
    assert tracked.returncode == 0, ".simplicio/ is in .gitignore: add the file with `git add -f`"


def test_the_file_is_a_minimal_safe_opt_in():
    assert problems(tomllib.loads(LOOP_TOML.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("table", [
    {},
    {"enabled": False, "verify": "python3 scripts/check.py"},
    {"enabled": "true", "verify": "python3 scripts/check.py"},
    {"enabled": True},
    {"enabled": True, "verify": "   "},
    {"enabled": True, "verify": "python3 -m pytest -q"},
    {"enabled": True, "verify": "python3 scripts/check.py --full"},
    {"enabled": True, "verify": "python3 scripts/check.py", "allowed_authors": ["someone"]},
    {"enabled": True, "verify": "python3 scripts/check.py", "auto_merge": True},
], ids=["empty", "disabled", "string-enabled", "no-verify", "blank-verify", "whole-suite", "full-flag",
        "widened-authors", "extra-key"])
def test_the_validator_rejects_a_loosened_file(table):
    assert problems(table), f"{table} should be rejected"
