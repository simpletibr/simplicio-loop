"""Small embeddable Python SDK facade over the public projection contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

from .compatibility import compatibility_manifest
from .projection import ProjectionEnvelope, ProjectionError, ProjectionStore
from .universal_context import UniversalContextError, compile_context


SDK_SCHEMA = "simplicio.fast.sdk/v1"
SDK_SUPPORT_MATRIX = (
    {
        "surface": "python",
        "status": "supported",
        "operations": (
            "publish", "compile_delta", "query", "query_async", "snapshot",
            "save", "open", "close", "context", "context_async",
        ),
        "reason": None,
    },
    {
        "surface": "rust",
        "status": "partial",
        "operations": ("read", "query", "context"),
        "reason": "crate_conformance_and_installed_matrix_pending",
    },
    {
        "surface": "session",
        "status": "partial",
        "operations": ("stats", "query", "context"),
        "reason": "resident_transport_and_cross_platform_receipts_pending",
    },
    {
        "surface": "cli",
        "status": "partial",
        "operations": ("diagnose", "json_receipts"),
        "reason": "equivalent_sdk_surface_and_installed_receipts_pending",
    },
)


class SDKError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class ProjectionSDK:
    """In-process projection operations with explicit repository scope."""

    def __init__(self, repository: str) -> None:
        self._closed = False
        try:
            self.store = ProjectionStore(repository)
        except ProjectionError as error:
            raise SDKError(error.reason_code) from error

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            raise SDKError("sdk_closed")

    def close(self) -> None:
        """Close the facade and reject further operations; safe to repeat."""
        self._closed = True

    def __enter__(self) -> "ProjectionSDK":
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    async def __aenter__(self) -> "ProjectionSDK":
        self._ensure_open()
        return self

    async def __aexit__(self, *_: object) -> None:
        self.close()

    @property
    def repository(self) -> str:
        self._ensure_open()
        return self.store.repository

    @property
    def generation(self) -> str | None:
        self._ensure_open()
        return self.store.generation

    def publish(self, envelope: ProjectionEnvelope) -> dict[str, Any]:
        self._ensure_open()
        if not isinstance(envelope, ProjectionEnvelope):
            raise SDKError("envelope_invalid")
        try:
            self.store.publish(envelope)
        except ProjectionError as error:
            raise SDKError(error.reason_code) from error
        return {"schema": SDK_SCHEMA, "operation": "publish", "repository": self.repository, "generation": self.generation, "handle": envelope.stable_handle}

    def compile_delta(self, generation: str, *, base_generation: str | None = None, changed: Iterable[ProjectionEnvelope] = (), deleted_handles: Iterable[str] = (), closure_handles: Iterable[str] = ()) -> dict[str, Any]:
        self._ensure_open()
        changed_items = _bounded_tuple(changed, "changed")
        if any(not isinstance(item, ProjectionEnvelope) for item in changed_items):
            raise SDKError("changed_invalid")
        deleted = _bounded_handles(deleted_handles, "deleted_handles")
        closure = _bounded_handles(closure_handles, "closure_handles")
        try:
            return self.store.apply_delta(
                generation,
                base_generation=base_generation,
                changed=changed_items,
                deleted_handles=deleted,
                closure_handles=closure,
            )
        except ProjectionError as error:
            raise SDKError(error.reason_code) from error

    def query(self, handle: str) -> dict[str, Any] | None:
        self._ensure_open()
        if not isinstance(handle, str) or not handle.strip():
            raise SDKError("query_handle_invalid")
        return next((item for item in self.store.snapshot() if item["stable_handle"] == handle), None)

    def snapshot(self) -> list[dict[str, Any]]:
        self._ensure_open()
        return self.store.snapshot()

    def save(self, path: Path) -> dict[str, Any]:
        self._ensure_open()
        return self.store.save(path)

    @classmethod
    def open(cls, path: Path, repository: str) -> "ProjectionSDK":
        instance = cls(repository)
        try:
            instance.store = ProjectionStore.load(path, repository)
        except ProjectionError as error:
            raise SDKError(error.reason_code) from error
        return instance

    def context(self, *, max_bytes: int = 256 * 1024, max_tokens: int = 4096, max_items: int = 128) -> dict[str, Any]:
        self._ensure_open()
        envelopes = [ProjectionEnvelope.decode(json.dumps(item, sort_keys=True, separators=(",", ":")).encode()) for item in self.store.snapshot()]
        try:
            return compile_context(envelopes, repository_scope=self.repository, max_bytes=max_bytes, max_tokens=max_tokens, max_items=max_items)
        except UniversalContextError as error:
            raise SDKError(error.reason_code) from error

    async def context_async(self, *, max_bytes: int = 256 * 1024, max_tokens: int = 4096, max_items: int = 128) -> dict[str, Any]:
        """Run bounded local compilation without blocking the event loop."""
        return await asyncio.to_thread(self.context, max_bytes=max_bytes, max_tokens=max_tokens, max_items=max_items)

    async def query_async(self, handle: str) -> dict[str, Any] | None:
        """Async-safe read-only query using the same synchronous contract."""
        return await asyncio.to_thread(self.query, handle)

    def capabilities(self) -> dict[str, Any]:
        self._ensure_open()
        return {
            "schema": "simplicio.fast.sdk-capabilities/v1",
            "sdk": SDK_SCHEMA,
            "operations": [
                "publish", "compile_delta", "query", "query_async", "snapshot",
                "save", "open", "close", "context", "context_async",
            ],
            "support_matrix": [
                {**item, "operations": list(item["operations"])}
                for item in SDK_SUPPORT_MATRIX
            ],
            "compatibility": compatibility_manifest(),
            "authority": "derived_read_only",
        }


__all__ = ["ProjectionSDK", "SDKError", "SDK_SCHEMA", "SDK_SUPPORT_MATRIX"]


_MAX_SDK_ITEMS = 100_000


def _bounded_tuple(value: object, field: str) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes)):
        raise SDKError(f"{field}_invalid")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise SDKError(f"{field}_invalid") from error
    if len(result) > _MAX_SDK_ITEMS:
        raise SDKError(f"{field}_invalid")
    return result


def _bounded_handles(value: object, field: str) -> tuple[str, ...]:
    result = _bounded_tuple(value, field)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise SDKError(f"{field}_invalid")
    return result  # type: ignore[return-value]
