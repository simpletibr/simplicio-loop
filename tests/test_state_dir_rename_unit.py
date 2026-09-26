"""Regression guard for issue #1311: `.simplicio/` must not reappear.

The loop stack (root loop + packages/mapper + packages/fast + packages/dev-cli)
uses `.simplicio-loop/` as its state directory; `.simplicio/` belongs to the
separate Simplicio Runtime/MCP product. This test fails closed if the old
directory name is reintroduced anywhere in the loop's own source.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (?<![\w.]) skips module-path uses like `x.simplicio`; (?![\w-]) skips
# `.simplicio-loop` and `.simplicio_foo` variants.
PATTERN = r"(?<![\w.])\.simplicio(?![\w-])"

SCOPE_DIRS = [
    "simplicio_loop",
    "scripts",
    "hooks",
]


def _grep(pattern: str, paths: list[str]) -> str:
    result = subprocess.run(
        ["git", "grep", "-nP", pattern, "--", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # git grep exit code 1 means "no matches" - that's the success case here.
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git grep failed: {result.stderr}")
    return result.stdout


def test_no_dot_simplicio_in_root_loop_scope():
    paths = [p for p in SCOPE_DIRS if (REPO_ROOT / p).exists()]
    output = _grep(PATTERN, paths)
    assert output == "", f"found stale '.simplicio' references:\n{output}"


def test_no_dot_simplicio_in_package_source():
    package_globs = [
        "packages/mapper/simplicio_mapper",
        "packages/dev-cli/simplicio",
        "packages/fast/src",
    ]
    paths = [p for p in package_globs if (REPO_ROOT / p).exists()]
    assert paths, "expected at least one package source dir to exist"
    output = _grep(PATTERN, paths)
    assert output == "", f"found stale '.simplicio' references:\n{output}"
