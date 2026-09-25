"""Safe Python process specification, leases, and async adapter."""

import asyncio
import hashlib
import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple


PROCESS_SPEC_SCHEMA = "simplicio.process-spec/v1"
PROCESS_RESULT_SCHEMA = "simplicio.process-result/v1"


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ProcessSpecError(ValueError):
    """Raised when a process specification is unsafe or incomplete."""


@dataclass(frozen=True)
class ProcessSpec:
    """Structured argv-only process contract."""

    argv: Tuple[str, ...]
    cwd: Optional[str] = None
    cwd_allowlist: Tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    env_allowlist: Tuple[str, ...] = ()
    timeout_seconds: Optional[float] = 30.0
    max_output_bytes: int = 65536
    priority: int = 0
    idempotency_key: str = ""
    shell: bool = False

    def __post_init__(self) -> None:
        argv = tuple(str(value) for value in self.argv)
        if not argv or any(not value for value in argv):
            raise ProcessSpecError("argv must contain a non-empty executable")
        if self.shell:
            raise ProcessSpecError("shell execution is forbidden")
        cwd_allowlist = tuple(
            str(Path(str(root)).resolve()) for root in self.cwd_allowlist
        )
        if self.cwd is not None:
            if not Path(self.cwd).is_absolute():
                raise ProcessSpecError("cwd must be absolute")
            if cwd_allowlist:
                resolved_cwd = Path(self.cwd).resolve()
                allowed = any(
                    resolved_cwd == Path(root) or Path(root) in resolved_cwd.parents
                    for root in cwd_allowlist
                )
                if not allowed:
                    raise ProcessSpecError(
                        "cwd escapes the allowed roots (cwd_allowlist)"
                    )
        object.__setattr__(self, "cwd_allowlist", cwd_allowlist)
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ProcessSpecError("timeout_seconds must be positive")
        if self.max_output_bytes < 1:
            raise ProcessSpecError("max_output_bytes must be positive")
        if self.priority < 0:
            raise ProcessSpecError("priority cannot be negative")
        allowlist = tuple(sorted({str(key) for key in self.env_allowlist}))
        env = {str(key): str(value) for key, value in self.env.items()}
        if any(key not in allowlist for key in env):
            raise ProcessSpecError("env contains a key outside env_allowlist")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "env_allowlist", allowlist)
        object.__setattr__(self, "env", env)

    @property
    def spec_hash(self) -> str:
        return _hash({
            "argv": self.argv,
            "cwd": self.cwd,
            "cwd_allowlist": self.cwd_allowlist,
            "env": dict(self.env),
            "env_allowlist": self.env_allowlist,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "priority": self.priority,
            "idempotency_key": self.idempotency_key,
        })

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": PROCESS_SPEC_SCHEMA,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "cwd_allowlist": list(self.cwd_allowlist),
            "env": dict(self.env),
            "env_allowlist": list(self.env_allowlist),
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "priority": self.priority,
            "idempotency_key": self.idempotency_key,
            "shell": False,
            "spec_hash": self.spec_hash,
        }


@dataclass
class ProcessLease:
    """Renewable lease that can be cancelled and expires deterministically."""

    lease_id: str
    spec_hash: str
    ttl_seconds: float = 30.0
    expires_at: float = 0.0
    state: str = "active"

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ProcessSpecError("lease ttl must be positive")
        if not self.expires_at:
            self.expires_at = time.monotonic() + self.ttl_seconds

    def heartbeat(self, *, now: Optional[float] = None) -> float:
        if self.state != "active":
            return self.expires_at
        current = time.monotonic() if now is None else float(now)
        self.expires_at = current + self.ttl_seconds
        return self.expires_at

    def expired(self, *, now: Optional[float] = None) -> bool:
        current = time.monotonic() if now is None else float(now)
        if self.state == "active" and current >= self.expires_at:
            self.state = "expired"
        return self.state == "expired"

    def cancel(self) -> None:
        self.state = "cancelled"


@dataclass(frozen=True)
class ProcessResult:
    """Bounded, classified process outcome."""

    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False
    error_code: str = ""
    lease_id: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema": PROCESS_RESULT_SCHEMA,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "truncated": self.truncated,
            "error_code": self.error_code,
            "lease_id": self.lease_id,
        }


class PythonProcessAdapter:
    """Run ProcessSpec with asyncio.create_subprocess_exec and shell=False."""

    @staticmethod
    def _environment(spec: ProcessSpec) -> Dict[str, str]:
        environment = {
            key: os.environ[key]
            for key in spec.env_allowlist
            if key in os.environ
        }
        environment.update(spec.env)
        return environment

    @staticmethod
    def _bounded(raw: bytes, limit: int) -> Tuple[str, bool]:
        truncated = len(raw) > limit
        return raw[:limit].decode("utf-8", errors="replace"), truncated

    @staticmethod
    def _kill_tree(process: "asyncio.subprocess.Process") -> None:
        """Kill a supervised process and its complete descendant tree."""
        if process.pid is None:
            return
        if os.name == "nt":
            try:
                import subprocess
                completed = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False, timeout=10,
                )
                if completed.returncode == 0:
                    return
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return
        except (AttributeError, ProcessLookupError, PermissionError, OSError):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            pass

    @staticmethod
    async def _reap_after_kill(process: "asyncio.subprocess.Process") -> Tuple[bytes, bytes]:
        """Bound cleanup after STOP/deadline so a failed tree kill cannot hang the caller."""
        try:
            return await asyncio.wait_for(process.communicate(), timeout=10)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return b"", b""
    async def run(
        self,
        spec: ProcessSpec,
        *,
        lease: Optional[ProcessLease] = None,
        on_spawned: Optional[Callable[["asyncio.subprocess.Process"], None]] = None,
    ) -> ProcessResult:
        """Run ``spec`` to completion.

        ``on_spawned`` is an optional additive hook (issue #516) invoked synchronously with the
        live ``asyncio.subprocess.Process`` immediately after a successful spawn, before this
        coroutine awaits completion -- the only point at which the real OS pid is known. It
        exists so an external bookkeeping layer (a process registry) can record "this pid is
        supervised" without this adapter needing to know anything about that layer. A raising
        hook must never take down the supervised child, so exceptions from it are swallowed.
        """
        started = time.monotonic()
        lease_id = lease.lease_id if lease else ""
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=spec.cwd,
                env=self._environment(spec),
                stdin=asyncio.subprocess.DEVNULL,
                shell=False,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name != "nt",
            )
            if on_spawned is not None:
                try:
                    on_spawned(process)
                except Exception:
                    pass
            communicate = process.communicate()
            if spec.timeout_seconds is None:
                stdout, stderr = await communicate
            else:
                stdout, stderr = await asyncio.wait_for(
                    communicate, timeout=spec.timeout_seconds
                )
            out, out_truncated = self._bounded(stdout or b"", spec.max_output_bytes)
            err, err_truncated = self._bounded(stderr or b"", spec.max_output_bytes)
            return ProcessResult(
                process.returncode,
                out,
                err,
                time.monotonic() - started,
                truncated=out_truncated or err_truncated,
                lease_id=lease_id,
            )
        except asyncio.TimeoutError:
            if process is not None:
                self._kill_tree(process)
                stdout, stderr = await self._reap_after_kill(process)
                out, out_truncated = self._bounded(stdout or b"", spec.max_output_bytes)
                err, err_truncated = self._bounded(stderr or b"", spec.max_output_bytes)
            else:
                out, err, out_truncated, err_truncated = "", "", False, False
            return ProcessResult(
                process.returncode if process is not None else None,
                out,
                err,
                time.monotonic() - started,
                timed_out=True,
                truncated=out_truncated or err_truncated,
                error_code="deadline_exceeded",
                lease_id=lease_id,
            )
        except asyncio.CancelledError:
            if process is not None:
                self._kill_tree(process)
                await self._reap_after_kill(process)
            return ProcessResult(
                process.returncode if process is not None else None,
                duration_seconds=time.monotonic() - started,
                cancelled=True,
                error_code="cancelled",
                lease_id=lease_id,
            )
        except OSError as exc:
            code = "executable_not_found" if isinstance(exc, FileNotFoundError) else "spawn_error"
            return ProcessResult(
                None,
                duration_seconds=time.monotonic() - started,
                error_code=code,
                lease_id=lease_id,
            )


def run_sync(
    spec: ProcessSpec,
    *,
    on_spawned: Optional[Callable[["asyncio.subprocess.Process"], None]] = None,
) -> ProcessResult:
    """Run ``spec`` to completion through the pure-Python adapter, synchronously.

    Single entrypoint for callers (e.g. ``HubDaemon.handle``) that are not themselves async.
    There is no other backend: the previous optional Rust/Tokio supervisor
    (``rust/simplicio-supervisor``) was removed (#1298, 100% Python) along with its adapter
    module; this pure-Python path is unconditional.
    """
    return asyncio.run(PythonProcessAdapter().run(spec, on_spawned=on_spawned))


def backend_name() -> str:
    return "python"
