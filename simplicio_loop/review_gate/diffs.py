"""Read a PR diff: which files changed, which lines were added, and what kind of file each one is."""
from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DOC_SUFFIXES = (".md", ".rst", ".txt", ".toon")
_SYMLINK_MODE = re.compile(r"^(?:new file mode|deleted file mode|old mode|new mode) 120000$|^index [0-9a-f.]+ 120000$")


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # A added, M modified, D deleted
    added: tuple[int, ...]  # line numbers (in the new file) of the added lines
    removed: int = 0
    symlink: bool = False  # mode 120000 on either side: its content is a link target, never read

    @property
    def kind(self) -> str:
        return kind_of(self.path)


# Scripts and compiled languages: a file of these under `docs/` is still behavior, not documentation.
EXECUTABLE_SUFFIXES = frozenset(".sh .bash .zsh .ps1 .bat .cmd .js .jsx .mjs .cjs .ts .tsx .go .rs .rb .php .java .kt .cs .c .cc .cpp .h .hpp".split())


def is_requirements_file(path: str) -> bool:
    """`requirements.txt`, `requirements-dev.txt`, ... at any depth: a `.txt` that the installer reads, not documentation."""
    name = PurePosixPath(path).name.lower()
    return name.startswith("requirements") and name.endswith(".txt")


def kind_of(path: str) -> str:
    """`test`, `docs`, `code` (python outside the tests) or `other`."""
    p = PurePosixPath(path)
    if p.suffix == ".py" and (p.parts[0] == "tests" or p.name.startswith("test_") or p.name.endswith("_test.py")
                              or p.name == "conftest.py"):
        return "test"
    if is_requirements_file(path):
        return "other"
    # under `docs/` only what is not executable is documentation (text, diagrams, images, JSON of a flow): `docs/run.sh` is not
    if p.suffix in _DOC_SUFFIXES or (p.parts[0] == "docs" and p.suffix.lower() not in EXECUTABLE_SUFFIXES):
        return "docs"
    return "code" if p.suffix == ".py" else "other"


PYTEST_CONFIG_NAMES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "pyproject.toml", "tox.ini", "setup.cfg")  # the order pytest reads them
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


def is_test_helper(path: str) -> bool:
    """A shared module under `tests/` that is not a test file (fixtures, builders): it has no test function of its own, so the
    tests that import it are what proves a change to it."""
    p = PurePosixPath(path.replace("\\", "/"))
    return (p.parts[:1] == ("tests",) and p.suffix == ".py" and not p.name.startswith("test_") and not p.name.endswith("_test.py")
            and p.name != "__init__.py" and not is_pytest_infra(path))


def parse_diff(text: str) -> list[FileChange]:
    """Parse `git diff --unified=0 --no-renames` output."""
    files: list[dict] = []
    current: dict | None = None
    line_no = 0
    for raw in text.splitlines():
        if current is not None and _SYMLINK_MODE.match(raw):
            current["symlink"] = True
        if raw.startswith("diff --git "):
            current = {"path": "", "status": "M", "added": [], "removed": 0, "symlink": False}
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
    return [FileChange(f["path"], f["status"], tuple(f["added"]), f["removed"], f["symlink"]) for f in files if f["path"]]


def changed_files(repo: Path, base: str, head: str, timeout: float = 60) -> list[FileChange]:
    """The files `head` changes against `base` (a merge-base diff, so main moving on is not counted)."""
    done = subprocess.run(["git", "diff", "--unified=0", "--no-renames", "--no-color", f"{base}...{head}"], cwd=repo,
                          capture_output=True, text=True, timeout=timeout, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git diff {base}...{head} failed: {done.stderr.strip()[-200:]}")
    return parse_diff(done.stdout)
