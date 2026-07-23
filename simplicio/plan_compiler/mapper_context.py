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
import importlib.metadata
import importlib.resources
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from simplicio.plan_compiler.errors import PlanCompilerError

MAPPER_CONTEXT_SNAPSHOT_SCHEMA = "simplicio.context-snapshot/v1"
MAPPER_CONTEXT_PACK_SCHEMA = "simplicio.context-pack/v1"
DEV_CLI_CONTEXT_HANDLE_SCHEMA = "simplicio.dev-cli.context-handle/v1"
DEV_CLI_FALLBACK_CONTEXT_SCHEMA = "simplicio.dev-cli.context-fallback/v1"
MAPPER_CONTRACT_OWNER = "wesleysimplicio/simplicio-mapper"
MAPPER_CONTRACT_MANIFEST_SHA256 = "db8cf791fe6442585f03b3fac220c0987ca5e4271a4955df02b1df77018c52b0"
MAPPER_CONTRACT_COMMIT = "05ea96390762d4bba309abcbf4783d0637a4e53f"
_MANIFEST_PATH = "contracts/context-snapshot/v1/contract-manifest.json"
_LEGACY_SHADOW_FIELDS = frozenset({"snapshot_id", "revision", "base_sha", "captured_at", "root", "extra"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEYS = frozenset({"secret", "password", "access_token", "api_key", "private_key"})


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

    @property
    def source_digest(self) -> str:
        """Digest of the exact canonical snapshot bytes accepted from Mapper."""

        return hashlib.sha256(self.payload_bytes).hexdigest()


@dataclass(frozen=True)
class MapperContextPackAdapter:
    """Validated immutable projection tied to one canonical snapshot."""

    payload_bytes: bytes
    payload: Mapping[str, Any]
    pack_hash: str
    projection_digest: str
    files: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ContextHandle:
    """Content-addressed identity shared by planning and effect boundaries."""

    snapshot_id: str
    revision: str
    source_digest: str
    pack_hash: str
    mapper_version: str
    source_root_identity: str
    projection_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": DEV_CLI_CONTEXT_HANDLE_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "pack_hash": self.pack_hash,
            "mapper_version": self.mapper_version,
            "source_root_identity": self.source_root_identity,
            "projection_digest": self.projection_digest,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.to_dict())).hexdigest()

    @property
    def value(self) -> str:
        return f"sha256:{self.digest}"


@dataclass(frozen=True)
class ContextBinding:
    """One validated snapshot/projection pair and its common handle."""

    snapshot: MapperContextAdapter
    pack: MapperContextPackAdapter
    context_handle: ContextHandle


def _source_handles(graph: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    handles: list[Mapping[str, Any]] = []
    for node in graph.get("nodes", ()):  # validation already guaranteed the shapes.
        if isinstance(node, Mapping) and isinstance(node.get("source"), Mapping):
            handles.append(MappingProxyType(dict(node["source"])))
    for edge in graph.get("edges", ()):
        if isinstance(edge, Mapping) and isinstance(edge.get("source_handle"), Mapping):
            handles.append(MappingProxyType(dict(edge["source_handle"])))
    return tuple(handles)


def _canonical_json_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MapperContextError(
            "CONTEXT_PACK_NOT_CANONICAL", "ContextPack cannot be represented as canonical JSON"
        ) from exc


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or _contains_sensitive_key(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _required_mapping(payload: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise MapperContextError("CONTEXT_PACK_INVALID", f"ContextPack.{field} must be an object")
    return value


def load_mapper_context_pack(payload: Any, *, snapshot: MapperContextAdapter) -> MapperContextPackAdapter:
    """Validate a Mapper projection and prove its canonical snapshot origin.

    Mapper owns the ContextPack schema.  The Dev CLI only consumes the
    additive ``source_snapshot`` provenance required for a safe integrated
    dispatch; it does not reinterpret or regenerate Mapper's projection.
    """

    if not isinstance(payload, Mapping) or payload.get("schema") != MAPPER_CONTEXT_PACK_SCHEMA:
        raise MapperContextError(
            "UNSUPPORTED_CONTEXT_PACK_SCHEMA", "a Mapper context-pack/v1 payload is required"
        )
    pack_hash = payload.get("pack_hash")
    if not isinstance(pack_hash, str) or _SHA256_RE.fullmatch(pack_hash) is None:
        raise MapperContextError("CONTEXT_PACK_HASH_INVALID", "Mapper pack_hash must be SHA-256")
    provenance = _required_mapping(payload, "source_snapshot")
    expected = {
        "snapshot_id": snapshot.view.snapshot_id,
        "revision": snapshot.view.revision,
        "source_digest": snapshot.source_digest,
        "root_hash": snapshot.view.root_hash,
    }
    for field, value in expected.items():
        if provenance.get(field) != value:
            raise MapperContextError(
                "CONTEXT_PACK_ORIGIN_MISMATCH",
                f"ContextPack source_snapshot.{field} does not match the canonical snapshot",
            )
    if _contains_sensitive_key(payload):
        raise MapperContextError(
            "CONTEXT_PACK_SENSITIVE_DATA", "ContextPack contains a forbidden sensitive field"
        )
    fidelity = _required_mapping(payload, "fidelity")
    if payload.get("needs_broader_context") is True or fidelity.get("gate") != "ready":
        raise MapperContextError(
            "CONTEXT_PACK_FIDELITY_INSUFFICIENT",
            "ContextPack requires explicit broader-context refresh before an effect",
        )
    budget = payload.get("serialization_budget")
    if budget is not None:
        if not isinstance(budget, Mapping):
            raise MapperContextError("CONTEXT_PACK_BUDGET_INVALID", "serialization_budget must be an object")
        token_budget = budget.get("token_budget")
        estimated_tokens = budget.get("estimated_tokens")
        if (
            not isinstance(token_budget, int)
            or isinstance(token_budget, bool)
            or token_budget < 0
            or not isinstance(estimated_tokens, int)
            or isinstance(estimated_tokens, bool)
            or estimated_tokens < 0
        ):
            raise MapperContextError(
                "CONTEXT_PACK_BUDGET_INVALID", "ContextPack token budget values must be integers"
            )
        if estimated_tokens > token_budget:
            raise MapperContextError(
                "CONTEXT_PACK_BUDGET_EXCEEDED", "ContextPack exceeds its declared token budget"
            )
    files = payload.get("files")
    if not isinstance(files, list):
        raise MapperContextError("CONTEXT_PACK_INVALID", "ContextPack.files must be an array")
    for entry in files:
        if (
            not isinstance(entry, Mapping)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("snapshot_hash"), str)
            or _SHA256_RE.fullmatch(str(entry["snapshot_hash"])) is None
        ):
            raise MapperContextError(
                "CONTEXT_PACK_FILE_INVALID", "every ContextPack file needs path and snapshot_hash"
            )
    payload_bytes = _canonical_json_bytes(payload)
    frozen = _freeze(json.loads(payload_bytes.decode("utf-8")))
    if not isinstance(frozen, Mapping):
        raise MapperContextError("CONTEXT_PACK_INVALID", "canonical ContextPack is not an object")
    frozen_files = frozen["files"]
    return MapperContextPackAdapter(
        payload_bytes=payload_bytes,
        payload=frozen,
        pack_hash=pack_hash,
        projection_digest=hashlib.sha256(payload_bytes).hexdigest(),
        files=tuple(item for item in frozen_files if isinstance(item, Mapping)),
    )


def bind_mapper_context(
    snapshot_payload: Any,
    pack_payload: Any,
    *,
    source_root: str | None = None,
) -> ContextBinding:
    """Validate snapshot + projection and derive their shared content handle."""

    snapshot = load_mapper_context(snapshot_payload, source_root=source_root)
    pack = load_mapper_context_pack(pack_payload, snapshot=snapshot)
    producer = snapshot.payload.get("producer")
    mapper_version = producer.get("version") if isinstance(producer, Mapping) else None
    if not isinstance(mapper_version, str) or not mapper_version:
        try:
            mapper_version = importlib.metadata.version("simplicio-mapper")
        except importlib.metadata.PackageNotFoundError as exc:
            raise MapperContextError(
                "MAPPER_VERSION_UNAVAILABLE", "Mapper producer version is unavailable"
            ) from exc
    handle = ContextHandle(
        snapshot_id=snapshot.view.snapshot_id,
        revision=snapshot.view.revision,
        source_digest=snapshot.source_digest,
        pack_hash=pack.pack_hash,
        mapper_version=mapper_version,
        source_root_identity=snapshot.view.root_hash,
        projection_digest=pack.projection_digest,
    )
    return ContextBinding(snapshot=snapshot, pack=pack, context_handle=handle)


def verify_context_sources(binding: ContextBinding, *, source_root: str) -> None:
    """Fail closed when any projected source changed before effect dispatch."""

    root = Path(source_root).resolve()
    for entry in binding.pack.files:
        raw_path = str(entry["path"]).replace("\\", "/")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise MapperContextError(
                "CONTEXT_ROOT_PATH_MISMATCH", f"unsafe ContextPack source path: {raw_path}"
            )
        candidate = (root / Path(*relative.parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise MapperContextError(
                "CONTEXT_ROOT_PATH_MISMATCH", f"ContextPack source escapes root: {raw_path}"
            ) from exc
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise MapperContextError(
                "SOURCE_DRIFT", f"ContextPack source is missing or unreadable: {raw_path}"
            ) from exc
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != entry["snapshot_hash"]:
            raise MapperContextError("SOURCE_DRIFT", f"ContextPack source changed: {raw_path}")


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
    "ContextBinding",
    "ContextHandle",
    "DEV_CLI_CONTEXT_HANDLE_SCHEMA",
    "DEV_CLI_FALLBACK_CONTEXT_SCHEMA",
    "MAPPER_CONTRACT_COMMIT",
    "MAPPER_CONTRACT_MANIFEST_SHA256",
    "MAPPER_CONTEXT_PACK_SCHEMA",
    "MAPPER_CONTEXT_SNAPSHOT_SCHEMA",
    "MapperContextAdapter",
    "MapperContextError",
    "MapperContextPackAdapter",
    "MapperContextView",
    "bind_mapper_context",
    "load_mapper_context",
    "load_mapper_context_pack",
    "verify_context_sources",
]
