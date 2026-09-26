"""Observability + opt-in enforcement layer for the #514 process-supervisor contract.

Issue #516 (child of the #498 supervisor epic) asks for: detecting Simplicio processes that
bypass the supervisor, a status/top/queue/cancel/drain/reports surface, a circuit breaker, and
rollout shadow/canary with standalone fallback. This module is the first real slice of that --
built on top of ``simplicio_loop.process_supervisor`` (``ProcessSpec``/``ProcessLease``/
``ProcessResult`` + ``PythonProcessAdapter``) from the already-merged #514, not on the Rust/Tokio
backend from #515 (which may not exist yet in a given checkout).

Explicitly NOT the full #498 DoD -- see ``docs/SUPERVISOR_ENFORCEMENT_RUNBOOK.md`` for what is
implemented now versus deferred (quotas, cgroups/Job Objects resource limiting, full
shadow/canary rollout automation, cross-host sync).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .process_supervisor import ProcessLease, ProcessResult, ProcessSpec, PythonProcessAdapter

REGISTRY_SCHEMA = "simplicio.supervisor-registry/v1"
EVENT_SCHEMA = "simplicio.supervisor-event/v1"
BREAKER_SCHEMA = "simplicio.supervisor-circuit-breaker/v1"

# Substrings that identify a process as part of the Simplicio ecosystem: invoked via one of the
# packaged console scripts (see [project.scripts] in pyproject.toml), as a `-m simplicio_loop.*`
# module, or running a script that lives under this repository's simplicio_loop/ package. This
# is a best-effort *signature* match on argv, not a cryptographic guarantee -- documented as such
# in the runbook. Callers may extend it (e.g. a private fork's own entrypoint names).
SIMPLICIO_SIGNATURES: Sequence[str] = (
    "simplicio_loop",
    "simplicio-loop",
    "simplicio-cli",
    "simplicio-dev-cli",
    "simplicio-mapper",
    "simplicio-remote-worker",
    "simplicio-remote-queue-server",
)

FAILURE_ERROR_CODES = {"spawn_error", "executable_not_found"}

# Linux pidfds bind an operation to the kernel process object, rather than to a
# numeric PID which may be recycled after validation.  CPython does not expose
# these calls on every supported build, so use the stable Linux syscall ABI and
# fail closed when it is not available.  These numbers are shared by the Linux
# architectures we support (x86_64, aarch64, arm, ppc64, and s390x).
_LINUX_SYS_PIDFD_SEND_SIGNAL = 424
_LINUX_SYS_PIDFD_OPEN = 434
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001


# ``flock`` is advisory, so also serialize callers in this interpreter.  The
# latter matters because separate file descriptors in one process do not give
# every platform the same locking semantics as two independent processes.
_REGISTRY_LOCKS: Dict[str, threading.RLock] = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()


def is_simplicio_cmdline(cmdline: Sequence[str]) -> bool:
    """True when ``cmdline`` looks like a Simplicio-ecosystem entrypoint."""
    joined = " ".join(str(part) for part in cmdline)
    return any(signature in joined for signature in SIMPLICIO_SIGNATURES)


def default_state_dir() -> Path:
    return Path(os.environ.get("SIMPLICIO_SUPERVISOR_STATE_DIR", ".simplicio-loop/orchestrator/supervisor"))


def default_registry_path() -> Path:
    return default_state_dir() / "registry.json"


def default_events_path() -> Path:
    return default_state_dir() / "events.jsonl"


def default_breaker_path() -> Path:
    return default_state_dir() / "breaker.json"


def enforcement_enabled(*, override: Optional[bool] = None) -> bool:
    """Enforcement is opt-in and OFF by default. Opt in via ``SIMPLICIO_SUPERVISOR_ENFORCE=1``
    or an explicit ``override``. Callers should treat "unset/unparseable" as OFF (fail safe)."""
    if override is not None:
        return override
    return os.environ.get("SIMPLICIO_SUPERVISOR_ENFORCE", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(path))


@contextmanager
def _registry_write_lock(path: Path) -> Iterable[None]:
    """Take a process-wide exclusive lock for a registry read-modify-write.

    A sidecar lock file keeps the JSON payload replaceable atomically.  On an
    unsupported platform this deliberately raises instead of performing an
    unlocked update: losing a supervised-process record is less safe than
    making that registration unavailable for the current operation.
    """
    key = str(path.resolve())
    with _REGISTRY_LOCKS_GUARD:
        local_lock = _REGISTRY_LOCKS.setdefault(key, threading.RLock())
    with local_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(".%s.lock" % path.name)
        with lock_path.open("a+", encoding="utf-8") as handle:
            if os.name == "nt":  # pragma: no cover - Windows-specific
                try:
                    import msvcrt
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write("0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                except (ImportError, OSError) as exc:
                    raise RuntimeError("registry interprocess lock unavailable") from exc
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                try:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError) as exc:
                    raise RuntimeError("registry interprocess lock unavailable") from exc
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":  # pragma: no cover - Windows-specific
        # ``os.kill(pid, 0)`` is not a supported Windows liveness primitive:
        # depending on the runtime it can request a real signal or produce a
        # permission-shaped false negative.  A query HANDLE pins the object
        # while its exit code is read instead.
        try:
            import ctypes
            from ctypes import wintypes

            handle = _windows_open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
            if not handle:
                return False
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetExitCodeProcess.argtypes = (
                wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
            )
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            exit_code = wintypes.DWORD()
            try:
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                            and exit_code.value == 259)  # STILL_ACTIVE
            finally:
                _windows_close_handle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return False
    return True


def _linux_pidfd_open(pid: int) -> Optional[int]:
    """Open a pidfd, or return ``None`` when the host cannot pin ``pid``.

    A numeric PID must never be signalled after a failed pin: a reuse race is
    preferable to report as an unsuccessful cancellation than to turn into a
    signal for an unrelated process.
    """
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.syscall(_LINUX_SYS_PIDFD_OPEN, pid, 0)
        return fd if fd >= 0 else None
    except (AttributeError, OSError):
        return None


def _linux_pidfd_send_signal(pidfd: int, sig: int) -> bool:
    """Signal one already-pinned Linux process object."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return libc.syscall(_LINUX_SYS_PIDFD_SEND_SIGNAL, pidfd, sig, None, 0) == 0
    except (AttributeError, OSError):
        return False


def _windows_open_process(pid: int, access: int) -> Any:
    """Open a Windows process with correctly declared HANDLE signatures."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(access, False, pid)
    return handle or None


def _windows_close_handle(handle: Any) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


def _process_identity(pid: int) -> Optional[str]:
    """Return a stable identity for ``pid`` when the host can provide one.

    A PID alone is deliberately *not* an identity: it can be reused after a
    supervisor crash.  Linux exposes the kernel start-time tick in procfs,
    which is stable for a process lifetime.  Other hosts without an equally
    reliable, dependency-free source return ``None``.  Callers treat that as
    unavailable rather than guessing that a PID still belongs to a lease.
    """
    proc_root = Path("/proc")
    if proc_root.is_dir():
        depth = _caller_namespace_depth(proc_root)
        if depth is None:
            return None
        try:
            entries = proc_root.iterdir()
        except OSError:
            return None
        for entry in entries:
            if not entry.name.isdigit():
                continue
            values = _nspid_values(entry / "status")
            if values is None or depth >= len(values) or values[depth] != pid:
                continue
            return _proc_entry_identity(entry)
        return None
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        try:
            import ctypes
            from ctypes import wintypes
            handle = _windows_open_process(pid, _PROCESS_QUERY_LIMITED_INFORMATION)
            if not handle:
                return None
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetProcessTimes.argtypes = (
                wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            )
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            try:
                if not kernel32.GetProcessTimes(
                    handle, ctypes.byref(creation), ctypes.byref(exit_time),
                    ctypes.byref(kernel), ctypes.byref(user),
                ):
                    return None
                ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
                return "windows-creation:%d" % ticks
            finally:
                _windows_close_handle(handle)
        except (AttributeError, OSError):
            return None
    # ``ps lstart`` is a later, separate lookup and cannot pin the process
    # object which a numeric PID denotes.  macOS and BSD therefore have no
    # safe dependency-free backend here and must fail closed.
    return None


def _proc_entry_identity(entry: Path) -> Optional[str]:
    """Return Linux's lifetime identity from one already-selected proc entry."""
    try:
        raw = (entry / "stat").read_text(encoding="utf-8", errors="replace")
        # comm may contain spaces and parentheses; fields after the final ')'
        # start at field 3, so starttime (field 22) is offset 19.
        fields = raw.rsplit(")", 1)[1].split()
        return "linux-proc:%s:starttime:%s" % (entry.name, fields[19])
    except (IndexError, OSError):
        return None


def kill_process_tree(
    pid: int, *, sig: int = getattr(signal, "SIGKILL", signal.SIGTERM), expected_identity: Optional[str] = None,
    dedicated_process_group: bool = False,
) -> bool:
    """Best-effort kill of ``pid`` and its descendants, from a thread/process that never held
    the live ``Process`` object -- the real in-flight cancellation the #498 epic still lacked
    (see ``docs/SUPERVISOR_ENFORCEMENT_RUNBOOK.md``): a supervised child registered in
    :class:`ProcessRegistry` could previously only be killed by the coroutine that spawned it
    (on its own timeout/cancellation), never by an external ``cancel`` request arriving on a
    different thread while ``execute`` is still blocked awaiting completion.

    Linux: pidfds pin the kernel process object before it is signalled. A process group is
    signalled only when the registry explicitly proves that the supervisor created a dedicated
    group; an observed/unsupervised process receives an exact pidfd signal only. Windows: an
    open HANDLE pins the object while
    ``taskkill /T /F`` resolves it. macOS/BSD have no equivalent backend in this module, so the
    pidfd acquisition fails and no signal is sent rather than claiming generic POSIX safety.
    """
    if os.name == "nt":  # pragma: no cover - Windows-specific
        # Keep a HANDLE open while taskkill resolves the numeric PID.  Windows
        # cannot recycle a process ID while a handle to that process object is
        # open, so this pins the taskkill target across the validation/signal
        # boundary.  If acquiring the handle fails, do not run taskkill.
        try:
            handle = _windows_open_process(
                pid, _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_TERMINATE,
            )
            if not handle:
                return False
            # Holding ``handle`` prevents PID reuse while this second query is
            # made, so the identity comparison is against the same object
            # taskkill will address below.
            if expected_identity and _process_identity(pid) != expected_identity:
                return False
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=5, check=False,
            )
            if completed.returncode == 0:
                return True
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel32.TerminateProcess.restype = wintypes.BOOL
            return bool(kernel32.TerminateProcess(handle, 1))
        except (AttributeError, OSError, subprocess.SubprocessError):
            return False
        finally:
            if "handle" in locals() and handle:
                try:
                    _windows_close_handle(handle)
                except (AttributeError, OSError):
                    pass

    pidfd = _linux_pidfd_open(pid)
    if pidfd is None:
        return False
    try:
        # Revalidate only after pinning.  Checking the procfs start time before
        # pidfd_open leaves exactly the PID-reuse race this function exists to
        # close.
        if expected_identity and _process_identity(pid) != expected_identity:
            return False
        try:
            # The pinned process being the group leader prevents its group ID
            # from being recycled before killpg.  Never signal a group merely
            # because an unpinned numeric PID happened to be a member of it.
            if dedicated_process_group and os.getpgid(pid) == pid:
                os.killpg(pid, sig)
                return True
        except (ProcessLookupError, PermissionError, OSError):
            pass
        # A process outside a dedicated group still gets an exact, pinned
        # signal.  This is intentionally not ``os.kill(pid, ...)``.
        return _linux_pidfd_send_signal(pidfd, sig)
    finally:
        os.close(pidfd)


@dataclass(frozen=True)
class ProcessRecord:
    """One observed OS process, as seen by ``scan_host_processes``."""

    pid: int
    cmdline: List[str]
    process_identity: Optional[str] = None


def _scan_windows_processes() -> List[ProcessRecord]:
    """Observe Windows processes with psutil, retaining CIM as fallback."""
    try:
        import psutil  # type: ignore
        records: List[ProcessRecord] = []
        for process in psutil.process_iter(["pid", "cmdline"]):
            try:
                info = process.info
                pid = int(info["pid"])
                cmdline = list(info.get("cmdline") or [])
                if not is_simplicio_cmdline(cmdline):
                    records.append(ProcessRecord(pid, cmdline))
                    continue
                identity_before = _process_identity(pid)
                identity_after = _process_identity(pid)
                if identity_before and identity_before == identity_after:
                    records.append(ProcessRecord(pid, cmdline, identity_before))
            except (psutil.AccessDenied, psutil.NoSuchProcess, KeyError, TypeError, ValueError):
                continue
        if records:
            return records
    except ImportError:
        pass
    command = "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    try:
        completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, timeout=5, check=False)
        if completed.returncode != 0:
            return []
        payload = json.loads(completed.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return []
    rows = payload if isinstance(payload, list) else [payload]
    records = []
    for row in rows:
        try:
            pid = int(row["ProcessId"])
            cmdline = _split_windows_command_line(str(row.get("CommandLine") or ""))
            if not is_simplicio_cmdline(cmdline):
                records.append(ProcessRecord(pid, cmdline))
                continue
            identity_before = _process_identity(pid)
            identity_after = _process_identity(pid)
        except (KeyError, TypeError, ValueError):
            continue
        if identity_before and identity_before == identity_after:
            records.append(ProcessRecord(pid, cmdline, identity_before))
    return records

def _split_windows_command_line(command_line: str) -> List[str]:
    """Parse a Windows command line with the platform's own quoting rules."""
    if not command_line:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        argc = ctypes.c_int()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
        shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
        argv = shell32.CommandLineToArgvW(command_line, ctypes.byref(argc))
        if not argv:
            return []
        try:
            return [argv[index] for index in range(argc.value)]
        finally:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
            kernel32.LocalFree.restype = ctypes.c_void_p
            kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))
    except (AttributeError, OSError, ValueError):
        return []

def scan_host_processes() -> List[ProcessRecord]:
    """Enumerate running processes with their argv."""
    proc_root = Path("/proc")
    if proc_root.is_dir():
        return _scan_proc(proc_root)
    if os.name == "nt":
        return _scan_windows_processes()
    return _scan_ps()

def _scan_proc(proc_root: Path) -> List[ProcessRecord]:
    records: List[ProcessRecord] = []
    caller_namespace_depth = _caller_namespace_depth(proc_root)
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            identity_before = _proc_entry_identity(entry)
            raw = (entry / "cmdline").read_bytes()
            identity_after = _proc_entry_identity(entry)
        except OSError:
            continue
        # A process may exit and its proc directory/PID be reused while this
        # scan reads argv.  Do not report a mixed-generation observation.
        if identity_before != identity_after:
            continue
        if not raw:
            continue
        parts = [part for part in raw.decode("utf-8", errors="replace").split("\x00") if part]
        if parts:
            visible_pid = _namespace_visible_pid(entry, caller_namespace_depth)
            if visible_pid is not None:
                records.append(ProcessRecord(visible_pid, parts, identity_before))
    return records


def _nspid_values(status_path: Path) -> Optional[List[int]]:
    """Return the kernel's host-to-inner PID mapping, if it is well-formed."""
    try:
        status = status_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in status.splitlines():
        name, separator, values = line.partition(":")
        if separator and name == "NSpid":
            try:
                return [int(value) for value in values.split()]
            except ValueError:
                return None
    return None


def _caller_namespace_depth(proc_root: Path) -> Optional[int]:
    """Return this caller's position in the PID namespace hierarchy.

    ``/proc/self`` is available on Linux procfs.  When the mapping is absent
    or malformed, there is no safe way to translate host proc-directory PIDs
    into the caller namespace, so return ``None`` and omit records.
    """
    values = _nspid_values(proc_root / "self" / "status")
    if values is None:
        values = _nspid_values(proc_root / str(os.getpid()) / "status")
    return len(values) - 1 if values else None


def _namespace_visible_pid(proc_entry: Path, caller_namespace_depth: Optional[int]) -> Optional[int]:
    """Return the PID visible to this process for one ``/proc`` entry.

    In a nested PID namespace, ``/proc`` can be mounted from the host namespace even though
    child processes created by Python expose namespace-local PIDs through ``Popen.pid`` and
    ``os.kill``.  Linux records the PID at each namespace level in ``NSpid``.  Select the
    caller's level, rather than always selecting the target's innermost (possibly child-only)
    PID.  Missing or incomplete mappings are omitted: using the directory PID
    in that case can signal an unrelated host process.
    """
    if caller_namespace_depth is None:
        return None
    namespace_pids = _nspid_values(proc_entry / "status")
    if namespace_pids is None:
        return None
    if caller_namespace_depth < len(namespace_pids):
        return namespace_pids[caller_namespace_depth]
    return None


def _scan_ps() -> List[ProcessRecord]:
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,args="],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    records: List[ProcessRecord] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, rest = line.partition(" ")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        records.append(ProcessRecord(pid, rest.split()))
    return records


class ProcessRegistry:
    """Cross-process bookkeeping of PIDs launched through the supervisor.

    Persisted to a JSON file so a *separate* CLI invocation (status/top/the detector) can see
    what is currently supervised without sharing Python process memory with the process that
    spawned the child. Registration is keyed by OS pid; a stale entry (the pid was reused by an
    unrelated process after the supervised child exited without unregistering, e.g. a crash of
    the supervisor itself) is pruned on read using both liveness and a
    process-start identity.  Hosts where that identity cannot be obtained fail
    closed and do not retain a persisted PID as supervised.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_registry_path()

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"schema": REGISTRY_SCHEMA, "processes": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema": REGISTRY_SCHEMA, "processes": {}}
        if not isinstance(data, dict) or not isinstance(data.get("processes"), dict):
            return {"schema": REGISTRY_SCHEMA, "processes": {}}
        return data

    def register(
        self, pid: int, *, lease_id: str, spec_hash: str, argv: Sequence[str],
        dedicated_process_group: bool = False,
    ) -> Optional[str]:
        """Record a process and return its lifetime identity when available.

        The returned identity is a required capability for later removal.  A
        caller that cannot obtain it must leave cleanup to ``prune_dead``;
        this fails closed against a delayed cleanup deleting a newly reused
        PID.
        """
        identity = _process_identity(pid)
        with _registry_write_lock(self.path):
            data = self._read()
            data["processes"][str(pid)] = {
                "pid": pid,
                "lease_id": lease_id,
                "spec_hash": spec_hash,
                "argv": list(argv),
                "registered_at": time.time(),
                "process_identity": identity,
                "dedicated_process_group": bool(dedicated_process_group),
            }
            data["schema"] = REGISTRY_SCHEMA
            _atomic_write_json(self.path, data)
        return identity

    def unregister(
        self, pid: int, *, lease_id: Optional[str] = None,
        process_identity: Optional[str] = None,
    ) -> bool:
        """Remove exactly the registration created by a known lease.

        Bare PID removal is intentionally a no-op.  It cannot distinguish a
        delayed cleanup from a new process that reused that PID.  Both the
        lease and process lifetime identity are required, so unsupported hosts
        safely retain an entry only until normal stale-record pruning.
        """
        if not lease_id or not process_identity:
            return False
        with _registry_write_lock(self.path):
            data = self._read()
            record = data["processes"].get(str(pid))
            if not isinstance(record, dict):
                return False
            if (
                record.get("lease_id") != lease_id
                or record.get("process_identity") != process_identity
            ):
                return False
            data["processes"].pop(str(pid), None)
            data["schema"] = REGISTRY_SCHEMA
            _atomic_write_json(self.path, data)
            return True

    def prune_dead(self) -> None:
        with _registry_write_lock(self.path):
            data = self._read()
            alive = {
                pid_str: record
                for pid_str, record in data["processes"].items()
                if self._record_matches_live_process(int(pid_str), record)
            }
            if alive != data["processes"]:
                data["processes"] = alive
                data["schema"] = REGISTRY_SCHEMA
                _atomic_write_json(self.path, data)

    def active(self) -> Dict[int, Dict[str, Any]]:
        self.prune_dead()
        data = self._read()
        return {int(pid_str): record for pid_str, record in data["processes"].items()}

    def active_pids(self) -> Set[int]:
        return set(self.active())

    @staticmethod
    def _record_matches_live_process(pid: int, record: Dict[str, Any]) -> bool:
        expected = record.get("process_identity")
        if not isinstance(expected, str) or not expected:
            # v1 records written before identities, and unsupported hosts,
            # must not turn a reused PID into a privileged cancellation target.
            return False
        if not _pid_alive(pid):
            return False
        return _process_identity(pid) == expected

    def terminate(self, lease_id: str, *, sig: int = getattr(signal, "SIGKILL", signal.SIGTERM)) -> Dict[str, Any]:
        """Kill the live, supervised process registered under ``lease_id``, for real.

        Looks up the pid the registry already tracks for this lease and kills its whole tree
        via :func:`kill_process_tree` -- independent of whichever thread/coroutine is currently
        blocked awaiting that process's completion (e.g. a Hub ``execute`` call in flight on a
        different connection thread). Returns a status dict rather than raising: an unknown or
        already-finished lease is a normal "nothing to cancel" outcome, not an error.
        """
        for pid, record in self.active().items():
            if record.get("lease_id") == lease_id:
                if not self._record_matches_live_process(pid, record):
                    self.unregister(
                        pid, lease_id=record.get("lease_id"),
                        process_identity=record.get("process_identity"),
                    )
                    return {"found": False, "pid": None, "lease_id": lease_id, "killed": False}
                killed = kill_process_tree(
                    pid, sig=sig, expected_identity=record.get("process_identity"),
                    dedicated_process_group=bool(record.get("dedicated_process_group")),
                )
                return {"found": True, "pid": pid, "lease_id": lease_id, "killed": killed}
        return {"found": False, "pid": None, "lease_id": lease_id, "killed": False}


def detect_unsupervised(
    registry: ProcessRegistry, *, exclude_pids: Optional[Set[int]] = None
) -> List[ProcessRecord]:
    """Diff the live host process table against the registry's bookkeeping.

    A process is flagged when its cmdline matches ``is_simplicio_cmdline`` (it looks like part
    of the Simplicio ecosystem) AND its pid is not currently registered as supervised. This is
    the detector required by #516: "process launched via a Simplicio CLI entrypoint but with no
    registered lease/PID tracked by the supervisor's own bookkeeping".
    """
    # A registry PID is only a suppression when it refers to the same kernel
    # process object that was registered.  Otherwise a recycled PID could let
    # an unrelated Simplicio process disappear from the audit.
    tracked = registry.active()
    exclude = {os.getpid()} | (exclude_pids or set())
    flagged: List[ProcessRecord] = []
    for record in scan_host_processes():
        if record.pid in exclude:
            continue
        registered = tracked.get(record.pid)
        if registered is not None:
            expected = registered.get("process_identity")
            if expected and record.process_identity == expected:
                continue
        if is_simplicio_cmdline(record.cmdline):
            flagged.append(record)
    return flagged


class SupervisedProcessAdapter:
    """Runs a ``ProcessSpec`` through ``PythonProcessAdapter`` while registering the real OS
    pid in a :class:`ProcessRegistry` for the process's lifetime -- the bookkeeping the detector
    diffs against. This is what "spawned properly through the supervisor" means operationally.
    """

    def __init__(
        self,
        *,
        registry: Optional[ProcessRegistry] = None,
        adapter: Optional[PythonProcessAdapter] = None,
    ) -> None:
        self.registry = registry or ProcessRegistry()
        self.adapter = adapter or PythonProcessAdapter()

    async def run(
        self, spec: ProcessSpec, *, lease: Optional[ProcessLease] = None
    ) -> ProcessResult:
        process_lease = lease or ProcessLease(
            lease_id=spec.idempotency_key or "lease-" + uuid.uuid4().hex,
            spec_hash=spec.spec_hash,
        )
        registered_pid: Dict[str, Any] = {}

        def _on_spawned(process: Any) -> None:
            identity = self.registry.register(
                process.pid, lease_id=process_lease.lease_id,
                spec_hash=spec.spec_hash, argv=spec.argv,
                dedicated_process_group=os.name != "nt",
            )
            registered_pid["pid"] = process.pid
            registered_pid["process_identity"] = identity

        try:
            return await self.adapter.run(spec, lease=process_lease, on_spawned=_on_spawned)
        finally:
            if "pid" in registered_pid:
                self.registry.unregister(
                    registered_pid["pid"], lease_id=process_lease.lease_id,
                    process_identity=registered_pid.get("process_identity"),
                )


def enforce(
    records: Iterable[ProcessRecord], *, enabled: bool, sig: int = signal.SIGTERM
) -> List[Dict[str, Any]]:
    """Act on flagged (unsupervised) records.

    When ``enabled`` is False (the default -- enforcement is opt-in and OFF by default) this
    ONLY observes: it reports what it *would* do without sending any signal to anything. When
    True, it only signals records carrying a scan-time identity and reports the real outcome.
    Identity-less observations (for example from macOS/BSD ``ps``) fail closed. Never called
    with ``enabled=True`` implicitly -- the CLI requires an explicit ``--enforce`` flag AND
    ``enforcement_enabled()`` to agree before this function is invoked with True.
    """
    actions: List[Dict[str, Any]] = []
    for record in records:
        if not enabled:
            actions.append({"pid": record.pid, "argv": record.cmdline, "action": "observed_only"})
            continue
        try:
            if not record.process_identity:
                raise OSError("process identity unavailable; refusing to signal numeric PID")
            if not kill_process_tree(
                record.pid, sig=sig, expected_identity=record.process_identity,
            ):
                raise OSError("unable to pin process for signaling")
            actions.append({
                "pid": record.pid, "argv": record.cmdline,
                "action": "signaled", "signal": int(sig),
            })
        except OSError as exc:
            actions.append({
                "pid": record.pid, "argv": record.cmdline,
                "action": "signal_failed", "error": str(exc),
            })
    return actions


class CircuitBreaker:
    """Trips OPEN after ``failure_threshold`` consecutive supervised-spawn failures, and moves
    to HALF_OPEN after ``cooldown_seconds`` have elapsed since the trip (a subsequent success
    closes it again). Documented trip condition (#516's "circuit breaker triggered by a
    documented condition"): ``failure_threshold`` consecutive results whose ``error_code`` is in
    ``FAILURE_ERROR_CODES`` (``spawn_error`` / ``executable_not_found``) -- i.e. repeated spawn
    failures, not ordinary non-zero exit codes from the user's own command.
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 5.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._state = "closed"
        self._tripped_at = 0.0
        self.trip_reason = ""

    @property
    def state(self) -> str:
        if self._state == "open" and (time.monotonic() - self._tripped_at) >= self.cooldown_seconds:
            self._state = "half_open"
        return self._state

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._state = "closed"
        self.trip_reason = ""

    def record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold and self._state != "open":
            self._state = "open"
            self._tripped_at = time.monotonic()
            self.trip_reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": BREAKER_SCHEMA,
            "state": self.state,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "trip_reason": self.trip_reason,
        }

    def save(self, path: Optional[Path] = None) -> None:
        payload = self.to_dict()
        payload["_consecutive_failures"] = self._consecutive_failures
        payload["_tripped_at"] = self._tripped_at
        _atomic_write_json(path or default_breaker_path(), payload)

    @classmethod
    def load(
        cls, path: Optional[Path] = None, *, failure_threshold: int = 3, cooldown_seconds: float = 5.0
    ) -> "CircuitBreaker":
        breaker = cls(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
        target = path or default_breaker_path()
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return breaker
            breaker._consecutive_failures = int(data.get("_consecutive_failures", 0))
            breaker._state = str(data.get("state", "closed"))
            breaker._tripped_at = float(data.get("_tripped_at", 0.0))
            breaker.trip_reason = str(data.get("trip_reason", ""))
        return breaker


async def run_guarded(
    spec: ProcessSpec,
    *,
    breaker: CircuitBreaker,
    supervised: Optional[SupervisedProcessAdapter] = None,
    standalone: Optional[PythonProcessAdapter] = None,
) -> Dict[str, Any]:
    """Run ``spec`` through the supervisor unless the breaker is OPEN, in which case fall back
    to a plain, unsupervised ``PythonProcessAdapter`` run -- still argv-only and spec-validated
    (never a bare shell string), just not registered/bookkept. This is the "fallback standalone"
    #516 asks the breaker to preserve: a tripped breaker degrades observability, it never stops
    work from completing.
    """
    supervised_adapter = supervised or SupervisedProcessAdapter()
    if breaker.state == "open":
        result = await (standalone or PythonProcessAdapter()).run(spec)
        return {"result": result, "mode": "standalone_fallback", "breaker": breaker.to_dict()}

    result = await supervised_adapter.run(spec)
    if result.error_code in FAILURE_ERROR_CODES:
        breaker.record_failure(result.error_code)
    else:
        breaker.record_success()
    return {"result": result, "mode": "supervised", "breaker": breaker.to_dict()}


def append_event(kind: str, payload: Dict[str, Any], *, path: Optional[Path] = None) -> Dict[str, Any]:
    """Append one JSONL event to the reports log (detector scans, enforcement actions, breaker
    trips). This is what the ``reports`` CLI subcommand reads back."""
    events_path = path or default_events_path()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event: Dict[str, Any] = {"schema": EVENT_SCHEMA, "kind": kind, "ts": time.time()}
    event.update(payload)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def read_events(*, path: Optional[Path] = None, limit: int = 50) -> List[Dict[str, Any]]:
    events_path = path or default_events_path()
    if not events_path.exists():
        return []
    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


__all__ = [
    "REGISTRY_SCHEMA",
    "EVENT_SCHEMA",
    "BREAKER_SCHEMA",
    "SIMPLICIO_SIGNATURES",
    "FAILURE_ERROR_CODES",
    "is_simplicio_cmdline",
    "default_state_dir",
    "default_registry_path",
    "default_events_path",
    "default_breaker_path",
    "enforcement_enabled",
    "ProcessRecord",
    "scan_host_processes",
    "ProcessRegistry",
    "detect_unsupervised",
    "SupervisedProcessAdapter",
    "enforce",
    "CircuitBreaker",
    "run_guarded",
    "append_event",
    "read_events",
]
