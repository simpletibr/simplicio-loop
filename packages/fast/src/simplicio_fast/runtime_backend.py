"""Narrow, verified adapter from Fast to the Rust engine owned by Runtime."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

HBP_SCHEMA = "simplicio.hbp/v1"
RUNTIME_FAST_ABI = "simplicio.runtime.fast/v1"
SELECTION_SCHEMA = "simplicio.fast.runtime-selection/v1"
HANDSHAKE_SCHEMA = "simplicio.fast.runtime-handshake/v1"
SUPPORTED_MODES = frozenset({"auto", "rust", "python", "off"})
SUPPORTED_PLATFORMS = frozenset(
    {"linux-x86_64", "linux-aarch64", "macos-aarch64", "windows-x86_64"}
)
READ_ONLY_OPERATIONS = frozenset(
    {"sha256", "catalog_lookup", "page", "overlay_merge", "stats", "query", "context"}
)
REASON_CODES = frozenset(
    {
        "RUNTIME_MISSING",
        "ABI_MISMATCH",
        "VERSION_MISMATCH",
        "PLATFORM_UNSUPPORTED",
        "HASH_MISMATCH",
        "SIGNATURE_MISMATCH",
        "RUNTIME_UNHEALTHY",
        "PROTOCOL_ERROR",
        "TIMEOUT",
        "CANCELLED",
        "DISABLED",
    }
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path, *, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            if size > max_bytes:
                raise RuntimeBackendError(
                    "HASH_MISMATCH", f"artifact exceeds {max_bytes} bytes"
                )
            digest.update(block)
    return digest.hexdigest(), size


def platform_tag(
    *, system: str | None = None, machine: str | None = None
) -> str | None:
    current_system = (system or platform.system()).lower()
    current_machine = (machine or platform.machine()).lower()
    aliases = {
        ("linux", "x86_64"): "linux-x86_64",
        ("linux", "amd64"): "linux-x86_64",
        ("linux", "aarch64"): "linux-aarch64",
        ("linux", "arm64"): "linux-aarch64",
        ("darwin", "arm64"): "macos-aarch64",
        ("windows", "amd64"): "windows-x86_64",
        ("windows", "x86_64"): "windows-x86_64",
    }
    return aliases.get((current_system, current_machine))


class RuntimeBackendError(RuntimeError):
    """A stable, machine-readable Runtime admission or invocation failure."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in REASON_CODES:
            reason_code = "PROTOCOL_ERROR"
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    executable: Path
    sha256: str
    version: str
    platform: str
    abi: str = RUNTIME_FAST_ABI
    source_commit: str | None = None
    signature: str | None = None
    signature_required: bool = False
    size: int | None = None

    @classmethod
    def from_manifest(
        cls, executable: str | Path, manifest: Mapping[str, Any]
    ) -> "RuntimeArtifact":
        runtime = manifest.get("runtime")
        runtime_data = runtime if isinstance(runtime, Mapping) else {}
        return cls(
            executable=Path(executable),
            sha256=str(manifest.get("sha256", "")),
            version=str(manifest.get("version") or runtime_data.get("version") or ""),
            platform=str(manifest.get("platform") or runtime_data.get("target") or ""),
            # The ABI must be asserted by the signed/released manifest.  A
            # compatibility caller must never turn an arbitrary executable
            # into a Runtime artifact by relying on an implicit default.
            abi=str(manifest.get("abi") or ""),
            source_commit=(
                str(manifest.get("source_commit") or runtime_data.get("commit"))
                if manifest.get("source_commit") or runtime_data.get("commit")
                else None
            ),
            signature=(
                str(manifest["signature"]) if manifest.get("signature") else None
            ),
            signature_required=bool(manifest.get("signature_required", False)),
            size=(
                int(manifest["size"]) if isinstance(manifest.get("size"), int) else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RuntimeHandshake:
    version: str
    platform: str
    abi: str
    capabilities: tuple[str, ...]
    conformance_digest: str
    artifact_sha256: str
    source_commit: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": HANDSHAKE_SCHEMA,
            "runtime": "simplicio-runtime",
            "version": self.version,
            "platform": self.platform,
            "abi": self.abi,
            "capabilities": list(self.capabilities),
            "conformance_digest": self.conformance_digest,
            "artifact_sha256": self.artifact_sha256,
            "source_commit": self.source_commit,
            "healthy": True,
        }


SignatureVerifier = Callable[[Path, str, str], bool]


class RuntimeFastBackend:
    """Verified HBP stdio bridge to Runtime's read-only Fast capability."""

    name = "rust"

    def __init__(
        self,
        artifact: RuntimeArtifact,
        *,
        launcher: Sequence[str] = (),
        required_capabilities: Sequence[str] = tuple(READ_ONLY_OPERATIONS),
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 4 * 1024 * 1024,
        max_artifact_bytes: int = 256 * 1024 * 1024,
        signature_verifier: SignatureVerifier | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
        if max_artifact_bytes < 1024:
            raise ValueError("max_artifact_bytes must be at least 1024")
        self.artifact = artifact
        self.launcher = tuple(launcher)
        self.required_capabilities = frozenset(required_capabilities)
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_artifact_bytes = max_artifact_bytes
        self.signature_verifier = signature_verifier
        self._handshake: RuntimeHandshake | None = None

    @property
    def command(self) -> list[str]:
        return [
            *self.launcher,
            str(self.artifact.executable),
            "fast-backend",
            "--stdio",
        ]

    def verify_artifact(self, *, current_platform: str | None = None) -> dict[str, Any]:
        path = self.artifact.executable
        if not path.is_file():
            raise RuntimeBackendError("RUNTIME_MISSING", str(path))
        expected_platform = current_platform or platform_tag()
        if (
            expected_platform not in SUPPORTED_PLATFORMS
            or self.artifact.platform != expected_platform
        ):
            raise RuntimeBackendError(
                "PLATFORM_UNSUPPORTED",
                f"artifact={self.artifact.platform} host={expected_platform}",
            )
        if self.artifact.abi != RUNTIME_FAST_ABI:
            raise RuntimeBackendError("ABI_MISMATCH", self.artifact.abi)
        if not self.artifact.version:
            raise RuntimeBackendError("VERSION_MISMATCH", "manifest version missing")
        try:
            actual_hash, actual_size = _file_sha256(
                path, max_bytes=self.max_artifact_bytes
            )
        except OSError as error:
            raise RuntimeBackendError(
                "RUNTIME_MISSING", type(error).__name__
            ) from error
        if self.artifact.size is not None and actual_size != self.artifact.size:
            raise RuntimeBackendError(
                "HASH_MISMATCH",
                f"size manifest={self.artifact.size} actual={actual_size}",
            )
        if len(self.artifact.sha256) != 64 or not hmac.compare_digest(
            actual_hash, self.artifact.sha256
        ):
            raise RuntimeBackendError("HASH_MISMATCH", actual_hash)
        if self.artifact.signature_required and not self.artifact.signature:
            raise RuntimeBackendError("SIGNATURE_MISMATCH", "signature missing")
        if self.artifact.signature:
            verifier = self.signature_verifier
            if verifier is None or not verifier(
                path, actual_hash, self.artifact.signature
            ):
                raise RuntimeBackendError("SIGNATURE_MISMATCH", "verification failed")
        return {
            "artifact_sha256": actual_hash,
            "artifact_size": actual_size,
            "artifact_version": self.artifact.version,
            "artifact_platform": self.artifact.platform,
            "artifact_abi": self.artifact.abi,
            "source_commit": self.artifact.source_commit,
            "signature_verified": bool(self.artifact.signature),
        }

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def _request(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        if operation != "doctor" and operation not in READ_ONLY_OPERATIONS:
            raise RuntimeBackendError("PROTOCOL_ERROR", f"operation={operation}")
        immutable_payload = json.loads(_canonical(payload))
        request_body = {
            "schema": HBP_SCHEMA,
            "abi": RUNTIME_FAST_ABI,
            "operation": operation,
            "payload": immutable_payload,
        }
        request_id = _sha256(_canonical(request_body))
        request = _canonical({**request_body, "request_id": request_id})
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeBackendError("CANCELLED", "before spawn")
        started = time.monotonic()
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                # Windows forbids close_fds=True while redirecting stdio.
                process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=(os.name != "nt"),
                )
                assert process.stdin is not None
                process.stdin.write(request)
                process.stdin.close()
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.wait(0.01):
                        self._stop(process)
                        raise RuntimeBackendError("CANCELLED", operation)
                    if time.monotonic() - started >= self.timeout_seconds:
                        self._stop(process)
                        raise RuntimeBackendError("TIMEOUT", operation)
                    time.sleep(0.005)
                stdout.seek(0)
                raw = stdout.read(self.max_response_bytes + 1)
                stderr.seek(0)
                error_text = stderr.read(4096).decode("utf-8", errors="replace")
        except RuntimeBackendError:
            raise
        except OSError as error:
            raise RuntimeBackendError(
                "RUNTIME_UNHEALTHY", type(error).__name__
            ) from error
        if process.returncode != 0:
            raise RuntimeBackendError(
                "RUNTIME_UNHEALTHY",
                f"exit={process.returncode} stderr={error_text[:160]}",
            )
        if len(raw) > self.max_response_bytes:
            raise RuntimeBackendError("PROTOCOL_ERROR", "response too large")
        try:
            response = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeBackendError("PROTOCOL_ERROR", "invalid JSON") from error
        if not isinstance(response, dict):
            raise RuntimeBackendError("PROTOCOL_ERROR", "response is not an object")
        if (
            response.get("schema") != HBP_SCHEMA
            or response.get("abi") != RUNTIME_FAST_ABI
            or response.get("request_id") != request_id
            or not isinstance(response.get("ok"), bool)
        ):
            raise RuntimeBackendError("PROTOCOL_ERROR", "envelope mismatch")
        if response["ok"] is not True:
            reason = str(response.get("reason_code", "PROTOCOL_ERROR"))
            detail = str(response.get("detail", "runtime rejected request"))
            raise RuntimeBackendError(reason, detail)
        if "result" not in response:
            raise RuntimeBackendError("PROTOCOL_ERROR", "result missing")
        return response["result"]

    def handshake(
        self, *, cancel_event: threading.Event | None = None
    ) -> RuntimeHandshake:
        artifact_receipt = self.verify_artifact()
        result = self._request("doctor", {}, cancel_event=cancel_event)
        if not isinstance(result, dict):
            raise RuntimeBackendError(
                "PROTOCOL_ERROR", "doctor result is not an object"
            )
        if (
            result.get("runtime") != "simplicio-runtime"
            or result.get("healthy") is not True
        ):
            raise RuntimeBackendError("RUNTIME_UNHEALTHY", "doctor did not pass")
        if result.get("abi") != RUNTIME_FAST_ABI:
            raise RuntimeBackendError("ABI_MISMATCH", str(result.get("abi")))
        if result.get("version") != self.artifact.version:
            raise RuntimeBackendError(
                "VERSION_MISMATCH",
                f"manifest={self.artifact.version} runtime={result.get('version')}",
            )
        if result.get("platform") != self.artifact.platform:
            raise RuntimeBackendError(
                "PLATFORM_UNSUPPORTED", str(result.get("platform"))
            )
        raw_capabilities = result.get("capabilities")
        if not isinstance(raw_capabilities, list) or any(
            not isinstance(item, str) for item in raw_capabilities
        ):
            raise RuntimeBackendError("PROTOCOL_ERROR", "capabilities invalid")
        capabilities = frozenset(raw_capabilities)
        missing = sorted(self.required_capabilities.difference(capabilities))
        if missing:
            raise RuntimeBackendError(
                "RUNTIME_UNHEALTHY", f"capabilities missing: {','.join(missing)}"
            )
        conformance = result.get("conformance")
        digest = conformance.get("digest") if isinstance(conformance, dict) else None
        if (
            not isinstance(conformance, dict)
            or conformance.get("passed") is not True
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise RuntimeBackendError("RUNTIME_UNHEALTHY", "conformance missing")
        self._handshake = RuntimeHandshake(
            version=self.artifact.version,
            platform=self.artifact.platform,
            abi=RUNTIME_FAST_ABI,
            capabilities=tuple(sorted(capabilities)),
            conformance_digest=digest,
            artifact_sha256=artifact_receipt["artifact_sha256"],
            source_commit=self.artifact.source_commit,
        )
        return self._handshake

    def call(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        if self._handshake is None:
            self.handshake(cancel_event=cancel_event)
        assert self._handshake is not None
        if operation not in self._handshake.capabilities:
            raise RuntimeBackendError("RUNTIME_UNHEALTHY", f"unsupported={operation}")
        return self._request(operation, payload, cancel_event=cancel_event)


@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    requested: str
    selected: str
    reason_code: str | None
    backend: RuntimeFastBackend | None = field(default=None, repr=False)
    handshake: RuntimeHandshake | None = field(default=None, repr=False)

    def receipt(self) -> dict[str, Any]:
        handshake = self.handshake.to_dict() if self.handshake else None
        return {
            "schema": SELECTION_SCHEMA,
            "requested_engine": self.requested,
            "selected_engine": self.selected,
            "usable": self.selected != "off",
            "reason_code": self.reason_code,
            "backend": "rust" if self.selected == "rust" else self.selected,
            "backend_artifact_hash": (
                handshake["artifact_sha256"] if handshake else None
            ),
            "abi": handshake["abi"] if handshake else None,
            "runtime_version": handshake["version"] if handshake else None,
            "runtime_platform": handshake["platform"] if handshake else None,
            "runtime_source_commit": (
                handshake["source_commit"] if handshake else None
            ),
            "conformance_digest": (
                handshake["conformance_digest"] if handshake else None
            ),
            "python_hot_path_loaded": False if self.selected == "rust" else None,
        }

    def execute(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        if self.selected == "rust":
            assert self.backend is not None
            return self.backend.call(operation, payload, cancel_event=cancel_event)
        if self.selected == "off":
            raise RuntimeBackendError("DISABLED", "acceleration disabled")
        from .native_backend import PythonBackend, execute_with_fallback

        result, _, _ = execute_with_fallback(PythonBackend(), operation, payload)
        return result


def runtime_artifact_from_environment(
    environment: Mapping[str, str] | None = None,
) -> RuntimeArtifact | None:
    env = os.environ if environment is None else environment
    executable = env.get("SIMPLICIO_RUNTIME_BIN")
    manifest_path = env.get("SIMPLICIO_RUNTIME_MANIFEST")
    if not executable or not manifest_path:
        return None
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    return RuntimeArtifact.from_manifest(executable, manifest)


def select_runtime_backend(
    mode: str = "auto",
    *,
    artifact: RuntimeArtifact | None = None,
    launcher: Sequence[str] = (),
    required_capabilities: Sequence[str] = tuple(READ_ONLY_OPERATIONS),
    timeout_seconds: float = 5.0,
    cancel_event: threading.Event | None = None,
    signature_verifier: SignatureVerifier | None = None,
) -> RuntimeSelection:
    requested = str(mode or "auto").strip().lower()
    if requested not in SUPPORTED_MODES:
        raise ValueError(f"unsupported Runtime Fast mode: {mode}")
    if requested == "off":
        return RuntimeSelection(requested, "off", "DISABLED")
    if requested == "python":
        return RuntimeSelection(requested, "python", None)
    candidate = artifact or runtime_artifact_from_environment()
    if candidate is None:
        if requested == "rust":
            raise RuntimeBackendError(
                "RUNTIME_MISSING", "verified manifest unavailable"
            )
        return RuntimeSelection(requested, "python", "RUNTIME_MISSING")
    backend = RuntimeFastBackend(
        candidate,
        launcher=launcher,
        required_capabilities=required_capabilities,
        timeout_seconds=timeout_seconds,
        signature_verifier=signature_verifier,
    )
    try:
        handshake = backend.handshake(cancel_event=cancel_event)
    except RuntimeBackendError as error:
        if requested == "rust":
            raise
        return RuntimeSelection(requested, "python", error.reason_code)
    return RuntimeSelection(requested, "rust", None, backend, handshake)


__all__ = [
    "HANDSHAKE_SCHEMA",
    "HBP_SCHEMA",
    "READ_ONLY_OPERATIONS",
    "REASON_CODES",
    "RUNTIME_FAST_ABI",
    "RuntimeArtifact",
    "RuntimeBackendError",
    "RuntimeFastBackend",
    "RuntimeHandshake",
    "RuntimeSelection",
    "platform_tag",
    "runtime_artifact_from_environment",
    "select_runtime_backend",
]
