"""Regression guard for issue #1311: `.simplicio/` must not reappear.

The loop stack (root loop + packages/mapper + packages/fast + packages/dev-cli)
uses `.simplicio-loop/` as its state directory; `.simplicio/` belongs to the
separate Simplicio Runtime/MCP product. This test fails closed if the old
directory name is reintroduced anywhere in the loop's own source, except for the
explicit, narrow ALLOWLIST below (two deliberate external contracts).
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

PACKAGE_DIRS = [
    "packages/mapper/simplicio_mapper",
    "packages/dev-cli/simplicio",
    "packages/fast/src",
]

# The ONLY places a `.simplicio` reference is deliberate: contracts with things that
# live outside the loop stack. Each entry is (file, exact substring, justification).
# A grep hit is forgiven only when, after removing the allowed substring(s) of ITS
# file from the line, no `.simplicio` is left; any other reference, in any other
# file or on the same line, still fails. Do not widen this to a directory; do not
# add an entry for a loop state path (those are `.simplicio-loop/`).
ALLOWLIST = [
    (
        "simplicio_loop/auth.py",
        'RUNTIME_DIR = ".simplicio"',
        "home folder of the separate Simplicio Runtime product: its login file and its managed binary",
    ),
    (
        "simplicio_loop/auth.py",
        "~/.simplicio/login.json",
        "docstrings naming the Runtime login path shared with the 24/7 watcher and the login commands",
    ),
    (
        "simplicio_loop/auth.py",
        "~/.simplicio/bin",
        "docstring of the Runtime managed binary folder",
    ),
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


def _unallowed(output: str) -> str:
    """`git grep -n` lines that still hold a `.simplicio` once their file's allowed substrings are removed."""
    offenders = []
    for line in output.splitlines():
        path, _, rest = line.partition(":")
        content = rest.partition(":")[2]
        for allowed_path, token, _why in ALLOWLIST:
            if allowed_path == path:
                content = content.replace(token, "")
        if re.search(PATTERN, content):
            offenders.append(line)
    return "".join(f"{line}\n" for line in offenders)


def _offenders(paths: list[str]) -> str:
    return _unallowed(_grep(PATTERN, [p for p in paths if (REPO_ROOT / p).exists()]))


def test_no_dot_simplicio_in_root_loop_scope():
    output = _offenders(SCOPE_DIRS)
    assert output == "", f"found stale '.simplicio' references:\n{output}"


def test_no_dot_simplicio_in_package_source():
    assert any((REPO_ROOT / p).exists() for p in PACKAGE_DIRS), "expected at least one package source dir to exist"
    output = _offenders(PACKAGE_DIRS)
    assert output == "", f"found stale '.simplicio' references:\n{output}"


def test_allowlist_entries_are_live_and_narrow():
    # a contract that went away must leave the allowlist: every entry still matches a real line of its file
    for path, token, why in ALLOWLIST:
        assert why and token.count("simplicio") == 1 and (REPO_ROOT / path).is_file(), (path, token)
        assert token in (REPO_ROOT / path).read_text(encoding="utf-8"), f"stale allowlist entry: {path} {token}"


def test_allowlist_forgives_only_the_exact_token_of_its_own_file():
    auth = "simplicio_loop/auth.py:7:"
    assert _unallowed(f'{auth}RUNTIME_DIR = ".simplicio"\n') == ""
    # same file, another `.simplicio` path
    assert _unallowed(f"{auth}    # reads .simplicio/foo\n") != ""
    # allowed token and another `.simplicio` on one line
    assert _unallowed(f'{auth}RUNTIME_DIR = ".simplicio"; x = ".simplicio/foo"\n') != ""
    # the token is allowed only in its own file
    assert _unallowed('simplicio_loop/other.py:7:RUNTIME_DIR = ".simplicio"\n') != ""
    # the loop's own per-repo config lives in `.simplicio-loop/`; the old name gets no exception anywhere
    assert _unallowed("simplicio_loop/intake_gate.py:7:    # reads .simplicio/loop.toml\n") != ""
    assert _unallowed('simplicio_loop/watcher247/tick.py:7:    Path.home() / ".simplicio" / "login.json"\n') != ""
    # the auth module may name the Runtime folder only through its constant, not build a second path by hand
    assert _unallowed('simplicio_loop/auth.py:7:    Path.home() / ".simplicio" / "login.json"\n') != ""
