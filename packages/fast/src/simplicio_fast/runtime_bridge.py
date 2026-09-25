"""Deprecated, strict shim over :mod:`simplicio_fast.runtime_backend`.

The former bridge trusted any executable found in ``PATH`` and even treated
``/bin/echo`` as a native backend.  Compatibility names remain, but admission,
handshake, execution and reason codes now have exactly one owner:
``runtime_backend``.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from .runtime_backend import (
    READ_ONLY_OPERATIONS,
    RuntimeBackendError,
    RuntimeSelection,
    runtime_artifact_from_environment,
    select_runtime_backend,
)

BRIDGE_SCHEMA = "simplicio.fast.runtime-bridge/v2"


class RuntimeBridgeError(RuntimeBackendError):
    """Compatibility error carrying a canonical Runtime reason code."""


def _verified_runtime(
    *,
    environment: Mapping[str, str] | None,
    timeout_s: float,
    required_capabilities: Sequence[str],
) -> RuntimeSelection:
    artifact = runtime_artifact_from_environment(
        os.environ if environment is None else environment
    )
    if artifact is None:
        raise RuntimeBridgeError(
            "RUNTIME_MISSING", "SIMPLICIO_RUNTIME_BIN and manifest are required"
        )
    try:
        return select_runtime_backend(
            "rust",
            artifact=artifact,
            required_capabilities=required_capabilities,
            timeout_seconds=timeout_s,
        )
    except RuntimeBackendError as error:
        raise RuntimeBridgeError(error.reason_code, error.detail) from error


def discover_native_binary(
    *,
    environment: Mapping[str, str] | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Return only a manifest-verified, ABI-compatible, handshaken Runtime."""
    try:
        selected = _verified_runtime(
            environment=environment,
            timeout_s=timeout_s,
            required_capabilities=tuple(READ_ONLY_OPERATIONS),
        )
    except RuntimeBridgeError as error:
        return {
            "schema": BRIDGE_SCHEMA,
            "status": "rejected",
            "backend": "off",
            "reason_code": error.reason_code,
            "detail": error.detail,
            "cargo_used": False,
        }
    receipt = selected.receipt()
    return {
        "schema": BRIDGE_SCHEMA,
        "status": "verified",
        "backend": "rust",
        "path": str(selected.backend.artifact.executable),
        "artifact_sha256": receipt["backend_artifact_hash"],
        "abi": receipt["abi"],
        "version": receipt["runtime_version"],
        "platform": receipt["runtime_platform"],
        "handshake": receipt,
        "cargo_used": False,
    }


def execute_via_bridge(
    request: Mapping[str, Any],
    *,
    timeout_s: float = 5.0,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a read-only HBP operation after the canonical handshake.

    This compatibility API is deliberately fail-closed: it never echoes a
    request and never silently substitutes a Python backend.
    """
    if not isinstance(request, Mapping):
        raise RuntimeBridgeError("PROTOCOL_ERROR", "request must be a mapping")
    operation = request.get("op")
    if not isinstance(operation, str) or operation not in READ_ONLY_OPERATIONS:
        raise RuntimeBridgeError(
            "PROTOCOL_ERROR", f"unsupported operation={operation!r}"
        )
    payload = request.get("payload", {})
    if not isinstance(payload, Mapping):
        raise RuntimeBridgeError("PROTOCOL_ERROR", "payload must be a mapping")
    selected = _verified_runtime(
        environment=environment,
        timeout_s=timeout_s,
        required_capabilities=(operation,),
    )
    try:
        result = selected.execute(operation, payload)
    except RuntimeBackendError as error:
        raise RuntimeBridgeError(error.reason_code, error.detail) from error
    return {
        "schema": BRIDGE_SCHEMA,
        "status": "verified",
        "backend": "rust",
        "handshake": selected.receipt(),
        "result": result,
        "cargo_used": False,
    }


__all__ = [
    "BRIDGE_SCHEMA",
    "RuntimeBridgeError",
    "discover_native_binary",
    "execute_via_bridge",
]
