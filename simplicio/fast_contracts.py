"""Optional Simplicio Fast capability negotiation and diagnostics."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

FAST_DISTRIBUTION = "simplicio-fast"
FAST_MODULE = "simplicio_fast"
FAST_MIN_VERSION = (2, 0, 18)
FAST_MAX_MAJOR = 3
CAPABILITIES_SCHEMA = "simplicio.fast-capabilities/v1"
DOCTOR_SCHEMA = "simplicio.fast-doctor/v1"
RECEIPT_SCHEMA = "simplicio.fast-local-receipt/v1"
SNAPSHOT_SCHEMAS = ("simplicio.context-snapshot/v1", "simplicio.mapper-context-snapshot/v1")
BINARY_CHANGESET_SCHEMA = "simplicio.fast.binary-changeset/v1"


class FastEngineError(RuntimeError):
    """A requested Fast engine cannot satisfy the negotiated contract."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class FastEngineMetrics:
    """Counters attached to one engine instance, not global process state."""

    decode_calls: int = 0
    bytes_decoded: int = 0
    serializations: int = 0
    subprocesses: int = 0
    refresh_calls: int = 0
    refresh_pending: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "decode_calls": self.decode_calls,
            "bytes_decoded": self.bytes_decoded,
            "serializations": self.serializations,
            "subprocesses": self.subprocesses,
            "refresh_calls": self.refresh_calls,
            "refresh_pending": self.refresh_pending,
        }


class FastEngine(ABC):
    """In-memory changeset adapter selected once before mutation admission."""

    name: str

    def __init__(self) -> None:
        self.metrics = FastEngineMetrics()

    @abstractmethod
    def decode_binary(self, payload: bytes) -> dict[str, Any]:
        raise NotImplementedError

    def receipt(self) -> dict[str, Any]:
        return {"name": self.name, "metrics": self.metrics.to_dict()}

    def validate_generation(self, envelope: Mapping[str, Any], current: str | None = None) -> str:
        """Validate the immutable generation before an effect is admitted."""

        generation = envelope.get("generation") or envelope.get("base_generation")
        if not isinstance(generation, str) or not generation:
            raise FastEngineError("invalid_generation", "changeset generation must be a non-empty string")
        if current is not None and generation != str(current):
            raise FastEngineError(
                "stale_generation",
                "changeset generation does not match the current generation",
            )
        return generation

    def changed_paths(self, envelope: Mapping[str, Any]) -> tuple[str, ...]:
        """Extract the deduplicated path surface without serializing the envelope."""

        candidates: list[str] = []
        for raw in envelope.get("touched_files", envelope.get("allowlist", ())) or ():
            if isinstance(raw, str) and raw.strip():
                candidates.append(raw.replace("\\", "/"))
        operations = envelope.get("operations", ())
        if isinstance(operations, list):
            for operation in operations:
                if not isinstance(operation, Mapping):
                    continue
                for key in ("path", "source", "dest", "target"):
                    value = operation.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(value.replace("\\", "/"))
        return tuple(dict.fromkeys(candidates))

    def refresh(
        self,
        paths: Iterable[str],
        *,
        refresh_fn: Callable[[tuple[str, ...]], Any] | None = None,
    ) -> dict[str, Any]:
        """Refresh only admitted paths; missing/failing producers stay pending."""

        selected = tuple(dict.fromkeys(str(path).replace("\\", "/") for path in paths if str(path)))
        self.metrics.refresh_calls += 1
        if refresh_fn is None:
            self.metrics.refresh_pending += 1
            return {
                "status": "REFRESH_PENDING",
                "paths": list(selected),
                "reason": "refresh_callback_required",
            }
        try:
            result = refresh_fn(selected)
        except Exception as exc:  # producer boundary: pending is safer than retrying effects
            self.metrics.refresh_pending += 1
            return {
                "status": "REFRESH_PENDING",
                "paths": list(selected),
                "reason": "refresh_failed",
                "error_type": type(exc).__name__,
            }
        return {"status": "refreshed", "paths": list(selected), "result": result}


class RustFastEngine(FastEngine):
    name = "rust"

    def __init__(self, decoder: Any) -> None:
        super().__init__()
        self._decoder = decoder

    def decode_binary(self, payload: bytes) -> dict[str, Any]:
        self.metrics.decode_calls += 1
        self.metrics.bytes_decoded += len(payload)
        decoded = self._decoder(payload)
        if hasattr(decoded, "to_dict"):
            decoded = decoded.to_dict()
        if not isinstance(decoded, dict):
            raise FastEngineError("binary_decode_shape", "Fast decoder returned a non-object envelope")
        return decoded


class PythonFastEngine(FastEngine):
    """In-memory adapter using the Fast project's Python binary decoder."""

    name = "python"

    def decode_binary(self, payload: bytes) -> dict[str, Any]:
        self.metrics.decode_calls += 1
        self.metrics.bytes_decoded += len(payload)
        try:
            from simplicio_fast.binary_changeset import decode_binary
        except (ImportError, ModuleNotFoundError) as exc:
            raise FastEngineError(
                "python_decoder_unavailable", "Fast Python binary decoder is not installed"
            ) from exc
        try:
            decoded = decode_binary(payload)
        except Exception as exc:
            raise FastEngineError(
                "python_decode_failed", "Python Fast decoder rejected the envelope"
            ) from exc
        if hasattr(decoded, "to_dict"):
            decoded = decoded.to_dict()
        if not isinstance(decoded, dict):
            raise FastEngineError("binary_decode_shape", "Python Fast decoder returned a non-object envelope")
        return decoded


class NoFastEngine(FastEngine):
    name = "none"

    def decode_binary(self, payload: bytes) -> dict[str, Any]:
        del payload
        raise FastEngineError("fast_unavailable", "no compatible Fast binary decoder is installed")


def select_fast_engine(preference: str = "auto") -> FastEngine:
    """Select the decoder once without labelling Python as Rust."""
    requested = preference.strip().lower()
    if requested not in {"auto", "rust", "python", "none"}:
        raise FastEngineError("fast_engine_invalid", "fast engine must be auto, rust, python, or none")
    preflight = fast_preflight()
    if requested == "none":
        return NoFastEngine()
    if requested == "python":
        return PythonFastEngine()
    try:
        importlib.import_module("simplicio_fast.binary_changeset")
    except (ImportError, ModuleNotFoundError) as exc:
        if requested == "rust":
            raise FastEngineError("fast_rust_unavailable", "Rust Fast decoder is not installed") from exc
        return NoFastEngine()
    if requested == "rust":
        raise FastEngineError(
            "fast_rust_unavailable",
            "the installed Fast binary changeset decoder is Python; Rust parity is unavailable",
        )
    # Importability is sufficient for the explicit Python/reference lane.
    # Never wrap this decoder in RustFastEngine: the receipt is evidence and
    # must identify the actual implementation that consumed the bytes.
    if preflight.status in {"ready", "absent", "degraded"}:
        return PythonFastEngine()
    return NoFastEngine()


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    parts: list[int] = []
    for token in value.split("+", 1)[0].split(".", 3)[:3]:
        digits = "".join(character for character in token if character.isdigit())
        if not digits:
            return None
        parts.append(int(digits))
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _installed_version(distribution: str, env_name: str) -> str | None:
    override = os.environ.get(env_name)
    if override is not None:
        return override or None
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _module_available(module: str, env_name: str) -> bool:
    override = os.environ.get(env_name)
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "ready"}
    return importlib.util.find_spec(module) is not None


@dataclass(frozen=True)
class FastPreflight:
    status: str
    fast_version: str | None
    mapper_version: str | None
    parser_available: bool
    reason: str
    correction: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fast_version": self.fast_version,
            "mapper_version": self.mapper_version,
            "parser_available": self.parser_available,
            "reason": self.reason,
            "correction": self.correction,
        }


def fast_preflight(*, offline: bool = False) -> FastPreflight:
    fast_version = _installed_version(FAST_DISTRIBUTION, "SIMPLICIO_FAST_VERSION")
    mapper_version = _installed_version("simplicio-mapper", "SIMPLICIO_MAPPER_VERSION")
    install = "pip install 'simplicio-cli[fast]'"
    if fast_version is None:
        correction = (
            f"{install} using a local wheelhouse; offline installation cannot download packages"
            if offline
            else install
        )
        return FastPreflight("absent", None, mapper_version, False, "fast-distribution-not-found", correction)

    parsed = _version_tuple(fast_version)
    if parsed is None or parsed < FAST_MIN_VERSION or parsed[0] >= FAST_MAX_MAJOR:
        return FastPreflight(
            "incompatible",
            fast_version,
            mapper_version,
            False,
            "fast-version-outside-supported-range",
            f"install {FAST_DISTRIBUTION}>=2.0.18,<3",
        )

    parser_available = _module_available(f"{FAST_MODULE}.parsers", "SIMPLICIO_FAST_PARSER_AVAILABLE")
    if not parser_available:
        return FastPreflight(
            "degraded",
            fast_version,
            mapper_version,
            False,
            "fast-parser-not-found",
            "reinstall simplicio-fast with its parser artifacts, then rerun fast doctor",
        )
    return FastPreflight("ready", fast_version, mapper_version, True, "compatible", None)


def capabilities_contract(*, offline: bool = False) -> dict[str, Any]:
    preflight = fast_preflight(offline=offline)
    return {
        "schema": CAPABILITIES_SCHEMA,
        "availability": preflight.to_dict(),
        "compatibility": {
            "fast": ">=2.0.18,<3",
            "mapper": "installed version reported; negotiated through snapshot schema",
        },
        "schemas": [
            *SNAPSHOT_SCHEMAS,
            BINARY_CHANGESET_SCHEMA,
            "simplicio.fast.changeset/v2",
            "simplicio.fast.changeset-receipt/v2",
        ],
        "formats": {
            BINARY_CHANGESET_SCHEMA: {
                "input": "bytes",
                "magic": "SFBCHG01",
                "adapter": "execute_changeset_bytes",
            },
            "simplicio.fast.changeset/v2": {
                "input": "json",
                "adapter": "legacy-json-adapter",
            },
        },
        "languages": ["python", "javascript", "typescript", "json"],
        "commands": ["fast capabilities", "fast doctor", "changeset"],
        "source_access": False,
    }


def validate_snapshot(path: str | None) -> dict[str, Any]:
    if path is None:
        return {"status": "not_checked", "reason": "snapshot-not-supplied"}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "reason": f"snapshot-unreadable:{type(exc).__name__}"}
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if schema not in SNAPSHOT_SCHEMAS:
        return {"status": "invalid", "reason": "snapshot-schema-unsupported"}
    return {"status": "valid", "reason": "schema-supported", "schema": schema}


def doctor_contract(*, snapshot: str | None = None, offline: bool = False) -> dict[str, Any]:
    capabilities = capabilities_contract(offline=offline)
    snapshot_status = validate_snapshot(snapshot)
    status = capabilities["availability"]["status"]
    correction = capabilities["availability"]["correction"]
    if snapshot_status["status"] == "invalid":
        status = "degraded"
        correction = "rebuild/export a canonical Mapper context snapshot and retry"
    return {
        "schema": DOCTOR_SCHEMA,
        "status": status,
        "availability": capabilities["availability"],
        "snapshot": snapshot_status,
        "correction": correction,
        "exit_codes": {"ready": 0, "absent": 2, "incompatible": 3, "degraded": 4},
    }


def write_local_receipt(path: str, *, command: str, payload: dict[str, Any]) -> None:
    """Append metadata-only evidence; source paths/content are deliberately excluded."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "command": command,
        "status": payload.get("status") or payload.get("availability", {}).get("status"),
        "fast_version": payload.get("availability", {}).get("fast_version"),
        "mapper_version": payload.get("availability", {}).get("mapper_version"),
        "source_included": False,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
