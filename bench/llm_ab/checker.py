"""Thin subprocess wrapper around the harness-owned
``fixture/tests/check_cadastro.py`` acceptance checker, shared by every arm.

The benchmarked model never writes or sees this checker; it ships with the
fixture repo (copied verbatim into each arm's working copy) before any arm
runs, and this module is how the harness itself (not the loop) confirms
task success and times the check.
"""
from __future__ import annotations

import os

import measure


def run_check(repo: str, stage: int, python: str, checker: str = "check_cadastro.py", timeout: int = 30):
    """Run ``<checker> --stage <stage>`` in ``repo`` (default
    ``check_cadastro.py``; login.html tasks pass ``checker="check_login.py"``).

    Returns ``(passed, output, metrics)`` where ``metrics`` is the
    ``measure.run_subprocess`` dict (wall/cpu/peak_rss/returncode).
    """
    script = checker if os.path.isabs(checker) else f"tests/{checker}"  # hidden checkers live outside the repo
    cmd = [python, script, "--stage", str(stage)]
    out, metrics = measure.run_subprocess(cmd, cwd=repo, timeout=timeout)
    passed = metrics["returncode"] == 0
    return passed, out, metrics


def verifier_line(stage: int, checker: str = "check_cadastro.py") -> str:
    """The verifier command exactly as declared in a task's markdown file."""
    return f"python3 tests/{checker} --stage {stage}"


def seed_repo(fixture_dir: str, dest_dir: str) -> None:
    """Copy the fixture repo (README.md, cadastro.html placeholder,
    tests/check_cadastro.py) into ``dest_dir``, creating it if needed."""
    import shutil

    if os.path.isdir(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.copytree(fixture_dir, dest_dir)
