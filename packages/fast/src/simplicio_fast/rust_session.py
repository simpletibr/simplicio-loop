"""Resident client for the read-only Rust core session protocol."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Mapping


SESSION_SCHEMA = "simplicio.fast.engine-session/v1"
MAX_FRAME_BYTES = 1 * 1024 * 1024
MAX_READ_ONLY_RETRIES = 1
READ_ONLY_OPERATIONS = frozenset({"stats", "query", "relations", "context", "session_cache_stats"})


class RustSessionError(RuntimeError):
    """A Rust session failed without fabricating a response."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RustSessionError("session_payload_invalid") from error


class RustCoreSession:
    """One verified Rust child reused for read-only stats/query/context calls."""

    def __init__(
        self,
        executable: str | Path,
        expected_manifest: Mapping[str, Any] | None = None,
    ) -> None:
        self.executable = str(executable)
        self._expected_manifest = dict(expected_manifest or {})
        self._lock = threading.Lock()
        self._closed = False
        self._metrics: dict[str, int | float] = {
            "starts": 1,
            "reconnects": 0,
            "requests": 0,
            "failures": 0,
            "retries": 0,
            "bytes_in": 0,
            "bytes_out": 0,
            "wall_ms": 0.0,
            "mapped_generations": 0,
            "cache_hits": 0,
        }
        try:
            self._process = subprocess.Popen(
                [self.executable, "--session"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            handshake = self._readline()
        except (OSError, ValueError, RustSessionError) as error:
            self.close()
            raise RustSessionError(f"session_start_failed:{type(error).__name__}") from error
        try:
            self._validate_handshake(handshake, self._expected_manifest, self.executable)
        except RustSessionError:
            self.close()
            raise
        self.handshake = handshake

    @staticmethod
    def _validate_handshake(
        handshake: dict[str, Any],
        expected_manifest: Mapping[str, Any] | None = None,
        executable: str | Path | None = None,
    ) -> None:
        if not isinstance(handshake, dict):
            raise RustSessionError("session_handshake_invalid")
        if (
            handshake.get("schema") != SESSION_SCHEMA
            or handshake.get("abi") != SESSION_SCHEMA
            or handshake.get("engine") != "rust"
            or handshake.get("status") != "ready"
            or not isinstance(handshake.get("engine_version"), str)
            or not handshake["engine_version"].strip()
            or not isinstance(handshake.get("schemas"), list)
            or any(not isinstance(item, str) or not item.strip() for item in handshake["schemas"])
            or not isinstance(handshake.get("binary_digest"), str)
            or not handshake["binary_digest"].strip()
            or not isinstance(handshake.get("source_commit"), str)
            or not handshake["source_commit"].strip()
            or not isinstance(handshake.get("conformance_digest"), str)
            or not handshake["conformance_digest"].strip()
            or not isinstance(handshake.get("platform"), str)
            or not handshake["platform"].strip()
            or not isinstance(handshake.get("nonce"), str)
            or not handshake["nonce"].strip()
        ):
            raise RustSessionError("session_handshake_invalid")
        capabilities = handshake.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or any(not isinstance(item, str) or not item.strip() for item in capabilities)
            or not READ_ONLY_OPERATIONS.issubset(capabilities)
        ):
            raise RustSessionError("session_capabilities_invalid")
        expected = dict(expected_manifest or {})
        expected_version = expected.get("version")
        if isinstance(expected_version, str) and handshake["engine_version"] != expected_version:
            raise RustSessionError("session_version_mismatch")
        expected_commit = expected.get("source_commit")
        conformance = expected.get("conformance")
        if isinstance(conformance, Mapping):
            expected_commit = conformance.get("source_commit", expected_commit)
            expected_conformance = conformance.get("digest")
            if (
                isinstance(expected_conformance, str)
                and handshake["conformance_digest"] != expected_conformance
            ):
                raise RustSessionError("session_conformance_mismatch")
        if isinstance(expected_commit, str) and handshake["source_commit"] != expected_commit:
            raise RustSessionError("session_source_commit_mismatch")
        expected_digest = expected.get("sha256")
        if isinstance(conformance, Mapping):
            engine_digests = conformance.get("engine_sha256")
            if isinstance(engine_digests, Mapping):
                expected_digest = engine_digests.get("rust", expected_digest)
        if isinstance(expected_digest, str) and executable is not None:
            try:
                actual = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
            except OSError as error:
                raise RustSessionError("session_binary_unreadable") from error
            normalized = expected_digest.removeprefix("sha256:")
            if normalized != actual or handshake["binary_digest"] != f"sha256:{actual}":
                raise RustSessionError("session_binary_digest_mismatch")

    def _readline(self) -> dict[str, Any]:
        line = self._process.stdout.readline() if self._process.stdout else ""
        if not line or len(line.encode("utf-8")) > MAX_FRAME_BYTES:
            raise RustSessionError("session_frame_invalid")
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RustSessionError("session_frame_invalid") from error
        if not isinstance(value, dict):
            raise RustSessionError("session_frame_invalid")
        return value

    def call(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.closed:
            raise RustSessionError("session_closed")
        if not isinstance(operation, str) or operation not in READ_ONLY_OPERATIONS:
            raise RustSessionError("session_operation_invalid")
        if not isinstance(payload, Mapping):
            raise RustSessionError("session_payload_invalid")
        frame = _canonical({"operation": operation, "payload": dict(payload)})
        if len(frame.encode("utf-8")) > MAX_FRAME_BYTES:
            raise RustSessionError("session_frame_too_large")
        started = time.perf_counter()
        with self._lock:
            for attempt in range(MAX_READ_ONLY_RETRIES + 1):
                try:
                    response = self._call_once_locked(frame)
                except RustSessionError as error:
                    retryable = (
                        str(error) == "session_crashed"
                        and operation in READ_ONLY_OPERATIONS
                        and attempt < MAX_READ_ONLY_RETRIES
                    )
                    if not retryable:
                        raise
                    self._metrics["retries"] += 1
                    self._restart_locked()
                else:
                    break
            self._metrics["wall_ms"] += (time.perf_counter() - started) * 1000
        if response.get("ok") is not True:
            self._metrics["failures"] += 1
            raise RustSessionError(str(response.get("reason") or "session_request_failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RustSessionError("session_result_invalid")
        if operation == "session_cache_stats":
            snapshots = result.get("snapshots")
            if isinstance(snapshots, int) and snapshots >= 0:
                self._metrics["mapped_generations"] = snapshots
                if snapshots:
                    self._metrics["cache_hits"] += 1
        return result

    def _call_once_locked(self, frame: str) -> dict[str, Any]:
        self._metrics["bytes_in"] += len(frame.encode("utf-8")) + 1
        if self._process.poll() is not None:
            self._metrics["failures"] += 1
            raise RustSessionError("session_crashed")
        try:
            if self._process.stdin is None:
                raise RustSessionError("session_stdin_missing")
            self._process.stdin.write(frame + "\n")
            self._process.stdin.flush()
            response = self._readline()
        except (BrokenPipeError, OSError, RustSessionError) as error:
            self._metrics["failures"] += 1
            raise RustSessionError("session_crashed") from error
        self._metrics["requests"] += 1
        self._metrics["bytes_out"] += len(_canonical(response)) + 1
        return response

    def metrics(self) -> dict[str, int | float]:
        """Return resident-session request counters for benchmark receipts."""
        with self._lock:
            return dict(self._metrics)

    def restart(self) -> None:
        """Restart the child and require a fresh verified handshake."""
        with self._lock:
            self._restart_locked()

    def _restart_locked(self) -> None:
        self.close()
        self._closed = False
        try:
            self._process = subprocess.Popen(
                [self.executable, "--session"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            handshake = self._readline()
            self._validate_handshake(
                handshake, self._expected_manifest, self.executable
            )
        except (OSError, ValueError, RustSessionError) as error:
            self._metrics["failures"] += 1
            self.close()
            raise RustSessionError(
                f"session_restart_failed:{type(error).__name__}"
            ) from error
        self.handshake = handshake
        self._metrics["starts"] += 1
        self._metrics["reconnects"] += 1

    def close(self) -> None:
        self._closed = True
        process = getattr(self, "_process", None)
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=2)

    @property
    def closed(self) -> bool:
        return bool(getattr(self, "_closed", False))

    def __enter__(self) -> "RustCoreSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = [
    "MAX_FRAME_BYTES",
    "MAX_READ_ONLY_RETRIES",
    "READ_ONLY_OPERATIONS",
    "RustCoreSession",
    "RustSessionError",
    "SESSION_SCHEMA",
]
