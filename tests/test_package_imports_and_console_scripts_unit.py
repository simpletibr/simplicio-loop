"""Safety net for pruning: every module still imports and every console script still starts.

A module deleted while something still imports it, or a console script whose target is gone, fails here
in seconds instead of on a user's machine.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import simplicio_loop

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]


def test_every_simplicio_loop_module_imports():
    failures = []
    for module in pkgutil.walk_packages(simplicio_loop.__path__, "simplicio_loop."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001 - report every broken module, not just the first
            failures.append(f"{module.name}: {type(exc).__name__}: {exc}")
    assert not failures, failures


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_console_script_target_exists_and_answers_help(name):
    module, function = re.fullmatch(r"([\w.]+):(\w+)", SCRIPTS[name]).groups()
    code = (f"import sys; from {module} import {function} as entry; sys.argv = [{name!r}, '--help']; "
            "sys.exit(entry())")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, (name, proc.stdout[-300:], proc.stderr[-600:])
