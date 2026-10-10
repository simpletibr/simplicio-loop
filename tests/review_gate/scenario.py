"""A throwaway git repo with a base commit and three kinds of head, for the tests of the gate, its CLI and the squad's `evaluate`."""
from __future__ import annotations

import subprocess
from pathlib import Path

BASE = {
    "mod.py": "def add(a, b):\n    return a + b\n",
    "app.py": "from mod import add\n\n\ndef total(a, b):\n    return add(a, b)\n",
    "tests/test_add.py": "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}
CLAMP = ("def add(a, b):\n    return a + b\n\n\ndef clamp(x, low, high):\n    if x < low:\n        return low\n"
         "    if x > high:\n        return high\n    return x\n")
HEADS = {
    # new behavior, used by app.py, and tests that fail on main (clamp does not exist there) and kill its mutants
    "good": {
        "mod.py": CLAMP,
        "app.py": BASE["app.py"] + "\n\ndef limited(x):\n    return clamp(x, 0, 10)\n".replace("clamp", "mod.clamp"),
        "tests/test_clamp.py": ("import mod\n\n\ndef test_clamp_low():\n    assert mod.clamp(-1, 0, 10) == 0\n\n\n"
                                "def test_clamp_high():\n    assert mod.clamp(11, 0, 10) == 10\n\n\n"
                                "def test_clamp_inside():\n    assert mod.clamp(5, 0, 10) == 5\n    assert mod.clamp(0, 0, 10) == 0\n    assert mod.clamp(10, 0, 10) == 10\n"),
    },
    # production changed, tests that pass on main as well
    "vacuous": {
        "mod.py": "def add(a, b):\n    if a is None:\n        return b\n    return a + b\n",
        "tests/test_add.py": BASE["tests/test_add.py"] + "\n\ndef test_add_again():\n    assert add(2, 2) == 4\n",
    },
    # a new module nobody calls, with tests that kill every mutant
    "dead": {
        "dead.py": "def double(x):\n    if x < 0:\n        return 0\n    return x * 2\n",
        "tests/test_dead.py": ("from dead import double\n\n\ndef test_double():\n    assert double(2) == 4\n    assert double(0) == 0\n"
                               "    assert double(-1) == 0\n    assert double(1) == 2\n"),
    },
}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")


def make_repo(root: Path, head: str) -> tuple[Path, str, str]:
    """(repo, base sha, head sha): `main` holds BASE, branch `loop/issue-7` holds HEADS[head]."""
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    _write(repo, BASE)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "loop/issue-7")
    _write(repo, HEADS[head])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", head)
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return repo, base, tip
