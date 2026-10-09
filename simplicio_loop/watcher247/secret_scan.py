"""Secret scan of the staged diff before the watcher commits and pushes (#1434).

The detection patterns are the loop's own (hooks/action_gate.py, shipped in the wheel under
_bundle/hooks); this module only splits the diff per file so the comment can name the file.
The matched text is never returned, logged or put in an error.
"""
from __future__ import annotations

import importlib.util
import re
from functools import cache
from pathlib import Path

from . import proc

_GATE = Path(__file__).resolve().parents[1] / "_bundle" / "hooks" / "action_gate.py"
_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)


class SecretDetected(RuntimeError):
    reason_code = "secret_detected"

    def __init__(self, files: list[str]) -> None:
        self.files = files
        super().__init__("secret detected in: " + ", ".join(files))


@cache
def _scan_text():
    spec = importlib.util.spec_from_file_location("_loop_action_gate", _GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.scan_secret_text


def scan_diff(diff: str) -> list[str]:
    """Paths whose added lines carry a secret, in diff order."""
    scan = _scan_text()
    marks = list(_FILE.finditer(diff))
    found: list[str] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(diff)
        if scan(diff[mark.start():end]):
            found.append(mark.group(2))
    return found


async def check_staged(dest: Path) -> None:
    """Raise SecretDetected when the staged diff holds a secret; an unreadable diff blocks too."""
    result = await proc.run(["git", "diff", "--cached", "--unified=0"], cwd=dest)
    if result.returncode != 0:
        raise RuntimeError("cannot read the staged diff to scan it for secrets")
    if files := scan_diff(result.stdout):
        raise SecretDetected(files)
