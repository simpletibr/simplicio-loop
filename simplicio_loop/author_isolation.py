"""What the author flow trusts instead of git: a file system snapshot, and a private HOME for the CLI.

``snapshot`` maps every path of the worktree to a digest, so ``changed`` is what the files say, whatever git is told (a new
``.gitignore``, ``update-index --assume-unchanged`` and a ``.git`` file that points elsewhere hide nothing). It does not follow
symlinks (a link is its target text), and it records the mode. It skips ``__pycache__``, ``.pytest_cache`` and the ``.git``
folder, which git itself rewrites on every ``add`` and ``commit``; of ``.git`` it keeps ``config`` and ``hooks/``, the two places
that run a program on the host. A ``.git`` FILE (a linked worktree) is an ordinary entry: pointing it elsewhere is a change.

The CLI gets a private HOME under the real HOME (``.cache/simplicio-loop-author/<run>``) holding only a copy of the login. It is not
inside the worktree: the sandbox binds the whole worktree read-write for the verify command too, and the verify command runs the
author's code, so the login must be visible to the CLI alone. The sandbox binds this folder (``HomeView.rw``) for the CLI and
nothing else; the real HOME is an empty tmpfs for both.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import stat
from pathlib import Path

SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache"})
GIT_KEPT = (".git/config", ".git/hooks")
HOMES = Path(".cache") / "simplicio-loop-author"
LOGIN = Path(".claude") / ".credentials.json"
# What the CLI could load from its HOME and run, rebuilt away before every round (the login and the transcripts stay).
CLAUDE_CONFIG = ("settings.json", "settings.local.json", "CLAUDE.md", "hooks", "agents", "commands", "skills", "plugins")


class LoginMissing(Exception):
    """The real HOME has no login to copy: nothing runs."""


def _digest(path: str) -> str:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return "link:" + os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        return f"special:{stat.S_IFMT(info.st_mode):o}"
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                sha.update(chunk)
    except OSError as exc:
        return f"unreadable:{exc.errno}"
    return f"{stat.S_IMODE(info.st_mode):o}:{sha.hexdigest()}"


def _entries(root: str):
    """Absolute paths of the files and symlinks the snapshot covers."""
    unreadable: list[str] = []  # a folder the walk cannot list would hide what is in it: it is an entry of its own
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=lambda exc: unreadable.append(exc.filename)):
        git = folder == root and ".git" in dirs
        for name in files:
            yield os.path.join(folder, name)
        for name in dirs:
            if os.path.islink(os.path.join(folder, name)):  # walk lists a link to a folder as a folder and does not enter it
                yield os.path.join(folder, name)
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not (git and name == ".git")]
        if git:
            for kept in GIT_KEPT:
                path = os.path.join(root, kept)
                if os.path.isfile(path):
                    yield path
                elif os.path.isdir(path):
                    yield from (os.path.join(sub, name) for sub, _dirs, names in os.walk(path) for name in names)
    yield from unreadable


def snapshot(root: str | os.PathLike[str]) -> dict[str, str]:
    """``{relative posix path: digest}`` of the worktree."""
    base = os.fspath(root)
    return {os.path.relpath(path, base).replace(os.sep, "/"): _digest(path) for path in _entries(base)}


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths created, changed or deleted between two snapshots."""
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))


def make_home(real_home: Path, name: str) -> Path:
    """A private HOME (0700) with a 0600 copy of the login. ``LoginMissing`` when the real HOME has none."""
    source = real_home / LOGIN
    if not source.is_file():
        raise LoginMissing(f"{source} not found: log in to claude first")
    (real_home / HOMES).mkdir(parents=True, exist_ok=True, mode=0o700)
    home = real_home / HOMES / name
    try:
        home.mkdir(mode=0o700)
        (home / LOGIN.parent).mkdir(mode=0o700)
        fd = os.open(home / LOGIN, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(source.read_bytes())
    except BaseException:
        drop_home(real_home, home)
        raise
    return home


def drop_home(real_home: Path, home: Path) -> None:
    """Delete the private HOME, and the folder of the private HOMES when it is the last one."""
    shutil.rmtree(home, ignore_errors=True)
    with contextlib.suppress(OSError):
        (real_home / HOMES).rmdir()  # fails (and stays) while another run uses it


def reset_config(home: Path) -> None:
    """Remove what the author may have written in its HOME for the next round to load (settings, hooks, agents, skills, plugins)."""
    for name in CLAUDE_CONFIG:
        target = home / ".claude" / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                target.unlink()
