"""Fail-closed boundary for Mapper-owned context snapshots.

``simplicio.context-snapshot/v1`` belongs to ``simplicio-mapper``.  This
module deliberately contains no schema copy: it verifies the installed
Mapper conformance-kit manifest, then delegates validation to Mapper's public
``context_contract`` API.  The resulting adapter keeps the validated payload
as canonical bytes and exposes only derived, immutable planner views.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.resources
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from simplicio.plan_compiler.errors import PlanCompilerError

MAPPER_CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
DEV_CLI_FALLBACK_CONTEXT_SCHEMA = "simplicio.dev-cli.context-fallback/v1"
MAPPER_CONTRACT_OWNER = "wesleysimplicio/simplicio-mapper"
MAPPER_CONTRACT_MANIFEST_SHA256 = "db8cf791fe6442585f03b3fac220c0987ca5e4271a4955df02b1df77018c52b0"
MAPPER_CONTRACT_COMMIT = "05ea96390762d4bba309abcbf4783d0637a4e53f"
_MANIFEST_PATH = "contracts/context-snapshot/v1/contract-manifest.json"
_LEGACY_SHADOW_FIELDS = frozenset({"snapshot_id", "revision", "base_sha", "captured_at", "root", "extra"})


class MapperContextError(PlanCompilerError):
    """A stable, machine-readable rejection at the Mapper context boundary."""

    def __init__(self, code: str, message: str, *, reasons: tuple[Mapping[str, str], ...] = ()) -> None:
        self.code = code
        self.reasons = reasons
        super().__init__(f"{code}: {message}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read_manifest() -> Mapping[str, Any]:
    """Load the exact contract-kit resource from the installed Mapper wheel."""
    try:
        raw = importlib.resources.files("simplicio_mapper").joinpath(_MANIFEST_PATH).read_bytes()
    except (ImportError, ModuleNotFoundError, FileNotFoundError, OSError, AttributeError) as exc:
        raise MapperContextError(
            "MAPPER_MANIFEST_UNAVAILABLE", "installed Mapper contract kit is unavailable"
        ) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != MAPPER_CONTRACT_MANIFEST_SHA256:
        raise MapperContextError(
            "MAPPER_MANIFEST_DIGEST_MISMATCH",
            "installed Mapper manifest does not match the pinned contract digest",
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MapperContextError(
            "MAPPER_MANIFEST_INVALID", "Mapper manifest is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("owner") != MAPPER_CONTRACT_OWNER:
        raise MapperContextError("MAPPER_MANIFEST_INVALID", "Mapper manifest has an unexpected owner")
    schema_ids = manifest.get("schema_ids")
    compatibility = manifest.get("compatibility")
    if (
        not isinstance(schema_ids, list)
        or MAPPER_CONTEXT_SNAPSHOT_SCHEMA not in schema_ids
        or not isinstance(compatibility, dict)
        or compatibility.get("current") != "v1"
        or compatibility.get("future") != "fail-closed"
    ):
        raise MapperContextError(
            "MAPPER_MANIFEST_INVALID", "Mapper manifest does not describe the canonical v1 contract"
        )
    return MappingProxyType(manifest)


def _mapper_api() -> tuple[Any, Any]:
    try:
        module = importlib.import_module("simplicio_mapper.context_contract")
        return module.validate_context_payload, module.canonical_json
    except (ImportError, ModuleNotFoundError, AttributeError) as exc:
        raise MapperContextError(
            "MAPPER_API_UNAVAILABLE", "installed Mapper validator API is unavailable"
        ) from exc


def _is_legacy_shadow(payload: Any) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("schema") == MAPPER_CONTEXT_SNAPSHOT_SCHEMA
        and _LEGACY_SHADOW_FIELDS.issubset(payload)
        and "graph" not in payload
        and "root_hash" not in payload
    )


@dataclass(frozen=True)
class MapperContextView:
    """Read-only planner view derived from one canonical Mapper snapshot."""

    snapshot_id: str
    revision: str
    root_hash: str
    graph_hash: str
    freshness: Mapping[str, Any]
    fidelity: Mapping[str, Any]
    source_handles: tuple[Mapping[str, Any], ...]
    source_set: tuple[str, ...]
    needs_broader_context: bool


@dataclass(frozen=True)
class MapperContextAdapter:
    """Validated immutable canonical payload plus a small typed planning view."""

    payload_bytes: bytes
    payload: Mapping[str, Any]
    view: MapperContextView
    manifest: Mapping[str, Any]


def _source_handles(graph: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    handles: list[Mapping[str, Any]] = []
    for node in graph.get("nodes", ()):  # validation already guaranteed the shapes.
        if isinstance(node, Mapping) and isinstance(node.get("source"), Mapping):
            handles.append(MappingProxyType(dict(node["source"])))
    for edge in graph.get("edges", ()):
        if isinstance(edge, Mapping) and isinstance(edge.get("source_handle"), Mapping):
            handles.append(MappingProxyType(dict(edge["source_handle"])))
    return tuple(handles)


def load_mapper_context(payload: Any, *, source_root: str | None = None) -> MapperContextAdapter:
    """Validate and adapt a canonical Mapper snapshot without altering it.

    The old Dev CLI shape is deliberately rejected even when it claims the
    canonical schema id.  Standalone callers that need non-Mapper context
    must use :data:`DEV_CLI_FALLBACK_CONTEXT_SCHEMA`; this function will not
    reinterpret it as Mapper context.
    """
    if _is_legacy_shadow(payload):
        raise MapperContextError(
            "LEGACY_CONTEXT_SNAPSHOT_REJECTED",
            "the retired Dev CLI snapshot shape cannot claim Mapper's schema id",
        )
    if not isinstance(payload, Mapping) or payload.get("schema") != MAPPER_CONTEXT_SNAPSHOT_SCHEMA:
        is_fallback = (
            isinstance(payload, Mapping) and payload.get("schema") == DEV_CLI_FALLBACK_CONTEXT_SCHEMA
        )
        code = "FALLBACK_CONTEXT_NOT_CANONICAL" if is_fallback else "UNSUPPORTED_CONTEXT_SCHEMA"
        raise MapperContextError(code, "a canonical Mapper context-snapshot/v1 payload is required")

    manifest = _read_manifest()
    validate_context_payload, canonical_json = _mapper_api()
    try:
        report = validate_context_payload(payload, source_root=source_root)
    except Exception as exc:  # Mapper is an external producer boundary; never leak its implementation error.
        raise MapperContextError(
            "MAPPER_VALIDATOR_FAILED", "Mapper validator failed while checking context"
        ) from exc
    reasons = report.get("reason_codes") if isinstance(report, Mapping) else None
    normalized_reasons = tuple(
        MappingProxyType({str(key): str(value) for key, value in reason.items()})
        for reason in reasons or ()
        if isinstance(reason, Mapping)
    )
    if not isinstance(report, Mapping) or report.get("valid") is not True:
        raise MapperContextError(
            "MAPPER_CONTEXT_REJECTED",
            "Mapper rejected the canonical context payload",
            reasons=normalized_reasons,
        )
    try:
        payload_bytes = bytes(canonical_json(payload))
        frozen_payload = _freeze(json.loads(payload_bytes.decode("utf-8")))
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise MapperContextError(
            "CANONICAL_PAYLOAD_UNAVAILABLE", "canonical Mapper payload cannot be preserved"
        ) from exc
    if not isinstance(frozen_payload, Mapping):  # defensive: Mapper accepted an object above.
        raise MapperContextError("CANONICAL_PAYLOAD_UNAVAILABLE", "canonical Mapper payload is not an object")
    freshness = frozen_payload["freshness"]
    fidelity = frozen_payload["fidelity"]
    graph = frozen_payload["graph"]
    view = MapperContextView(
        snapshot_id=str(frozen_payload["snapshot_id"]),
        revision=str(frozen_payload["revision"]),
        root_hash=str(frozen_payload["root_hash"]),
        graph_hash=str(freshness["graph_hash"]),
        freshness=freshness,
        fidelity=fidelity,
        source_handles=_source_handles(graph),
        source_set=tuple(str(item) for item in frozen_payload["source_set"]),
        needs_broader_context=bool(frozen_payload["needs_broader_context"]),
    )
    return MapperContextAdapter(
        payload_bytes=payload_bytes, payload=frozen_payload, view=view, manifest=manifest
    )


__all__ = [
    "DEV_CLI_FALLBACK_CONTEXT_SCHEMA",
    "MAPPER_CONTRACT_COMMIT",
    "MAPPER_CONTRACT_MANIFEST_SHA256",
    "MAPPER_CONTEXT_SNAPSHOT_SCHEMA",
    "MapperContextAdapter",
    "MapperContextError",
    "MapperContextView",
    "load_mapper_context",
]
