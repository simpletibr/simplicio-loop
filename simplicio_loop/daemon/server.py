"""The daemon: one asyncio accept loop that forks a child per request.

The parent is single-threaded and never runs program code. It checks who is asking (socket owner mode, peer
user id, protocol, installed code), takes a slot (bounded: the rest wait, a full queue is refused), forks, and
reports the exit code. The child (``runner``) runs the program on the stdio of the caller. When the caller
hangs up, the child's process group is terminated.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import importlib
import importlib.util
import os
import resource
import signal
import socket
import stat
import sys
import threading
import time
from typing import Any, Iterable, Mapping, Optional

from . import protocol, runner

READ_TIMEOUT_S = 10.0
KILL_GRACE_S = 5.0
MAX_CHILDREN_CAP = 16
CODE_SUFFIXES = (".py", ".so", ".pyd")
SKIPPED_DIRS = ("__pycache__", "_bundle")


def code_roots() -> list[str]:
    """The directories of the code this daemon imports: the loop and the two operators."""
    found: list[str] = []
    for name in ("simplicio_loop", "simplicio_mapper", "simplicio"):
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.submodule_search_locations:
            found.extend(spec.submodule_search_locations)
    return found


def fingerprint(roots: Iterable[str | os.PathLike[str]]) -> str:
    """A digest of every code file under ``roots`` (path, mtime, size): any install, update or edit changes it."""
    entries: list[tuple[str, int, int]] = []

    def walk(directory: str) -> None:
        try:
            scan = os.scandir(directory)
        except OSError:
            return
        with scan:
            for entry in scan:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIPPED_DIRS:
                        walk(entry.path)
                elif entry.name.endswith(CODE_SUFFIXES):
                    info = entry.stat(follow_symlinks=False)
                    entries.append((entry.path, info.st_mtime_ns, info.st_size))

    for root in roots:
        walk(os.fspath(root))
    entries.sort()
    return hashlib.sha256(repr(entries).encode()).hexdigest()


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def default_max_children() -> int:
    """Simultaneous programs this machine can carry: its measured safe workers, at least one, at most 16."""
    try:
        from ..local_capacity import probe_local_capacity

        safe = probe_local_capacity(".", requested_workers=MAX_CHILDREN_CAP).safe_workers
    except (ImportError, OSError):
        safe = 0
    return max(1, min(MAX_CHILDREN_CAP, safe or (os.cpu_count() or 2) - 1))


def acquire_lock(pid_path: str) -> Optional[int]:
    """Take the exclusive lock that names the one daemon of this key; None when another daemon holds it."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
    for _ in range(3):
        fd = os.open(pid_path, flags, 0o600)
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        try:
            same = os.fstat(fd).st_ino == os.stat(pid_path).st_ino
        except FileNotFoundError:
            same = False
        if same:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            return fd
        os.close(fd)  # the file was replaced between open and lock: lock the new one
    return None


class Daemon:
    def __init__(self, run_dir: os.PathLike[str] | str, *, key: str, programs: Optional[Mapping[str, str]] = None,
                 roots: Optional[Iterable[str]] = None, idle_s: float = 900.0, max_children: Optional[int] = None,
                 max_waiting: int = 64, allowed_uid: Optional[int] = None,
                 preload: Iterable[str] = runner.PRELOAD) -> None:
        self.run_dir = os.fspath(run_dir)
        self.key = key
        self.programs = dict(runner.PROGRAMS if programs is None else programs)
        self.roots = list(code_roots() if roots is None else roots)
        self.idle_s = idle_s
        self.max_children = max_children or default_max_children()
        self.max_waiting = max_waiting
        self.allowed_uid = os.geteuid() if allowed_uid is None else allowed_uid
        self.preload = tuple(preload)
        self.paths = protocol.paths(self.run_dir, key)
        self.loaded = ""
        self.active = 0
        self.waiting = 0
        self.served = 0
        self._started = time.monotonic()
        self._last = time.monotonic()
        self._entries: dict[str, Any] = {}
        self._children: dict[int, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()
        self._slots: asyncio.Semaphore
        self._stopping: asyncio.Event
        self._reason = ""
        self._lock_fd: Optional[int] = None
        self._listener: Optional[socket.socket] = None

    # ---- life cycle --------------------------------------------------------------------------------------

    def log(self, message: str) -> None:
        print(time.strftime("%Y-%m-%dT%H:%M:%S"), message, file=sys.stderr, flush=True)

    def shutdown(self, reason: str) -> None:
        if not self._stopping.is_set():
            self._reason = reason
            self._stopping.set()

    def _bind(self) -> socket.socket:
        path = self.paths.sock
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            pass
        else:  # we hold the lock, so nobody serves on an old socket file
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise protocol.DaemonError("socket_in_use", f"{path} exists and is not a socket of this user")
            os.unlink(path)
        previous = os.umask(0o177)
        try:
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(path)
        finally:
            os.umask(previous)
        os.chmod(path, 0o600)
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener

    def _release(self) -> None:
        """Stop accepting and free the key, so a replacement daemon can start while this one drains."""
        if self._listener is not None:
            self._listener.close()
            self._listener = None
            _unlink(self.paths.sock)
        if self._lock_fd is not None:
            _unlink(self.paths.pid)
            os.close(self._lock_fd)
            self._lock_fd = None

    async def serve(self) -> int:
        directory = protocol.secure_dir(self.run_dir)
        self.paths = protocol.paths(directory, self.key)
        self._lock_fd = acquire_lock(self.paths.pid)
        if self._lock_fd is None:
            return 0  # another daemon serves this key
        os.chdir(directory)  # never leave a caller's directory on the import path
        sys.path[:] = [p for p in sys.path if p not in ("", ".")]
        loop = asyncio.get_running_loop()
        self._slots = asyncio.Semaphore(self.max_children)
        self._stopping = asyncio.Event()
        try:
            self.loaded = fingerprint(self.roots)  # before the imports: a change in between reads as stale
            self._entries = {name: runner.resolve(spec) for name, spec in self.programs.items()}
            for module in self.preload:
                importlib.import_module(module)
            self._listener = self._bind()
            for number in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(number, self.shutdown, "signal")
            loop.add_signal_handler(signal.SIGCHLD, self._reap)
            self.log(f"serving {os.path.basename(self.paths.sock)} pid={os.getpid()} max_children={self.max_children}")
            self._started = self._last = time.monotonic()  # idle time counts from the first moment it can serve
            accept = loop.create_task(self._accept(self._listener))
            idle = loop.create_task(self._watch_idle())
            await self._stopping.wait()
            accept.cancel()
            idle.cancel()
            self._release()
            if self._reason == "signal":
                for pid in list(self._children):
                    self._signal(pid, signal.SIGTERM)
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self.log(f"stopped: {self._reason}")
        finally:
            self._release()
        return 0

    async def _accept(self, listener: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                connection, _ = await loop.sock_accept(listener)
            except OSError:
                return
            connection.setblocking(False)
            self._last = time.monotonic()
            task = loop.create_task(self._handle(connection))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _watch_idle(self) -> None:
        while True:
            await asyncio.sleep(min(1.0, max(0.05, self.idle_s / 4)))
            if not self._tasks and time.monotonic() - self._last > self.idle_s:
                self.shutdown("idle")
                return

    # ---- children ----------------------------------------------------------------------------------------

    def _reap(self) -> None:
        for pid, future in list(self._children.items()):
            try:
                done, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                done, status = pid, 0
            if done:
                del self._children[pid]
                code = os.waitstatus_to_exitcode(status)
                future.set_result(code if code >= 0 else 128 - code)  # killed by signal N: 128 + N

    @staticmethod
    def _signal(pid: int, number: int) -> None:
        try:
            os.killpg(pid, number)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, number)  # the child has not made its own group yet
            except ProcessLookupError:
                pass

    async def _terminate(self, pid: int, done: asyncio.Future) -> None:
        for number in (signal.SIGTERM, signal.SIGKILL):
            self._signal(pid, number)
            try:
                await asyncio.wait_for(asyncio.shield(done), KILL_GRACE_S)
                return
            except asyncio.TimeoutError:
                continue

    # ---- one connection ----------------------------------------------------------------------------------

    async def _send(self, connection: socket.socket, message: Mapping[str, Any]) -> None:
        try:
            await asyncio.get_running_loop().sock_sendall(connection, protocol.encode(message))
        except OSError:
            pass  # the caller is gone

    async def _receive(self, connection: socket.socket) -> tuple[dict, list[int]]:
        """One request line and the descriptors that came with it."""
        loop = asyncio.get_running_loop()
        buffer = bytearray()
        fds: list[int] = []
        try:
            while b"\n" not in buffer:
                ready = loop.create_future()

                def readable() -> None:
                    loop.remove_reader(connection.fileno())
                    if not ready.done():
                        ready.set_result(None)

                loop.add_reader(connection.fileno(), readable)
                try:
                    await ready
                finally:
                    loop.remove_reader(connection.fileno())
                try:
                    data, received, flags, _ = socket.recv_fds(connection, 65536, 4, getattr(socket, "MSG_CMSG_CLOEXEC", 0))
                except BlockingIOError:
                    continue
                fds.extend(received)
                if flags & getattr(socket, "MSG_CTRUNC", 0) or len(fds) > 3:
                    raise protocol.DaemonError("bad_request", "too many descriptors")
                if not data:
                    raise protocol.DaemonError("bad_request", "the connection closed before a full request")
                buffer += data
                if len(buffer) > protocol.MAX_REQUEST_BYTES:
                    raise protocol.DaemonError("too_big", "the request is too big")
            line = bytes(buffer).partition(b"\n")[0]
            import json

            try:
                request = json.loads(line)
            except ValueError:
                raise protocol.DaemonError("bad_request", "the request is not JSON") from None
            if not isinstance(request, dict):
                raise protocol.DaemonError("bad_request", "the request is not an object")
            return request, fds
        except BaseException:
            for fd in fds:
                os.close(fd)
            raise

    def _stale(self) -> bool:
        """True when the code on disk is not the code this daemon imported. Checked on every request."""
        return fingerprint(self.roots) != self.loaded

    def status(self) -> dict[str, Any]:
        try:
            from importlib.metadata import version

            loop_version = version("simplicio-loop")
        except Exception:  # noqa: BLE001 - a source checkout has no metadata
            loop_version = "unknown"
        return {
            "pid": os.getpid(), "protocol": protocol.PROTOCOL, "version": loop_version, "python": sys.version.split()[0],
            "uptime_s": round(time.monotonic() - self._started, 1), "active": self.active, "waiting": self.waiting,
            "served": self.served, "max_children": self.max_children, "max_waiting": self.max_waiting,
            "idle_s": self.idle_s, "fingerprint": self.loaded[:12], "stale": self._stale(),
            "programs": sorted(self.programs), "threads": threading.active_count(), "socket": self.paths.sock,
            "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20 if sys.platform == "darwin" else 1 << 10)),
        }

    async def _handle(self, connection: socket.socket) -> None:
        fds: list[int] = []
        try:
            if protocol.peer_uid(connection) != self.allowed_uid:
                await self._send(connection, {"error": "peer_uid", "message": "this socket serves another user"})
                return
            request, fds = await asyncio.wait_for(self._receive(connection), READ_TIMEOUT_S)
            if request.get("proto") != protocol.PROTOCOL:
                await self._send(connection, {"error": "protocol",
                                              "message": f"the daemon speaks protocol {protocol.PROTOCOL}"})
                return
            operation = request.get("op")
            if operation == "status":
                await self._send(connection, {"ok": True, **self.status()})
            elif operation == "stop":
                await self._send(connection, {"ok": True})
                self.shutdown("stop")
            elif operation == "exec":
                await self._exec(connection, request, fds)
                fds = []
            else:
                await self._send(connection, {"error": "bad_request", "message": "unknown operation"})
        except protocol.DaemonError as error:
            await self._send(connection, {"error": error.code, "message": str(error)})
        except asyncio.TimeoutError:
            await self._send(connection, {"error": "bad_request", "message": "no complete request in time"})
        except Exception as error:  # noqa: BLE001 - one bad request must not stop the daemon
            self.log(f"internal error: {type(error).__name__}: {error}")
            await self._send(connection, {"error": "internal", "message": type(error).__name__})
        finally:
            for fd in fds:
                os.close(fd)
            connection.close()

    @staticmethod
    def _check(request: Mapping[str, Any], fds: list[int]) -> None:
        argv, env = request.get("argv"), request.get("env")
        ok = (isinstance(request.get("program"), str) and isinstance(request.get("cwd"), str)
              and isinstance(argv, list) and all(isinstance(a, str) for a in argv)
              and isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
              and len(fds) == 3)
        if not ok:
            raise protocol.DaemonError("bad_request", "an exec request needs program, argv, cwd, env and 3 descriptors")

    async def _exec(self, connection: socket.socket, request: dict, fds: list[int]) -> None:
        loop = asyncio.get_running_loop()
        self._check(request, fds)
        program = request["program"]
        if program not in self._entries:
            raise protocol.DaemonError("unknown_program", f"the daemon does not run {program!r}")
        if self._stale():
            self._release()  # free the key now: the client starts the daemon of the new code
            self.shutdown("stale")
            raise protocol.DaemonError("stale", "the installed code changed since the daemon started; it is restarting")
        if self._slots.locked() and self.waiting >= self.max_waiting:
            raise protocol.DaemonError("busy", f"{self.active} running and {self.waiting} waiting; try again")
        self.waiting += 1
        try:
            await self._slots.acquire()
        finally:
            self.waiting -= 1
        started = time.monotonic()
        self.active += 1
        try:
            pid = os.fork()
            if pid == 0:
                try:
                    runner.serve_request(request, fds, self._entries[program], self.run_dir, self.key)
                finally:
                    os._exit(70)  # the child never goes back into the daemon's loop
            done = loop.create_future()
            self._children[pid] = done
            for fd in fds:
                os.close(fd)
            fds.clear()
            await self._send(connection, {"ok": True})
            hangup = loop.create_task(self._hangup(connection))
            await asyncio.wait({done, hangup}, return_when=asyncio.FIRST_COMPLETED)
            if not done.done():
                await self._terminate(pid, done)
            hangup.cancel()
            code = done.result()
            await self._send(connection, {"exit": code})
            self.log(f"{program} exit={code} {time.monotonic() - started:.2f}s")  # never the arguments or the environment
        finally:
            self.active -= 1
            self.served += 1
            self._slots.release()
            self._last = time.monotonic()

    async def _hangup(self, connection: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                if not await loop.sock_recv(connection, 4096):
                    return
            except OSError:
                return
