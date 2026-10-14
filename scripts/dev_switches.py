"""Dev-only switches that must not ship (release blockers): find them in the shipped package."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

# Dev-only switches: a release must not carry them. The first one skips the watcher's login gate for the self-host
# phase (issue "Release blocker: remove the dev login switch and enforce login", docs/RELEASE.md "Release blockers").
DEV_SWITCHES = ("SIMPLICIO_247_NO_LOGIN",)


def find_dev_switches(repo: Path) -> Dict[str, list]:
    """{switch: [repo-relative files under simplicio_loop/ that still contain it]}, only the switches found.

    Bytecode caches are skipped: a stale .pyc is not source. Everything outside simplicio_loop/ (tests, scripts, docs)
    may name the switch; the package that ships is what must not.
    """
    root = Path(repo) / "simplicio_loop"
    found: Dict[str, list] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        for switch in DEV_SWITCHES:
            if switch.encode() in data:
                found.setdefault(switch, []).append(path.relative_to(repo).as_posix())
    return found
