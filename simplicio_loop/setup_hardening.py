"""Setup hardening primitives (#1637).

Minimal probe env, PATH hygiene, exact download allowlist, strict redirect
handling, safe reads of private state files and an isolated cwd for git.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
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
    """Unsafe PATH entries as (entry, reason) pairs."""
    local_bin = os.path.normpath(os.path.join(home or str(Path.home()), ".local", "bin"))
    warnings: list[tuple[str, str]] = []
    for entry in path_value.split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            warnings.append((entry, "relative"))
        elif os.path.normpath(entry) == local_bin:
            warnings.append((entry, "user_local_bin"))
        elif os.name != "nt" and _shared_writable(entry):
            warnings.append((entry, "writable_by_others"))
    return warnings


def safe_path(path_value: str, home: str | None = None) -> str:
    """PATH without the entries ``path_warnings`` reports, for host detection."""
    unsafe = {entry for entry, _ in path_warnings(path_value, home)}
    kept = [entry for entry in path_value.split(os.pathsep) if entry and entry not in unsafe]
    return os.pathsep.join(kept)


def _shared_writable(directory: str) -> bool:
    try:
        return bool(os.stat(directory).st_mode & _SHARED_WRITE)
    except OSError:
        return False


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
        env = minimal_env(environ)
        env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(workdir)
        env["GIT_TERMINAL_PROMPT"] = "0"
        yield workdir, env
