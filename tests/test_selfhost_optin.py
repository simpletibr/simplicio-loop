"""The repo's own `.simplicio-loop/loop.toml` (self-host opt-in, #1589): present, tracked, minimal and safe.

The 24/7 watcher reads this file from the default branch (`intake_gate.repo_config`). Only `enabled` and `verify`
are allowed here: a file that widens who may start work (`allowed_authors`) or that points `verify` at the whole
suite must fail, so a later edit cannot loosen the gate without a test change.
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOOP_TOML = REPO / ".simplicio-loop" / "loop.toml"
OLD_TOML = REPO / ".simplicio" / "loop.toml"  # the Runtime's namespace: the loop keeps nothing there
# Tracked under `.simplicio-loop/` (ignored but for exact exceptions): the config, and the savings snapshots the ignore file names.
TRACKED_UNDER_STATE_DIR = {".simplicio-loop/loop.toml", ".simplicio-loop/orchestrator/savings/snapshots.jsonl"}
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


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def _ignored(path: str, tmp_path: Path) -> bool:
    """Does the repo's own .gitignore ignore `path`? Evaluated in a scratch repo, so a developer's `.git/info/exclude` (this
    checkout excludes `.simplicio-loop/` locally) or global ignore file cannot hide a broken rule."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True, env=env)
    (tmp_path / ".gitignore").write_text((REPO / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
    probe = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=tmp_path, capture_output=True, env=env)
    return probe.returncode == 0


def test_the_file_exists_and_is_tracked(tmp_path):
    assert LOOP_TOML.is_file(), ".simplicio-loop/loop.toml is missing"
    assert not _ignored(".simplicio-loop/loop.toml", tmp_path), \
        ".simplicio-loop/ is ignored: keep the exact exception `!.simplicio-loop/loop.toml` in .gitignore"
    if (REPO / ".git").exists():
        assert _git("ls-files", "--error-unmatch", ".simplicio-loop/loop.toml").returncode == 0, "loop.toml is not tracked"


@pytest.mark.parametrize("name", [".simplicio-loop/state.json", ".simplicio-loop/orchestrator/runs/x/events.jsonl",
                                  ".simplicio-loop/other.toml", ".simplicio-loop/loop.toml.bak"])
def test_nothing_else_under_the_state_dir_is_unignored(name, tmp_path):
    assert _ignored(name, tmp_path), f"{name} must stay ignored: only loop.toml is an exception"


def test_nothing_else_under_the_state_dir_is_tracked():
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = set(_git("ls-files", ".simplicio-loop").stdout.split())
    assert tracked <= TRACKED_UNDER_STATE_DIR, f"tracked state files: {sorted(tracked - TRACKED_UNDER_STATE_DIR)}"


def test_the_old_path_is_gone_and_nothing_reads_it():
    assert not OLD_TOML.exists(), ".simplicio/ belongs to the Runtime: the loop keeps no file there"
    if (REPO / ".git").exists():
        assert _git("ls-files", ".simplicio").stdout.strip() == ""


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
