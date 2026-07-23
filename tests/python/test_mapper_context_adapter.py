"""Unit tests for the Mapper-owned ContextSnapshot boundary (#255)."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any

import pytest

from simplicio.plan_compiler.mapper_context import (
    DEV_CLI_FALLBACK_CONTEXT_SCHEMA,
    MAPPER_CONTEXT_PACK_SCHEMA,
    MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
    MapperContextError,
    bind_mapper_context,
    load_mapper_context,
    load_mapper_context_pack,
    verify_context_sources,
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
        "producer": {"name": "simplicio-mapper", "version": "0.24.1"},
        "freshness": {"graph_hash": "graph-hash", "root_hash": "root-hash"},
        "fidelity": {"gate": "ready", "status": "complete"},
        "graph": {
            "nodes": [{"source": {"file": "src/main.py", "line": 1}}],
            "edges": [{"source_handle": {"file": "src/main.py", "line": 2}}],
        },
        "source_set": ["src/main.py"],
        "needs_broader_context": False,
    }


def _pack(payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    source_digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    pack = {
        "schema": MAPPER_CONTEXT_PACK_SCHEMA,
        "pack_hash": "a" * 64,
        "source_snapshot": {
            "snapshot_id": payload["snapshot_id"],
            "revision": payload["revision"],
            "source_digest": source_digest,
            "root_hash": payload["root_hash"],
        },
        "files": [],
        "needs_broader_context": False,
        "fidelity": {"gate": "ready", "status": "sufficient"},
    }
    pack.update(overrides)
    return pack


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


def test_context_handle_is_deterministic_and_binds_snapshot_and_pack(mapper_boundary: None) -> None:
    payload = _payload()
    pack = _pack(payload)

    first = bind_mapper_context(payload, pack)
    second = bind_mapper_context(payload, pack)

    assert first.context_handle.value == second.context_handle.value
    assert first.context_handle.value.startswith("sha256:")
    assert first.context_handle.source_digest == hashlib.sha256(_canonical_json(payload)).hexdigest()
    assert first.context_handle.pack_hash == "a" * 64
    assert (
        first.context_handle.projection_digest
        == hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )

    changed = _pack(payload, recent_changes=["src/main.py"])
    assert bind_mapper_context(payload, changed).context_handle.value != first.context_handle.value


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda pack: pack.update(pack_hash="short"), "CONTEXT_PACK_HASH_INVALID"),
        (
            lambda pack: pack["source_snapshot"].update(snapshot_id="other"),
            "CONTEXT_PACK_ORIGIN_MISMATCH",
        ),
        (
            lambda pack: pack.update(needs_broader_context=True),
            "CONTEXT_PACK_FIDELITY_INSUFFICIENT",
        ),
        (
            lambda pack: pack.update(api_key="redacted"),
            "CONTEXT_PACK_SENSITIVE_DATA",
        ),
        (
            lambda pack: pack.update(serialization_budget={"token_budget": 10, "estimated_tokens": 11}),
            "CONTEXT_PACK_BUDGET_EXCEEDED",
        ),
    ],
)
def test_context_pack_rejections_are_typed(mapper_boundary: None, mutation: Any, code: str) -> None:
    payload = _payload()
    pack = _pack(payload)
    mutation(pack)

    with pytest.raises(MapperContextError) as error:
        bind_mapper_context(payload, pack)
    assert error.value.code == code


def test_source_drift_and_unsafe_paths_fail_before_dispatch(mapper_boundary: None, tmp_path: Any) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("print('one')\n", encoding="utf-8")
    payload = _payload()
    source_hash = hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest()
    pack = _pack(payload, files=[{"path": "src/main.py", "snapshot_hash": source_hash}])
    binding = bind_mapper_context(payload, pack)

    verify_context_sources(binding, source_root=str(tmp_path))
    source.write_text("print('two')\n", encoding="utf-8")
    with pytest.raises(MapperContextError) as drift:
        verify_context_sources(binding, source_root=str(tmp_path))
    assert drift.value.code == "SOURCE_DRIFT"

    unsafe = _pack(payload, files=[{"path": "../main.py", "snapshot_hash": source_hash}])
    with pytest.raises(MapperContextError) as mismatch:
        verify_context_sources(bind_mapper_context(payload, unsafe), source_root=str(tmp_path))
    assert mismatch.value.code == "CONTEXT_ROOT_PATH_MISMATCH"


def test_context_pack_requires_schema_provenance_files_and_valid_budget(
    mapper_boundary: None,
) -> None:
    snapshot = load_mapper_context(_payload())
    with pytest.raises(MapperContextError, match="UNSUPPORTED_CONTEXT_PACK_SCHEMA"):
        load_mapper_context_pack({}, snapshot=snapshot)

    invalids = [
        ({**_pack(_payload()), "source_snapshot": []}, "CONTEXT_PACK_INVALID"),
        ({**_pack(_payload()), "files": "bad"}, "CONTEXT_PACK_INVALID"),
        (
            {
                **_pack(_payload()),
                "serialization_budget": {"token_budget": True, "estimated_tokens": 1},
            },
            "CONTEXT_PACK_BUDGET_INVALID",
        ),
        (
            {**_pack(_payload()), "files": [{"path": "x", "snapshot_hash": "bad"}]},
            "CONTEXT_PACK_FILE_INVALID",
        ),
    ]
    for pack, code in invalids:
        with pytest.raises(MapperContextError) as error:
            load_mapper_context_pack(pack, snapshot=snapshot)
        assert error.value.code == code


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
