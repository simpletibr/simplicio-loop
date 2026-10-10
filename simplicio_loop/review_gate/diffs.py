"""Read a PR diff: which files changed, which lines were added, and what kind of file each one is."""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DOC_SUFFIXES = (".md", ".rst", ".txt", ".toon")


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # A added, M modified, D deleted
    added: tuple[int, ...]  # line numbers (in the new file) of the added lines
    removed: int = 0

    @property
    def kind(self) -> str:
        return kind_of(self.path)


def kind_of(path: str) -> str:
    """`test`, `docs`, `code` (python outside the tests) or `other`."""
    p = PurePosixPath(path)
    if p.suffix == ".py" and (p.parts[0] == "tests" or p.name.startswith("test_") or p.name.endswith("_test.py")
                              or p.name == "conftest.py"):
        return "test"
    if p.suffix in _DOC_SUFFIXES or p.parts[0] == "docs":
        return "docs"
    return "code" if p.suffix == ".py" else "other"


PYTEST_CONFIG_NAMES = ("pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")  # the order pytest reads them
_PYTEST_INFRA_NAMES = frozenset({"conftest.py", "pytest_plugins.py", "plugins.py", *PYTEST_CONFIG_NAMES})
_PYTEST_INFRA_DIRS = frozenset({"plugins", "pytest_plugins"})


def _fold(part: str) -> str:
    return unicodedata.normalize("NFKC", part).lower().rstrip(" .")  # what a forgiving file system reads


def is_pytest_infra(path: str) -> bool:
    """True for what changes how pytest itself behaves: any `conftest.py` (at any depth), the pytest configuration files and
    the plugin modules (`plugins.py`, `pytest_plugins.py`, anything under a `plugins/` or `pytest_plugins/` directory).
    Such a file runs inside the pytest that judges the PR, so the gate never takes the PR's version on trust."""
    parts = [_fold(p) for p in PurePosixPath(path.replace("\\", "/")).parts]
    if not parts:
        return False
    return parts[-1] in _PYTEST_INFRA_NAMES or (parts[-1].endswith(".py") and bool(_PYTEST_INFRA_DIRS.intersection(parts[:-1])))


def parse_diff(text: str) -> list[FileChange]:
    """Parse `git diff --unified=0 --no-renames` output."""
    files: list[dict] = []
    current: dict | None = None
    line_no = 0
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current = {"path": "", "status": "M", "added": [], "removed": 0}
            files.append(current)
        elif current is None:
            continue
        elif raw.startswith("new file mode"):
            current["status"] = "A"
        elif raw.startswith("deleted file mode"):
            current["status"] = "D"
        elif raw.startswith("+++ "):
            target = raw[4:].strip()
            if target != "/dev/null":
                current["path"] = target[2:] if target.startswith("b/") else target
        elif raw.startswith("--- "):
            source = raw[4:].strip()
            if source != "/dev/null" and not current["path"]:
                current["path"] = source[2:] if source.startswith("a/") else source
        elif (hunk := _HUNK.match(raw)):
            line_no = int(hunk.group(1))
        elif raw.startswith("+"):
            current["added"].append(line_no)
            line_no += 1
        elif raw.startswith("-"):
            current["removed"] += 1
    return [FileChange(f["path"], f["status"], tuple(f["added"]), f["removed"]) for f in files if f["path"]]


def changed_files(repo: Path, base: str, head: str, timeout: float = 60) -> list[FileChange]:
    """The files `head` changes against `base` (a merge-base diff, so main moving on is not counted)."""
    done = subprocess.run(["git", "diff", "--unified=0", "--no-renames", "--no-color", f"{base}...{head}"], cwd=repo,
                          capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git diff {base}...{head} failed: {done.stderr.strip()[-200:]}")
    return parse_diff(done.stdout)
