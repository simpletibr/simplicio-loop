"""Deterministic detection of the target repo's test command, passed to turbo as --verify."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

PYTEST = "python3 -m pytest -q"
NPM = "npm test --silent"
CARGO = "cargo test"
MAKE = "make test"

_NPM_PLACEHOLDER = "no test specified"  # npm init's default `test` script is not a test suite
_MAKE_TEST_TARGET = re.compile(r"^test\s*:", re.MULTILINE)
_SKIPPED_DIRS = {"node_modules", "site-packages", "venv", "build", "dist"}  # vendored or generated, never the repo's tests


def _has_python_tests(dest: Path) -> bool:
    """pytest exits 5 when it collects nothing, so a pytest config alone is not a test suite."""
    for _root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIPPED_DIRS]
        if any((f.startswith("test_") and f.endswith(".py")) or f.endswith("_test.py") for f in files):
            return True
    return False


def _has_pytest_config(dest: Path) -> bool:
    if (dest / "pyproject.toml").is_file() or (dest / "pytest.ini").is_file():
        return True
    for name, marker in (("setup.cfg", "[tool:pytest]"), ("tox.ini", "[pytest]")):
        path = dest / name
        if path.is_file() and marker in path.read_text(errors="replace"):
            return True
    return False


def _npm_test_script(dest: Path) -> str | None:
    package = dest / "package.json"
    if not package.is_file():
        return None
    try:
        scripts = json.loads(package.read_text(errors="replace")).get("scripts")
    except (ValueError, AttributeError):
        return None
    test = scripts.get("test") if isinstance(scripts, dict) else None
    if not isinstance(test, str) or not test.strip() or _NPM_PLACEHOLDER in test:
        return None
    return test


def _detect(dest: Path) -> str | None:
    if _has_pytest_config(dest) and _has_python_tests(dest):
        return PYTEST
    if _npm_test_script(dest) is not None:
        return NPM
    if (dest / "Cargo.toml").is_file():
        return CARGO
    makefile = dest / "Makefile"
    if makefile.is_file() and _MAKE_TEST_TARGET.search(makefile.read_text(errors="replace")):
        return MAKE
    return None


async def detect(dest: Path) -> str | None:
    """The test command of the repo checked out at dest, or None when none is detectable."""
    return await asyncio.to_thread(_detect, dest)
