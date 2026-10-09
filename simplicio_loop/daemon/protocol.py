"""Wire format and file rules shared by the daemon and its thin client.

Standard library only and no import of the command surface: the launcher imports this module on every
command, so each line here is paid on the hot path.

One request is one JSON line sent with ``sendmsg``; the three stdio file descriptors of the caller ride along
as ``SCM_RIGHTS``. The daemon forks, the child dups them onto 0, 1 and 2 and runs the program, so output
streams straight to the caller and the daemon never copies or runs command bytes. Replies are JSON lines.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import socket
import stat
import struct
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only: the typing module costs more than the rest of this file
    from typing import Any, Mapping, Optional, Sequence

PROTOCOL = 1
EX_UNAVAILABLE = 69
MAX_REQUEST_BYTES = 8 << 20
MAX_SOCKET_PATH = 100  # sun_path holds 108 bytes on Linux and 104 on macOS
OPT_OUT_ENV = "SIMPLICIO_LOOP_DAEMON"
DIR_ENV = "SIMPLICIO_LOOP_DAEMON_DIR"
OPT_OUT_HINT = "run in-process with SIMPLICIO_LOOP_DAEMON=0"


class DaemonError(Exception):
    """A daemon problem with a stable ``code`` (``peer_uid``, ``stale``, ``busy``, ``socket_mode`` ...)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


Paths = collections.namedtuple("Paths", "sock pid log")
# Set in a command the daemon runs: where to reach the daemon that runs it.
Current = collections.namedtuple("Current", "run_dir key")


CURRENT: Current | None = None


def supported() -> bool:
    """AF_UNIX, fork and descriptor passing. Windows has none of them, and the frozen binary starts differently
    (UNVERIFIED there): both run without a daemon."""
    return (sys.platform != "win32" and not getattr(sys, "frozen", False) and hasattr(os, "fork")
            and hasattr(socket, "AF_UNIX") and hasattr(socket, "send_fds"))


def secure_dir(path: os.PathLike[str] | str, create: bool = True) -> str:
    """The directory at ``path``, created 0700 if missing, refused unless it is private to this user.

    Refused: a symlink, a non-directory, another owner, any group or other permission bit, and a parent that
    others can write to (unless it is sticky), because that would let them rename the directory away.
    """
    target = os.path.abspath(os.fspath(path))
    parent_path = os.path.dirname(target)
    if create and not os.path.lexists(target):
        os.makedirs(parent_path, exist_ok=True)
        try:
            os.mkdir(target, 0o700)
        except FileExistsError:
            pass
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        raise DaemonError("dir_missing", f"{target} does not exist") from None
    if stat.S_ISLNK(info.st_mode):
        raise DaemonError("dir_symlink", f"{target} is a symlink; remove it")
    if not stat.S_ISDIR(info.st_mode):
        raise DaemonError("dir_type", f"{target} is not a directory")
    if info.st_uid != os.geteuid():
        raise DaemonError("dir_owner", f"{target} belongs to another user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise DaemonError("dir_mode", f"{target} must not be open to group or others (chmod 700)")
    parent = os.lstat(parent_path)
    if parent.st_mode & 0o022 and not parent.st_mode & stat.S_ISVTX:
        raise DaemonError("dir_parent", f"{parent_path} can be written by others and is not sticky")
    return target


def run_dir(environ: Optional[Mapping[str, str]] = None) -> str:
    """``$SIMPLICIO_LOOP_DAEMON_DIR``, else ``$XDG_RUNTIME_DIR/simplicio-loop``, else ``~/.simplicio-loop/run``."""
    environ = os.environ if environ is None else environ
    explicit = environ.get(DIR_ENV)
    if explicit:
        return secure_dir(explicit)
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return secure_dir(os.path.join(runtime, "simplicio-loop"))
    return secure_dir(os.path.join(os.path.expanduser("~"), ".simplicio-loop", "run"))


def daemon_key(environ: Optional[Mapping[str, str]] = None, exe: str | None = None, package_dir: str | None = None) -> str:
    """One daemon per installation and per interpreter environment that shapes ``sys.path`` or the network guard."""
    environ = os.environ if environ is None else environ
    package = package_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parts = [
        os.path.realpath(exe or sys.executable), os.path.realpath(package),
        environ.get("PYTHONPATH", ""), environ.get("PYTHONHOME", ""), environ.get("SIMPLICIO_CORE_NO_NETWORK", ""),
    ]
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:12]


def paths(directory: os.PathLike[str] | str, key: str) -> Paths:
    base = os.path.join(os.fspath(directory), key)
    if len(os.fsencode(base + ".sock")) > MAX_SOCKET_PATH:
        raise DaemonError("dir_long", f"{base}.sock is too long for a unix socket; set {DIR_ENV} to a shorter directory")
    return Paths(base + ".sock", base + ".pid", base + ".log")


def peer_uid(sock: socket.socket) -> Optional[int]:
    """The user id of the process on the other end, or None where the platform cannot tell."""
    try:
        if sys.platform.startswith("linux"):
            data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            return struct.unpack("3i", data)[1]
        if sys.platform == "darwin":  # LOCAL_PEERCRED: struct xucred { u_int cr_version; uid_t cr_uid; ... }
            data = sock.getsockopt(0, 1, 76)
            return struct.unpack_from("II", data)[1]
    except OSError:
        return None
    return None


def encode(message: Mapping[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def send_request(sock: socket.socket, message: Mapping[str, Any], fds: Sequence[int] = ()) -> None:
    """Send one request line, with ``fds`` attached to its first bytes."""
    data = encode(message)
    if len(data) > MAX_REQUEST_BYTES:
        raise DaemonError("too_big", "the request (arguments and environment) is too big")
    sent = socket.send_fds(sock, [data], list(fds)) if fds else sock.send(data)
    if sent < len(data):
        sock.sendall(data[sent:])


def read_message(sock: socket.socket, buffer: bytearray) -> Optional[dict]:
    """The next reply line (blocking), or None at end of stream. ``buffer`` keeps bytes past the first line."""
    while b"\n" not in buffer:
        try:
            chunk = sock.recv(65536)
        except ConnectionResetError:
            chunk = b""
        if not chunk:
            return None
        buffer += chunk
    line, _, rest = bytes(buffer).partition(b"\n")
    buffer[:] = rest
    try:
        parsed = json.loads(line)
    except ValueError:
        raise DaemonError("bad_reply", "the daemon sent something that is not JSON") from None
    if not isinstance(parsed, dict):
        raise DaemonError("bad_reply", "the daemon sent a reply that is not an object")
    return parsed
