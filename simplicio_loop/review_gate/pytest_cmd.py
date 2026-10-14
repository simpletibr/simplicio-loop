"""The one way the gate starts pytest on a disposable tree.

An editable install (`pip install -e`) puts a finder on `sys.meta_path` that serves any module missing from the tree out
of ANOTHER checkout. Then a new test that imports a module only the PR adds would pass on main, and the gate would call it
vacuous. The command removes those finders before pytest imports anything, so the tree under test is the only source.
"""
from __future__ import annotations

_BOOT = (
    "import sys\n"
    "sys.meta_path[:] = [f for f in sys.meta_path if 'editable' not in (getattr(f, '__module__', '') + getattr(f, '__name__', '')).lower()]\n"
    "import pytest\n"
    "sys.exit(pytest.main(sys.argv[1:]))\n"
)


def command(python: str, *args: str) -> list[str]:
    return [python, "-c", _BOOT, *args]
