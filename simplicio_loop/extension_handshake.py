"""Fail-closed handshake for an exact Simplicio Loop extension runtime (#621)."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .extension_manifest import SCHEMA_ID as EXTENSION_SCHEMA, compose_stage_graph
from .extension_registry import ExtensionRegistry
from .feedback_recovery_agent import FEEDBACK_RECOVERY_RECEIPT_SCHEMA
from .ops_ledger import SCHEMA as LEDGER_SCHEMA
from .oracle import COMPLETION_SCHEMA, ORACLE_MATRIX_SCHEMA
from .process_supervisor import PROCESS_RESULT_SCHEMA, PROCESS_SPEC_SCHEMA
from .runner import RUNNER_SCHEMA, STATE_SCHEMA

HANDSHAKE_SCHEMA = "simplicio.extension-handshake/v1"
SUPPORTED_HANDSHAKE_SCHEMAS = (HANDSHAKE_SCHEMA,)
RUNTIME_FINGERPRINT_SCHEMA = "simplicio.extension-runtime-fingerprint/v1"
RUN_OUTCOME_SCHEMA = "simplicio.run-outcome/v1"
INVALIDATION_SCHEMA = "simplicio.receipt-invalidation/v1"
REQUIRED_CAPABILITIES = frozenset({
    "process_supervision", "stage_composition", "receipt_invalidation",
    "run_outcome", "oracle_delegation",
})
CORE_STAGES = (
    {"stage_id": "intake", "depends_on": [], "mandatory": True, "gates": {"contract": "fail_closed"}},
    {"stage_id": "execute", "depends_on": ["intake"], "mandatory": True, "gates": {"process_spec": "fail_closed"}},
    {"stage_id": "quality", "depends_on": ["execute"], "mandatory": True, "gates": {"quality": "block"}},
    {"stage_id": "watcher", "depends_on": ["quality"], "mandatory": True, "gates": {"evidence": "fail_closed"}},
    {"stage_id": "delivery", "depends_on": ["watcher"], "mandatory": True, "gates": {"delivery": "fail_closed"}},
    {"stage_id": "oracle", "depends_on": ["delivery"], "mandatory": True, "gates": {"completion": "fail_closed"}},
)

class ExtensionHandshakeError(RuntimeError):
    """A typed incompatibility; callers must not downgrade or continue."""
    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def _semver(value: str) -> tuple[int, int, int]:
    try:
        parts = value.split(".")
        if len(parts) != 3 or any(not x.isdigit() for x in parts):
            raise ValueError
        return tuple(int(x) for x in parts)  # type: ignore[return-value]
    except (AttributeError, ValueError):
        raise ExtensionHandshakeError("UNSUPPORTED_VERSION", f"invalid semantic version: {value!r}")


def _module_file() -> Path:
    return Path(__file__).resolve()


def runtime_identity() -> dict[str, Any]:
    executable = Path(sys.executable).resolve()
    package = Path(__file__).resolve().parent
    try:
        distribution = Path(importlib.metadata.distribution("simplicio-loop").locate_file("")).resolve()
    except importlib.metadata.PackageNotFoundError:
        distribution = package.parent
    return {
        "executable": str(executable),
        "argv0": str(Path(sys.argv[0]).resolve()),
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "module": __name__.split(".extension_handshake")[0],
        "module_path": str(package),
        "package_version": __version__,
        "distribution_path": str(distribution),
    }


def _hash_file(digest: Any, path: Path) -> None:
    digest.update(str(path.resolve()).encode())
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ExtensionHandshakeError("RUNTIME_IDENTITY_UNREADABLE", f"cannot fingerprint {path}: {exc}")


def runtime_fingerprint() -> str:
    """Bind the installed executable and exact Loop modules used by doctor/run."""
    digest = hashlib.sha256()
    digest.update(RUNTIME_FINGERPRINT_SCHEMA.encode())
    identity = runtime_identity()
    digest.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    _hash_file(digest, Path(identity["executable"]))
    argv0 = Path(identity["argv0"])
    if argv0.is_file():
        _hash_file(digest, argv0)
    for path in sorted((_module_file(), Path(__file__).with_name("extension_registry.py"),
                        Path(__file__).with_name("extension_manifest.py"),
                        Path(__file__).with_name("runner.py"), Path(__file__).with_name("oracle.py"))):
        _hash_file(digest, path)
    return "sha256:" + digest.hexdigest()


def verify_runtime_fingerprint(expected: str) -> str:
    if not isinstance(expected, str) or not expected.startswith("sha256:") or len(expected) != 71:
        raise ExtensionHandshakeError("INVALID_FINGERPRINT", "expected fingerprint must be sha256:<64 hex>")
    observed = runtime_fingerprint()
    if not __import__("hmac").compare_digest(expected, observed):
        raise ExtensionHandshakeError("RUNTIME_SUBSTITUTED", f"runtime fingerprint mismatch: expected {expected}, observed {observed}")
    return observed


def _provider_runtime(registry: ExtensionRegistry, provider_id: str) -> Any:
    getter = getattr(registry, "runtime", None)
    return getter(provider_id) if callable(getter) else None


def _required_ids(manifest: Mapping[str, Any], field: str, key: str) -> set[str]:
    return {str(row[key]) for row in manifest.get(field, []) if isinstance(row, Mapping) and key in row}


def extension_handshake(provider_id: str, policy: str, *, requested_schema: str = HANDSHAKE_SCHEMA,
                        registry: ExtensionRegistry | None = None) -> dict[str, Any]:
    if requested_schema not in SUPPORTED_HANDSHAKE_SCHEMAS:
        raise ExtensionHandshakeError("UNSUPPORTED_HANDSHAKE_SCHEMA", f"unsupported handshake schema {requested_schema!r}; supported: {SUPPORTED_HANDSHAKE_SCHEMAS}")
    if not provider_id or not policy:
        raise ExtensionHandshakeError("INVALID_REQUEST", "provider and policy are required")
    registry = registry or ExtensionRegistry()
    if len(registry) == 0:
        try:
            registry.discover_entry_points(strict=True)
        except Exception as exc:
            raise ExtensionHandshakeError("PROVIDER_UNLOADABLE", str(exc)) from exc
    manifest = registry.get(provider_id)
    if manifest is None:
        raise ExtensionHandshakeError("PROVIDER_UNREGISTERED", f"provider {provider_id!r} is not registered")
    current = _semver(__version__)
    requires = manifest.get("requires_core", {})
    if requires.get("min_version") and current < _semver(requires["min_version"]):
        raise ExtensionHandshakeError("CORE_VERSION_UNSUPPORTED", "provider requires a newer Loop core")
    if requires.get("max_version") and current > _semver(requires["max_version"]):
        raise ExtensionHandshakeError("CORE_VERSION_UNSUPPORTED", "provider does not support this Loop core")
    runtime = _provider_runtime(registry, provider_id)
    if runtime is None:
        raise ExtensionHandshakeError("PROVIDER_RUNTIME_MISSING", "manifest loaded but provider runtime bindings are absent")
    capabilities = set((manifest.get("capabilities") or {}).get("provides") or [])
    missing_capabilities = sorted(REQUIRED_CAPABILITIES - capabilities)
    if missing_capabilities:
        raise ExtensionHandshakeError("CAPABILITY_MISSING", "missing capabilities: " + ", ".join(missing_capabilities))
    bindings = getattr(runtime, "bindings", None)
    if not isinstance(bindings, Mapping):
        raise ExtensionHandshakeError("HANDLER_MISSING", "provider runtime must expose a bindings mapping")
    required_handlers = _required_ids(manifest, "effect_handlers", "effect_id")
    required_roles = _required_ids(manifest, "role_bindings", "role_id")
    missing = sorted((required_handlers | required_roles) - {str(key) for key, fn in bindings.items() if callable(fn)})
    if missing:
        raise ExtensionHandshakeError("HANDLER_MISSING", "missing callable handler/role bindings: " + ", ".join(missing))
    if not required_handlers:
        raise ExtensionHandshakeError("HANDLER_MISSING", "provider declares no effect handlers")
    if not required_roles:
        raise ExtensionHandshakeError("ROLE_MISSING", "provider declares no roles")
    schemas = _required_ids(manifest, "receipt_schemas", "schema_id")
    if not schemas:
        raise ExtensionHandshakeError("RECEIPT_SCHEMA_MISSING", "provider declares no receipt schemas")
    composed = compose_stage_graph(CORE_STAGES, [manifest])
    if not composed["ok"]:
        raise ExtensionHandshakeError("STAGE_GRAPH_INVALID", "; ".join(composed["errors"]))
    identity = runtime_identity()
    fingerprint = runtime_fingerprint()
    return {
        "schema": HANDSHAKE_SCHEMA, "status": "PASS", "provider": {
            "id": provider_id, "version": manifest["version"], "policy": policy,
            "manifest_schema": EXTENSION_SCHEMA, "capabilities": sorted(capabilities),
            "roles": sorted(required_roles), "handlers": sorted(required_handlers),
        },
        "runtime": {**identity, "fingerprint_schema": RUNTIME_FINGERPRINT_SCHEMA, "fingerprint": fingerprint},
        "composition": {"dry_run": True, "worker_execution": False, "stages": composed["stages"]},
        "contracts": {
            "process_spec": PROCESS_SPEC_SCHEMA, "process_result": PROCESS_RESULT_SCHEMA,
            "ledger": LEDGER_SCHEMA, "run_manifest": RUNNER_SCHEMA, "run_state": STATE_SCHEMA,
            "run_outcome": RUN_OUTCOME_SCHEMA, "invalidation": INVALIDATION_SCHEMA,
            "feedback_recovery": FEEDBACK_RECOVERY_RECEIPT_SCHEMA,
            "completion_receipt": COMPLETION_SCHEMA, "oracle_matrix": ORACLE_MATRIX_SCHEMA,
            "provider_receipts": sorted(schemas),
        },
        "authorities": {"completion_oracle": "simplicio-loop", "exclusive": True, "provider_may_complete": False},
        "capabilities": {"receipt_invalidation": True, "run_outcome": True},
    }
