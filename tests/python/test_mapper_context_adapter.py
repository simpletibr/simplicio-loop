"""Unit tests for the Mapper-owned ContextSnapshot boundary (#255)."""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any

import pytest

from simplicio.plan_compiler.mapper_context import (
    DEV_CLI_FALLBACK_CONTEXT_SCHEMA,
    MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
    MapperContextError,
    load_mapper_context,
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _payload() -> dict[str, Any]:
    return {
        "schema": MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
        "schema_version": "v1",
        "snapshot_id": "snap-1",
        "revision": "rev-2",
        "root_hash": "root-hash",
        "freshness": {"graph_hash": "graph-hash", "root_hash": "root-hash"},
        "fidelity": {"gate": "ready", "status": "complete"},
        "graph": {
            "nodes": [{"source": {"file": "src/main.py", "line": 1}}],
            "edges": [{"source_handle": {"file": "src/main.py", "line": 2}}],
        },
        "source_set": ["src/main.py"],
        "needs_broader_context": False,
    }


@pytest.fixture
def mapper_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    from simplicio.plan_compiler import mapper_context

    monkeypatch.setattr(
        mapper_context,
        "_read_manifest",
        lambda: MappingProxyType({"owner": "wesleysimplicio/simplicio-mapper"}),
    )

    def validate(payload: Any, **_kwargs: Any) -> dict[str, Any]:
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == "v1"
            and payload.get("root_hash") == "root-hash"
        ):
            return {"valid": True, "reason_codes": []}
        return {"valid": False, "reason_codes": [{"code": "UNSUPPORTED_SCHEMA", "path": "$.schema"}]}

    monkeypatch.setattr(mapper_context, "_mapper_api", lambda: (validate, _canonical_json))


def test_adapter_preserves_canonical_bytes_and_exposes_immutable_view(mapper_boundary: None) -> None:
    payload = _payload()
    adapter = load_mapper_context(payload)

    assert adapter.payload_bytes == _canonical_json(payload)
    assert adapter.view.snapshot_id == "snap-1"
    assert adapter.view.revision == "rev-2"
    assert adapter.view.root_hash == "root-hash"
    assert adapter.view.graph_hash == "graph-hash"
    assert adapter.view.source_set == ("src/main.py",)
    assert len(adapter.view.source_handles) == 2
    with pytest.raises(TypeError):
        adapter.payload["revision"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        adapter.payload["freshness"]["graph_hash"] = "mutated"  # type: ignore[index]


def test_adapter_rejects_old_shadow_shape_before_mapper_validation(mapper_boundary: None) -> None:
    with pytest.raises(MapperContextError, match="LEGACY_CONTEXT_SNAPSHOT_REJECTED") as error:
        load_mapper_context(
            {
                "schema": MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
                "snapshot_id": "old",
                "revision": "1",
                "base_sha": "abc",
                "captured_at": "now",
                "root": ".",
                "extra": {},
            }
        )
    assert error.value.code == "LEGACY_CONTEXT_SNAPSHOT_REJECTED"


def test_adapter_rejects_standalone_fallback_as_noncanonical(mapper_boundary: None) -> None:
    with pytest.raises(MapperContextError, match="FALLBACK_CONTEXT_NOT_CANONICAL"):
        load_mapper_context({"schema": DEV_CLI_FALLBACK_CONTEXT_SCHEMA})


def test_adapter_rejects_future_and_tampered_mapper_payloads(mapper_boundary: None) -> None:
    future = _payload()
    future["schema_version"] = "v2"
    with pytest.raises(MapperContextError, match="MAPPER_CONTEXT_REJECTED") as future_error:
        load_mapper_context(future)
    assert future_error.value.reasons[0]["code"] == "UNSUPPORTED_SCHEMA"

    tampered = _payload()
    tampered["root_hash"] = "tampered"
    with pytest.raises(MapperContextError, match="MAPPER_CONTEXT_REJECTED"):
        load_mapper_context(tampered)


def test_manifest_digest_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from simplicio.plan_compiler import mapper_context

    class Resource:
        def joinpath(self, _path: str) -> Resource:
            return self

        def read_bytes(self) -> bytes:
            return b"{}"

    monkeypatch.setattr(mapper_context.importlib.resources, "files", lambda _package: Resource())
    with pytest.raises(MapperContextError, match="MAPPER_MANIFEST_DIGEST_MISMATCH") as error:
        mapper_context._read_manifest()
    assert error.value.code == "MAPPER_MANIFEST_DIGEST_MISMATCH"


def test_missing_manifest_and_validator_api_have_stable_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    from simplicio.plan_compiler import mapper_context

    def unavailable(_package: str) -> None:
        raise ModuleNotFoundError("simplicio_mapper")

    monkeypatch.setattr(mapper_context.importlib.resources, "files", unavailable)
    with pytest.raises(MapperContextError, match="MAPPER_MANIFEST_UNAVAILABLE"):
        mapper_context._read_manifest()

    monkeypatch.setattr(mapper_context.importlib, "import_module", unavailable)
    with pytest.raises(MapperContextError, match="MAPPER_API_UNAVAILABLE"):
        mapper_context._mapper_api()
