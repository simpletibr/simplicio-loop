"""What the author flow trusts instead of git: a file system snapshot, and a private HOME for the CLI.

``snapshot`` maps every path of the worktree to a digest, so ``changed`` is what the files say, whatever git is told (a new
``.gitignore``, ``update-index --assume-unchanged`` and a ``.git`` file that points elsewhere hide nothing). It does not follow
symlinks (a link is its target text), and it records the mode. Of ``.git`` it skips everything git rewrites on every ``add`` and
``commit`` and keeps ``config`` and ``hooks/``, the two places that run a program on the host. A ``.git`` FILE (a linked worktree)
is an ordinary entry: pointing it elsewhere is a change.

``__pycache__`` is in the snapshot and everything in it counts: python imports an UNCHECKED_HASH ``.pyc`` in place of its ``.py``
without reading the source, and the owner's pytest imports it outside the sandbox. The CLI and the verify command run with
``PYTHONDONTWRITEBYTECODE=1``, so any ``.pyc`` or ``.pyo`` that appears, changes or goes away is the author's (``bytecode_refusal``).
Only the ``.pytest_cache`` folder, which pytest writes on every run and nothing imports, is left out of ``changed``.

A file over ``BIG_FILE`` is not hashed (the author can make a sparse file of any size with the pytest it may run): it is recorded as
``big:<mode>:<size>:<mtime_ns>:<inode>``. A same-size rewrite of a big file that keeps its mtime and inode is not seen; no protected
path is that big. The whole snapshot has a time budget (``SnapshotTimeout``).

Inside ``.simplicio-loop/orchestrator/runs/`` (the host appends its telemetry there) a REGULAR file with one link is left out, and
nothing else: a symlink, a hard link, a fifo or a socket there is a change, because the host would append a line through it to
whatever it points at (``.git/config``).

``leaks`` is the other half of the login guard: the CLI cannot read its login file (``author_flow.deny_rules``), and any changed file
that still holds the bytes of the login file or of its tokens (``login_secrets``) fails the round. The bytes stay in memory.

The CLI gets a private HOME under the real HOME (``.cache/simplicio-loop-author/<run>``) holding only a copy of the login. It is not
inside the worktree: the sandbox binds the whole worktree read-write for the verify command too, and the verify command runs the
author's code, so the login must be visible to the CLI alone. The sandbox binds this folder (``HomeView.rw``) for the CLI and
nothing else; the real HOME is an empty tmpfs for both. A run that dies without cleaning (SIGKILL) leaves its HOME with a
``.owner`` file; the next run sweeps every HOME whose owner pid is gone.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import shutil
import signal
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path

NOISE_DIR = ".pytest_cache"
TELEMETRY_PARENT = (".simplicio-loop", "orchestrator")
TELEMETRY_DIR = "runs"  # <TELEMETRY_PARENT>/runs: what the host writes during a run (events.jsonl, the lease heartbeat every 60 s)
TOKEN_KEYS = ("accessToken", "refreshToken")  # the keys of the login file whose values are the credentials
MIN_SECRET = 8  # bytes; a shorter value would match innocent text
SCAN_CHUNK = 1 << 20
BYTECODE = (".pyc", ".pyo")
GIT_KEPT = (".git/config", ".git/hooks")
BIG_FILE = 64 << 20  # bytes; above this a file is recorded by size, mtime and inode
SNAPSHOT_BUDGET_S = 120.0
HOMES = Path(".cache") / "simplicio-loop-author"
HOME_BASE_ENV = "SIMPLICIO_247_AUTHOR_HOME_BASE"
LOGIN = Path(".claude") / ".credentials.json"
OWNER = ".owner"
UNOWNED_GRACE_S = 60  # a HOME with no readable owner file is stale only after this long (its owner may be writing the file)
# What the CLI could load from its HOME and run, rebuilt away before every round (the login and the transcripts stay).
CLAUDE_CONFIG = ("settings.json", "settings.local.json", "CLAUDE.md", "hooks", "agents", "commands", "skills", "plugins")
TERMINATION = tuple(getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name))


class LoginMissing(Exception):
    """The real HOME has no login to copy: nothing runs."""


class SnapshotTimeout(Exception):
    """The snapshot did not finish inside its time budget."""


def _digest(path: str, deadline: float) -> str:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        return "link:" + os.readlink(path)
    if not stat.S_ISREG(info.st_mode):
        return f"special:{stat.S_IFMT(info.st_mode):o}"
    mode = stat.S_IMODE(info.st_mode)
    if info.st_size > BIG_FILE:
        return f"big:{mode:o}:{info.st_size}:{info.st_mtime_ns}:{info.st_ino}"
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                sha.update(chunk)
                if time.monotonic() >= deadline:
                    raise SnapshotTimeout(f"snapshot over its budget while reading {path}")
    except OSError as exc:
        return f"unreadable:{exc.errno}"
    return f"{mode:o}:{sha.hexdigest()}"


def _host_owned(path: str) -> bool:
    """A regular file with one link: what the host appends to inside the telemetry folder. A file that vanished is left out too."""
    try:
        info = os.lstat(path)
    except OSError:
        return True
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def _entries(root: str) -> Iterator[str]:
    """Absolute paths of the files and symlinks the snapshot covers."""
    unreadable: list[str] = []  # a folder the walk cannot list would hide what is in it: it is an entry of its own
    runs = os.path.join(root, *TELEMETRY_PARENT, TELEMETRY_DIR)  # the host writes its run telemetry here (the lease heartbeat)
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=lambda exc: unreadable.append(exc.filename)):
        git = folder == root and ".git" in dirs
        telemetry = folder == runs or folder.startswith(runs + os.sep)  # only regular files are left out there; a link is still a change
        for name in files:
            path = os.path.join(folder, name)
            if not (telemetry and _host_owned(path)):
                yield path
        for name in dirs:
            if os.path.islink(os.path.join(folder, name)):  # walk lists a link to a folder as a folder and does not enter it
                yield os.path.join(folder, name)
        if git:
            dirs[:] = [name for name in dirs if name != ".git"]
            for kept in GIT_KEPT:
                path = os.path.join(root, kept)
                if os.path.isfile(path):
                    yield path
                elif os.path.isdir(path):
                    yield from (os.path.join(sub, name) for sub, _dirs, names in os.walk(path) for name in names)
    yield from unreadable


def snapshot(root: str | os.PathLike[str], budget_s: float | None = None) -> dict[str, str]:
    """``{relative posix path: digest}`` of the worktree. ``SnapshotTimeout`` after ``budget_s`` (default ``SNAPSHOT_BUDGET_S``)."""
    base = os.fspath(root)
    deadline = time.monotonic() + (SNAPSHOT_BUDGET_S if budget_s is None else budget_s)
    out: dict[str, str] = {}
    for path in _entries(base):
        if time.monotonic() >= deadline:
            raise SnapshotTimeout(f"snapshot over its budget at {path}")
        out[os.path.relpath(path, base).replace(os.sep, "/")] = _digest(path, deadline)
    return out


def _noise(path: str) -> bool:
    """A file in a ``.pytest_cache`` folder: pytest writes it on every run and nothing imports it. ``__pycache__`` is NOT noise."""
    return NOISE_DIR in path.split("/")[:-1]


def bytecode_refusal(path: str) -> str | None:
    """The reason a changed path is refused when it is a ``.pyc`` or ``.pyo`` file, anywhere, else None.

    The CLI and the verify command run with ``PYTHONDONTWRITEBYTECODE=1``, so a bytecode file that appears, changes or goes away is the
    author's. Python imports an UNCHECKED_HASH ``.pyc`` in place of its ``.py`` without reading the source.
    """
    if path.lower().endswith(BYTECODE):
        return (f"protected_path: {path!r} is a Python bytecode file: python imports it in place of the source. "
                "Delete every .pyc and .pyo you made and do not make bytecode")
    return None


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths created, changed or deleted between two snapshots (the ``.pytest_cache`` folder left out)."""
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path) and not _noise(path))


def _token_values(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in TOKEN_KEYS and isinstance(value, str):
                yield value
            else:
                yield from _token_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _token_values(item)


def login_secrets(*paths: str | os.PathLike[str]) -> set[bytes]:
    """The bytes of each readable login file, and of the ``accessToken`` / ``refreshToken`` values in it (JSON, any depth).

    Values shorter than ``MIN_SECRET`` are left out. The result is for ``leaks`` and memory only: never log it, never put it in a detail.
    """
    found: set[bytes] = set()
    for path in paths:
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        found |= {data, data.strip()}
        try:
            found |= {value.encode() for value in _token_values(json.loads(data))}
        except ValueError:
            pass
    return {secret for secret in found if len(secret) >= MIN_SECRET}


def _holds(path: str, secrets: set[bytes], deadline: float) -> bool:
    keep = max(map(len, secrets)) - 1
    tail = b""
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(SCAN_CHUNK):
                if time.monotonic() >= deadline:
                    raise SnapshotTimeout(f"secret scan over its budget while reading {path}")
                data = tail + chunk
                if any(secret in data for secret in secrets):
                    return True
                tail = data[-keep:] if keep else b""
    except OSError:
        return False
    return False


def leaks(root: str | os.PathLike[str], changed: list[str], secrets: set[bytes], budget_s: float | None = None) -> list[str]:
    """The changed paths (relative, as in ``changed``) whose content holds any of ``secrets``. A link is not read, a deleted path is skipped.

    ``SnapshotTimeout`` after ``budget_s`` (default ``SNAPSHOT_BUDGET_S``).
    """
    if not secrets:
        return []
    deadline = time.monotonic() + (SNAPSHOT_BUDGET_S if budget_s is None else budget_s)
    found = []
    for rel in changed:
        path = os.path.join(os.fspath(root), rel)
        try:
            regular = stat.S_ISREG(os.lstat(path).st_mode)
        except OSError:
            continue
        if regular and _holds(path, secrets, deadline):
            found.append(rel)
    return found


def _owner_alive(home: Path) -> bool:
    try:
        pid = int((home / OWNER).read_text())
    except (OSError, ValueError):
        try:
            return time.time() - home.stat().st_mtime < UNOWNED_GRACE_S
        except OSError:
            return False
    if pid <= 0:  # kill(0, ...) would signal a whole process group
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def homes_dir(real_home: Path) -> Path:
    """The folder that holds the private HOMEs: ``$SIMPLICIO_247_AUTHOR_HOME_BASE``, else ``<real home>/.cache/simplicio-loop-author``.

    The packaged unit has ProtectHome=read-only, so the operator points this at a folder in ReadWritePaths. It must be an absolute path
    inside the real HOME (and not the HOME itself): the sandbox hides the real HOME and binds back only the run's own folder, so a
    base elsewhere would leave every other run's login copy readable. ``OSError`` (EINVAL) otherwise. Empty means unset.
    """
    raw = os.environ.get(HOME_BASE_ENV)
    if not raw:
        return real_home / HOMES
    base = Path(os.path.normpath(raw))
    home = Path(os.path.normpath(real_home))
    if not Path(raw).is_absolute() or base == home or home not in base.parents:
        raise OSError(errno.EINVAL, f"{HOME_BASE_ENV}={raw} is not valid: use an absolute path inside the HOME {home}")
    return base


def sweep(real_home: Path) -> None:
    """Delete the private HOMES whose owner is gone (a killed run cannot clean its own)."""
    with contextlib.suppress(OSError):
        for home in homes_dir(real_home).iterdir():
            if not _owner_alive(home):
                shutil.rmtree(home, ignore_errors=True)


def make_home(real_home: Path, name: str) -> Path:
    """A private HOME (0700) with a 0600 copy of the login and the pid of this process.

    ``LoginMissing`` when there is no login; ``OSError`` that names the folder and the OS error when it cannot be made.
    """
    source = real_home / LOGIN
    if not source.is_file():
        raise LoginMissing(f"{source} not found: log in to claude first")
    base = homes_dir(real_home)
    sweep(real_home)
    try:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)  # on every creation: a parallel run may have emptied it
    except OSError as exc:
        raise OSError(exc.errno, f"cannot create {base}: {exc.strerror or exc}") from exc
    home = base / name
    try:
        home.mkdir(mode=0o700)
        (home / OWNER).write_text(str(os.getpid()))
        (home / LOGIN.parent).mkdir(mode=0o700)
        fd = os.open(home / LOGIN, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(source.read_bytes())
    except BaseException:
        drop_home(home)
        raise
    return home


def drop_home(home: Path) -> None:
    """Delete the private HOME. The folder that holds the HOMES stays: another run may be using it."""
    shutil.rmtree(home, ignore_errors=True)


def reset_config(home: Path) -> None:
    """Remove what the author may have written in its HOME for the next round to load (settings, hooks, agents, skills, plugins)."""
    for name in CLAUDE_CONFIG:
        target = home / ".claude" / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                target.unlink()


@contextlib.contextmanager
def terminating() -> Iterator[None]:
    """On the main thread, SIGTERM and SIGHUP raise ``SystemExit`` so the ``finally`` of the caller runs; the old handlers come back."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def stop(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    saved = {sig: signal.signal(sig, stop) for sig in TERMINATION}
    try:
        yield
    finally:
        for sig, handler in saved.items():
            if handler is not None:  # None: it was installed from C and cannot be set back from Python
                signal.signal(sig, handler)
