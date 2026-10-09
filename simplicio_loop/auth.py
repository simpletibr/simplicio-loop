"""The Simplicio login file, shared with the Simplicio Runtime (#1575).

One module owns it: where the file is, how it is read and checked, how it is written, and how a refresh takes turns
with the other program. The 24/7 watcher, `simplicio-loop login|logout|auth status` and `doctor` all go through here.

* PATH: env `SIMPLICIO_247_LOGIN` (the watcher), then env `SIMPLICIO_AUTH_FILE` (the name the Runtime reads), then
  ~/.simplicio/login.json. Same schema as the Runtime: `access_token`, `refresh_token`, `access_expires_at`,
  `refresh_token_expires_at`, `verification.validated`. Keys this module does not know (the Runtime adds some) are kept.
* SAFETY: a file that group or others can read, or that is a symlink, is refused (read and write). A write goes to a
  temp file in the same folder, mode 0600 before any content, fsync, then rename: a reader never sees half a file.
* REFRESH: the refresh token rotates, so two programs that refresh at once can invalidate it. Before a refresh this
  module takes an exclusive lock on the sidecar `login.lock`, reads the file AGAIN and refreshes only if the access
  token still expires within 60 s. EVIDENCE that the Runtime takes the same lock: its source (runtime_auth.rs
  `auth_lock`: the login file name with the extension changed to `lock`, `File::try_lock`, which is flock on Unix and
  LockFileEx on Windows, 20 s) and the strings of the 3.10.0 binary, and a `login.lock` next to the real file. NOT
  VERIFIED: a refresh race between the real Runtime and this module, and that msvcrt.locking and LockFileEx exclude
  each other on Windows. MITIGATION if the Runtime did not lock: the re-read narrows the window to one request, and a
  refresh the server rejects ends in `simplicio-loop login` (the Runtime flow), never in a lost file.
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

try:
    import fcntl
    msvcrt = None
except ImportError:  # Windows
    fcntl = None
    import msvcrt

WATCHER_ENV = "SIMPLICIO_247_LOGIN"
RUNTIME_ENV = "SIMPLICIO_AUTH_FILE"
RUNTIME_DIR = ".simplicio"
MCP_CLIENT_ID = "simplicio-cli"
REFRESH_WINDOW_S = 60  # refresh when the access token expires within this many seconds
ACCESS_MARGIN_S = 30  # the stored expiry is this much earlier than the server says
DEFAULT_EXPIRES_IN_S = 900  # what the Runtime assumes when the server omits expires_in
LOCK_WAIT_S = 20.0  # the Runtime waits 20 s for the same lock
LOCK_POLL_S = 0.05

_VERSION = re.compile(r"simplicio\s+v?(\d+\.\d+\.\d+)")
_EMAIL = re.compile(r"([^@\s])[^@\s]*@([^@\s]+\.[^@\s]+)")

Post = Callable[[dict], Mapping[str, Any]]


class LoginError(Exception):
    """The login file cannot be used. `reason_code` is stable, the message says what to do and never holds a token."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


# --- where ----------------------------------------------------------------------------------------------------------


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("HOME") or environ.get("USERPROFILE") or Path.home())


def runtime_login_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """The file the Runtime itself uses: SIMPLICIO_AUTH_FILE, else ~/.simplicio/login.json."""
    env = os.environ if environ is None else environ
    explicit = (env.get(RUNTIME_ENV) or "").strip()
    return Path(explicit) if explicit else _home(env) / RUNTIME_DIR / "login.json"


def login_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    """The file this program uses: SIMPLICIO_247_LOGIN, else the Runtime's file."""
    env = os.environ if environ is None else environ
    explicit = (env.get(WATCHER_ENV) or "").strip()
    return Path(explicit) if explicit else runtime_login_path(env)


def lock_path(path: Path) -> Path:
    """`login.json` -> `login.lock`: the sidecar the Runtime locks (the extension is replaced, as Rust does)."""
    return Path(path).with_suffix(".lock")


# --- read -----------------------------------------------------------------------------------------------------------


def _symlink_error(path: Path) -> LoginError:
    return LoginError("login_symlink", f"{path} is a symlink; remove it and run: simplicio-loop login")


def read_login(path: Optional[Path] = None) -> dict:
    """The login file as a dict. Raises LoginError: login_missing, login_symlink, login_permissions, login_invalid."""
    path = Path(path) if path else login_path()
    if path.is_symlink():
        raise _symlink_error(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        raise LoginError("login_missing", f"no login file at {path}; run: simplicio-loop login") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _symlink_error(path) from None
        raise LoginError("login_invalid", f"cannot read {path}: {exc.strerror}") from None
    with os.fdopen(fd, encoding="utf-8") as handle:
        mode = os.fstat(handle.fileno()).st_mode & 0o777
        if os.name != "nt" and mode & 0o077:
            raise LoginError("login_permissions",
                             f"{path} can be read by group or others (mode {mode:03o}); run: chmod 600 {path}")
        try:
            data = json.loads(handle.read())
        except (ValueError, UnicodeDecodeError):
            data = None
    if not isinstance(data, dict):
        raise LoginError("login_invalid", f"{path} is not a login file (JSON object expected); run: simplicio-loop login")
    return data


# --- write ----------------------------------------------------------------------------------------------------------


def _unlink_quiet(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":
        return
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_login(login: Mapping[str, Any], path: Optional[Path] = None) -> None:
    """Atomic write: temp file in the same folder, 0600 before the content, fsync, rename. Refuses a symlink."""
    path = Path(path) if path else login_path()
    if path.is_symlink():
        raise _symlink_error(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = None
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # a root refresh must not hand the user's file to root
        with contextlib.suppress(OSError):
            info = path.stat()
            owner = (info.st_uid, info.st_gid)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)  # before any content, whatever the umask
        if owner is not None:
            os.fchown(fd, *owner)
        view = memoryview((json.dumps(login, indent=2) + "\n").encode("utf-8"))
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        _unlink_quiet(tmp)
        raise
    os.close(fd)
    try:
        os.replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    _fsync_dir(path.parent)


def apply_tokens(login: dict, data: Mapping[str, Any], now: Optional[float] = None) -> None:
    """Put a token response into `login`. A response without refresh_token keeps the old one (as the Runtime does)."""
    access = str(data.get("access_token") or "")
    if not access:
        raise LoginError("token_response_invalid", "the token response has no access_token")
    stamp = int(time.time() if now is None else now)
    login["access_token"] = access
    if data.get("refresh_token"):
        login["refresh_token"] = data["refresh_token"]
    login["access_expires_at"] = stamp + int(data.get("expires_in") or DEFAULT_EXPIRES_IN_S) - ACCESS_MARGIN_S
    if data.get("refresh_token_persistent"):
        login["refresh_token_expires_at"] = 0
    else:
        login["refresh_token_expires_at"] = stamp + int(data.get("refresh_token_expires_in") or 0)
    entitlement = data.get("entitlement")
    if isinstance(entitlement, dict):
        validated = login.setdefault("verification", {}).setdefault("validated", {})
        validated["ok"] = True
        validated["active"] = bool(entitlement.get("active"))
        validated["entitlement"] = entitlement


# --- the lock -------------------------------------------------------------------------------------------------------


def _try_lock(fd: int) -> bool:
    """One attempt at the exclusive lock; False while another process holds it."""
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                return False
            raise
        return True
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def file_lock(path: Path, *, wait_s: float = LOCK_WAIT_S) -> Iterator[None]:
    """Exclusive advisory lock on the sidecar of `path`. The kernel drops it when the owner dies: a left-over file is no lock."""
    lock = lock_path(Path(path))
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(lock, flags, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise LoginError("login_symlink", f"{lock} is a symlink; remove it") from None
        raise
    try:
        deadline = time.monotonic() + wait_s
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise LoginError("login_lock_timeout",
                                 f"another program holds {lock} (the Runtime renews the login there); try again")
            time.sleep(LOCK_POLL_S)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def refresh_if_due(path: Optional[Path], post: Post, *, now: Optional[float] = None,
                   window: int = REFRESH_WINDOW_S, wait_s: float = LOCK_WAIT_S) -> tuple[dict, bool]:
    """(login, refreshed). `post(payload)` makes the one token request and returns the response.

    Not due (fresh access token, or no refresh token): no lock, no request. Due: take the lock, read the file AGAIN
    (the other program may have refreshed while we waited), and only if it is still due send ONE request and write the
    result into the freshly read dict, so keys written by the Runtime in between survive.
    """
    path = Path(path) if path else login_path()

    def due(login: dict, stamp: float) -> bool:
        refresh = str(login.get("refresh_token") or "").strip()
        return bool(refresh) and _int(login.get("access_expires_at")) <= stamp + window

    login = read_login(path)
    if not due(login, time.time() if now is None else now):
        return login, False
    with file_lock(path, wait_s=wait_s):
        login = read_login(path)
        if not due(login, time.time() if now is None else now):
            return login, False
        payload = {"grant_type": "refresh_token", "refresh_token": str(login["refresh_token"]).strip(),
                   "client_id": MCP_CLIENT_ID}
        if login.get("refresh_request_id"):  # left by a Runtime refresh that lost its answer: the server can replay it
            payload["refresh_request_id"] = login["refresh_request_id"]
        data = post(payload)
        apply_tokens(login, data, now=now)
        login.pop("refresh_request_id", None)
        write_login(login, path)
        return login, True


def clear_login(path: Optional[Path] = None) -> bool:
    """Delete the login file under the lock (logs the Runtime out too). True if a file was removed."""
    path = Path(path) if path else login_path()
    if not (path.exists() or path.is_symlink()):
        return False
    with file_lock(path):
        try:
            path.unlink()  # unlink never follows a symlink
        except FileNotFoundError:
            return False
    return True


# --- what the file says (never a token) -----------------------------------------------------------------------------


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def mask_email(email: str) -> str:
    """`wesley@gmail.com` -> `w***@gmail.com`; anything that is not an address gives ''."""
    found = _EMAIL.fullmatch(email.strip())
    return f"{found.group(1)}***@{found.group(2)}" if found else ""


def summary(login: Mapping[str, Any], now: Optional[float] = None) -> dict:
    """Public facts of a login: no token, no unmasked e-mail."""
    stamp = time.time() if now is None else now
    verification = login.get("verification")
    validated = verification.get("validated") if isinstance(verification, dict) else None
    validated = validated if isinstance(validated, dict) else {}
    user = validated.get("user") if isinstance(validated.get("user"), dict) else {}
    entitlement = validated.get("entitlement")
    access_expires = _int(login.get("access_expires_at"))
    refresh_expires = _int(login.get("refresh_token_expires_at"))
    return {
        "email": mask_email(str(user.get("email") or "")),
        "access_expires_at": access_expires,
        "access_expired": access_expires <= stamp,
        "refresh_expires_at": refresh_expires,
        "refresh_expired": bool(refresh_expires) and refresh_expires <= stamp,  # 0 = persistent or unknown
        "has_refresh_token": bool(str(login.get("refresh_token") or "").strip()),
        "entitlement": ({key: entitlement.get(key) for key in ("tier", "status", "source", "plan", "active")}
                        if isinstance(entitlement, dict) else None),
    }


# --- the Runtime ----------------------------------------------------------------------------------------------------


def runtime_binary(environ: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The Runtime: `simplicio` on PATH, else its managed copy in ~/.simplicio/bin. None when absent."""
    env = os.environ if environ is None else environ
    found = shutil.which("simplicio", path=env.get("PATH"))
    if found:
        return Path(found)
    managed = _home(env) / RUNTIME_DIR / "bin" / ("simplicio.exe" if os.name == "nt" else "simplicio")
    return managed if managed.is_file() and os.access(managed, os.X_OK) else None


def runtime_version(binary: Path, timeout: float = 10) -> Optional[str]:
    """`simplicio --version` -> '3.10.0', or None when it does not answer."""
    try:
        done = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    found = _VERSION.search(done.stdout) if done.returncode == 0 else None
    return found.group(1) if found else None
