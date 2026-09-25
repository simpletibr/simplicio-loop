"""Engine manifest for the Fast data plane.

Python is the only engine: there is no probing, no selection between
implementations, and no fallback wording. ``select_engine`` exists purely to
produce a versioned, validated manifest/receipt for callers that record
provenance (delivery receipts, generation receipts, doctor output).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import __version__
from .snapshot import MAX_FILES, MAX_RELATIONS, MAX_SNAPSHOT_BYTES, MAX_SYMBOLS


MANIFEST_SCHEMA = "simplicio.fast.engine-manifest/v1"
SELECTION_SCHEMA = "simplicio.fast.engine-selection/v1"
ENGINE_CHOICES = ("python", "off")
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
    manifest: dict[str, Any]

    def receipt(self) -> dict[str, Any]:
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
    """Validate the Python reference manifest before it is used as a receipt."""
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


def select_engine(requested: str = "python") -> EngineSelection:
    """Return the (only) Python engine selection, or the disabled selection.

    ``requested`` exists only so callers can pass through a stored/legacy
    value; anything other than ``python``/``off`` is rejected rather than
    silently coerced.
    """
    normalized = requested.strip().lower()
    if normalized not in ENGINE_CHOICES:
        raise ValueError(f"unsupported fast engine: {requested}")
    if normalized == "off":
        return EngineSelection(normalized, "off", "explicitly_disabled", {})
    return EngineSelection(
        normalized,
        "python",
        "explicitly_selected",
        validate_python_manifest(python_manifest()),
    )
