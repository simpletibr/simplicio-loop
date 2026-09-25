"""Engine manifests and fail-closed selection for the V3 Fast data plane.

The Python implementation is the reference engine.  A Rust engine may only be
selected after a real executable proves its versioned capability handshake;
selection never imports the Python processor as part of the Rust probe.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .snapshot import MAX_FILES, MAX_RELATIONS, MAX_SNAPSHOT_BYTES, MAX_SYMBOLS


MANIFEST_SCHEMA = "simplicio.fast.engine-manifest/v1"
SELECTION_SCHEMA = "simplicio.fast.engine-selection/v1"
ENGINE_CHOICES = ("auto", "rust", "python", "off")
PYTHON_REQUIRED_CAPABILITIES = frozenset(
    {
        "build",
        "refresh",
        "query",
        "context",
        "impact",
        "understand",
        "plan",
        "apply",
        "doctor",
        "receipts",
    }
)


class EngineSelectionError(RuntimeError):
    """Raised when an explicitly requested engine cannot be proven usable."""

    def __init__(self, receipt: dict[str, Any]) -> None:
        self.receipt = receipt
        super().__init__(receipt["reason"])


class PythonManifestError(ValueError):
    """Raised when the Python reference manifest is not trustworthy."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class EngineSelection:
    requested: str
    selected: str
    reason: str
    executable: str | None
    manifest: dict[str, Any]
    probe_ms: float | None = None

    def receipt(self) -> dict[str, Any]:
        conformance = self.manifest.get("conformance")
        if not isinstance(conformance, dict):
            conformance = {}
        capabilities = self.manifest.get("capabilities")
        if not isinstance(capabilities, list):
            capabilities = None
        return {
            "schema": SELECTION_SCHEMA,
            "requested": self.requested,
            "selected": self.selected,
            "requested_engine": self.requested,
            "selected_engine": self.selected,
            "version": self.manifest.get("version"),
            "capabilities": capabilities,
            "reason": self.reason,
            "conformance_digest": conformance.get("digest"),
            "timings": {"probe_ms": self.probe_ms},
            "executable": self.executable,
            "manifest": self.manifest,
        }


def python_manifest() -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "engine": "python",
        "version": __version__,
        "status": "available",
        "reference": True,
        "fallback": True,
        "capabilities": [
            "build",
            "refresh",
            "query",
            "search",
            "context",
            "impact",
            "understand",
            "plan",
            "apply",
            "overlay",
            "lease",
            "doctor",
            "receipts",
        ],
        "formats": ["SFAST001/v1", "SFAST001/v2"],
        "source_languages": ["python"],
        "minimum_python": "3.11",
        "limits": {
            "max_snapshot_bytes": MAX_SNAPSHOT_BYTES,
            "max_files": MAX_FILES,
            "max_symbols": MAX_SYMBOLS,
            "max_relations": MAX_RELATIONS,
        },
    }


def validate_python_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the Python reference/fallback manifest before selection."""
    if not isinstance(manifest, dict):
        raise PythonManifestError(
            "manifest_not_object", "Python manifest must be an object"
        )
    expected = (
        ("schema", MANIFEST_SCHEMA),
        ("engine", "python"),
        ("status", "available"),
    )
    for field, value in expected:
        if manifest.get(field) != value:
            raise PythonManifestError(
                "manifest_field_invalid", f"Python manifest field {field} is invalid"
            )
    if manifest.get("reference") is not True:
        raise PythonManifestError(
            "reference_flag_missing", "Python manifest must declare reference=true"
        )
    if manifest.get("fallback") is not True:
        raise PythonManifestError(
            "fallback_flag_missing", "Python manifest must declare fallback=true"
        )
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) or not item for item in capabilities
    ):
        raise PythonManifestError(
            "capabilities_invalid",
            "Python capabilities must be a non-empty string list",
        )
    if len(capabilities) != len(set(capabilities)):
        raise PythonManifestError(
            "capabilities_duplicate", "Python capabilities must be unique"
        )
    missing = sorted(PYTHON_REQUIRED_CAPABILITIES.difference(capabilities))
    if missing:
        raise PythonManifestError(
            "capability_missing",
            f"Python manifest is missing capabilities: {', '.join(missing)}",
        )
    formats = manifest.get("formats")
    if not isinstance(formats, list) or not {"SFAST001/v1", "SFAST001/v2"}.issubset(
        formats
    ):
        raise PythonManifestError(
            "formats_missing", "Python manifest must support SFAST001/v1 and v2"
        )
    if (
        manifest.get("source_languages") != ["python"]
        or manifest.get("minimum_python") != "3.11"
    ):
        raise PythonManifestError(
            "runtime_contract_invalid", "Python runtime contract is invalid"
        )
    limits = manifest.get("limits")
    if not isinstance(limits, dict) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in limits.values()
    ):
        raise PythonManifestError(
            "limits_invalid", "Python manifest limits must be positive integers"
        )
    return manifest


def _rust_executable() -> str | None:
    configured = os.environ.get("SIMPLICIO_FAST_RUST")
    if configured:
        candidate = Path(configured)
        return str(candidate) if candidate.is_file() else None
    return shutil.which("simplicio-fast-rs")


def probe_rust() -> tuple[dict[str, Any] | None, str | None]:
    executable = _rust_executable()
    if executable is None:
        return None, "rust_executable_missing"
    try:
        completed = subprocess.run(
            [executable, "--version", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "rust_probe_failed"
    if completed.returncode != 0:
        return None, "rust_probe_nonzero"
    try:
        manifest = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "rust_probe_invalid_json"
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        return None, "rust_manifest_schema_mismatch"
    if manifest.get("engine") != "rust" or manifest.get("status") != "available":
        return None, "rust_manifest_not_healthy"
    conformance = manifest.get("conformance")
    digest = conformance.get("digest") if isinstance(conformance, dict) else None
    if (
        not isinstance(conformance, dict)
        or conformance.get("passed") is not True
        or not isinstance(digest, str)
        or not digest.strip()
    ):
        return None, "rust_conformance_missing"
    return manifest, None


def _probe_rust_timed() -> tuple[dict[str, Any] | None, str | None, float]:
    started = time.perf_counter()
    manifest, reason = probe_rust()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return manifest, reason, elapsed_ms


def select_engine(requested: str = "auto") -> EngineSelection:
    normalized = requested.strip().lower()
    if normalized not in ENGINE_CHOICES:
        raise ValueError(f"unsupported fast engine: {requested}")
    if normalized == "off":
        return EngineSelection(normalized, "off", "explicitly_disabled", None, {})
    if normalized == "python":
        return EngineSelection(
            normalized,
            "python",
            "explicitly_selected",
            None,
            validate_python_manifest(python_manifest()),
        )
    rust_manifest, rust_reason, probe_ms = _probe_rust_timed()
    rust_path = _rust_executable()
    if normalized in {"auto", "rust"} and rust_manifest is not None:
        return EngineSelection(
            normalized, "rust", "rust_probe_passed", rust_path, rust_manifest, probe_ms
        )
    if normalized == "rust":
        selection = EngineSelection(
            normalized,
            "unavailable",
            rust_reason or "rust_unavailable",
            rust_path,
            {"schema": MANIFEST_SCHEMA, "engine": "rust", "status": "unavailable"},
            probe_ms,
        )
        raise EngineSelectionError(selection.receipt())
    return EngineSelection(
        normalized,
        "python",
        rust_reason or "rust_not_selected",
        None,
        validate_python_manifest(python_manifest()),
        probe_ms,
    )
