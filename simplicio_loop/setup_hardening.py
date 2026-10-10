"""Setup hardening primitives (#1637, #1657).

Minimal probe env, PATH hygiene, exact download allowlist, strict redirect
handling, safe reads of private state files and an isolated cwd for git.

PATH hygiene (decision: warn and ignore). Host detection, the prerequisite probes and the GitHub credential sources never
run a program found in an unsafe PATH entry; ``path_warnings`` names each one and ``simplicio-loop setup`` prints it. An entry
is unsafe when it is relative or empty, is ``~/.local/bin`` (however it is spelled or linked), cannot be examined, is writable
by anyone (``o+w``, sticky or not), belongs to a user other than root and the current one, or sits under a folder or link
that anyone can rewrite (``o+w`` without the sticky bit) or that a foreign user owns. A folder that does not exist is not
searched and not reported. Group write on a folder that root or the user owns is accepted: Homebrew (``/opt/homebrew/bin`` is
``775 user:admin``) and Debian (``/usr/local/bin`` is ``root:staff``) install like that, and their group is trusted.
``~/.local/bin`` is the one folder the setup writes to itself (gh and uv): ``safe_which(trusted=...)`` runs those exact files,
only after ``setup_cli`` checked their recorded SHA256.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlsplit

PROBE_ENV_KEYS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "XDG_CONFIG_HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "WINDIR",
    "PATHEXT",
    "COMSPEC",
)

# Exact hosts serving GitHub release assets (gh and uv publish on GitHub Releases).
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)

_SHARED_WRITE = stat.S_IWGRP | stat.S_IWOTH


class UnsafeFileError(Exception):
    """A state file is not a private regular file owned by the current user."""


class RedirectError(Exception):
    """A download redirect is missing its target or leaves the allowlist."""


def minimal_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for subprocess probes: locale and paths only, never tokens."""
    source = os.environ if environ is None else environ
    return {key: source[key] for key in PROBE_ENV_KEYS if key in source}


def path_warnings(path_value: str, home: str | None = None) -> list[tuple[str, str]]:
    """Unsafe PATH entries as (entry, reason) pairs.

    reason is relative, user_local_bin, unreadable, writable_by_others, writable_parent or foreign_owner."""
    local_bin = os.path.realpath(os.path.join(home or str(Path.home()), ".local", "bin"))
    warnings: list[tuple[str, str]] = []
    for entry in path_value.split(os.pathsep):
        reason = _entry_reason(entry, local_bin)
        if reason:
            warnings.append((entry, reason))
    return warnings


def _foreign(info: os.stat_result) -> bool:
    return info.st_uid not in (0, os.geteuid())


def _entry_reason(entry: str, local_bin: str) -> str | None:
    if not entry or not os.path.isabs(entry):
        return "relative"
    real = os.path.realpath(entry)
    if real == local_bin:
        return "user_local_bin"
    if os.name == "nt":
        return None
    try:
        info = os.stat(real)
    except (FileNotFoundError, NotADirectoryError):
        return None  # nothing there to run; it is checked again the next time
    except OSError:
        return "unreadable"
    if info.st_mode & stat.S_IWOTH:
        return "writable_by_others"
    if _foreign(info):
        return "foreign_owner"
    # whoever can rewrite a folder above the entry, or the link that points at it, can swap what is inside
    holders = {*_ancestors(os.path.normpath(entry)), *_ancestors(real)} - {real}
    for holder in sorted(holders):
        try:
            above = os.lstat(holder)
        except OSError:
            return "unreadable"
        if _foreign(above):
            return "foreign_owner"
        if stat.S_ISDIR(above.st_mode) and above.st_mode & stat.S_IWOTH and not above.st_mode & stat.S_ISVTX:
            return "writable_parent"
    return None


def _ancestors(path: str) -> Iterator[str]:
    """``path`` and every folder above it, down to the root."""
    while True:
        yield path
        parent = os.path.dirname(path)
        if parent == path:
            return
        path = parent


def safe_path(path_value: str, home: str | None = None) -> str:
    """PATH without the entries ``path_warnings`` reports, for host detection."""
    unsafe = {entry for entry, _ in path_warnings(path_value, home)}
    kept = [entry for entry in path_value.split(os.pathsep) if entry and entry not in unsafe]
    return os.pathsep.join(kept)


def exec_path(path_value: str, home: str | None = None) -> str:
    """``safe_path`` for a child process, never empty: an empty PATH makes the system search the current directory."""
    return safe_path(path_value, home) or os.defpath


def _home_of(environ: Mapping[str, str]) -> str | None:
    return environ.get("HOME") or environ.get("USERPROFILE")


def safe_which(environ: Mapping[str, str], trusted: Mapping[str, str] | None = None) -> Callable[[str], str | None]:
    """``which`` over the PATH of ``environ`` without its unsafe entries.

    ``trusted`` maps a program name to an exact file the caller already verified; it is used as is when it is a file.
    """
    path = safe_path(environ.get("PATH", os.defpath), _home_of(environ))
    vouched = trusted or {}

    def which(name: str) -> str | None:
        found = vouched.get(name)
        return found if found and os.path.isfile(found) else shutil.which(name, path=path)

    return which


def probe_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """``minimal_env`` whose PATH has no unsafe entry, so a probe never resolves a program through one."""
    source = os.environ if environ is None else environ
    env = minimal_env(source)
    if "PATH" in env:
        env["PATH"] = exec_path(env["PATH"], _home_of(source))
    return env


def find_ignored(environ: Mapping[str, str], names: Iterable[str]) -> dict[str, tuple[str, str]]:
    """For each name that has an executable file in an unsafe PATH entry: name -> (path, reason). The first entry wins."""
    unsafe = path_warnings(environ.get("PATH", os.defpath), _home_of(environ))
    found: dict[str, tuple[str, str]] = {}
    for name in names:
        for entry, reason in unsafe:
            if reason == "unreadable":
                continue
            candidate = os.path.join(entry or os.curdir, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                found[name] = (candidate, reason)
                break
    return found


def is_allowed_download(url: str) -> bool:
    """HTTPS URL on an exact allowlisted host, without credentials or a custom port."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in ALLOWED_DOWNLOAD_HOSTS
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
    )


def redirect_target(url: str, status: int, headers: Mapping[str, str]) -> str:
    """Resolve a 3xx response; refuse a missing Location or an off-allowlist target."""
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise RedirectError(f"HTTP {status} redirect from {url} has no Location header")
    target = urljoin(url, location)
    if not is_allowed_download(target):
        raise RedirectError(f"HTTP {status} redirect to a host outside the allowlist: {target}")
    return target


def read_private_text(path: str | os.PathLike[str], max_bytes: int = 1 << 20) -> str:
    """Read a regular file owned by the current user and not writable by others.

    Opens with O_NONBLOCK|O_NOFOLLOW so a FIFO or symlink is refused instead of
    blocking or being followed. A missing file raises FileNotFoundError.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise UnsafeFileError(f"{path}: cannot open safely ({exc.strerror})") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeFileError(f"{path}: not a regular file")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise UnsafeFileError(f"{path}: owned by uid {info.st_uid}, not the current user")
        if os.name != "nt" and info.st_mode & _SHARED_WRITE:
            raise UnsafeFileError(f"{path}: writable by group or others")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, 65536):
            total += len(chunk)
            if total > max_bytes:
                raise UnsafeFileError(f"{path}: larger than {max_bytes} bytes")
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b"".join(chunks).decode("utf-8")


@contextmanager
def isolated_git_cwd(
    environ: Mapping[str, str] | None = None,
) -> Iterator[tuple[str, dict[str, str]]]:
    """Empty cwd outside any repository plus a minimal env for ``git credential fill``.

    The repository config of the user's cwd (and its ``credential.helper``) is never
    read; global and system helpers still apply.
    """
    with tempfile.TemporaryDirectory(prefix="simplicio-git-") as workdir:
        env = probe_env(environ)
        env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(workdir)
        env["GIT_TERMINAL_PROMPT"] = "0"
        yield workdir, env
