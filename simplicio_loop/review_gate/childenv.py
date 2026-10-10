"""Environment of the PR's code under the review gate (#1649): an allowlist, never the watcher's environment.

The gate runs tests and mutants of a PR it has not judged yet, so a token in the watcher's environment (GH_TOKEN, API keys)
or its real HOME (~/.config/gh, ~/.simplicio) must not reach that code. HOME points at the disposable tree.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

KEEP = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM", "VIRTUAL_ENV", "PYTHONPATH", "SYSTEMROOT")


def scrubbed(home: Path, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The allowlisted variables of this process, HOME=`home`, then `extra` (set by the gate itself, so trusted)."""
    env = {name: os.environ[name] for name in KEEP if name in os.environ}
    env["HOME"] = str(home)
    env.update(extra or {})
    return env
