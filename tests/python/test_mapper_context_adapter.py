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
    MAPPER_EXECUTION_CONTEXT_SCHEMA,
    ContextBindingCache,
    ContextHandle,
    MapperContextError,
    bind_mapper_context,
    load_mapper_context,
    load_mapper_context_pack,
    load_mapper_execution_context,
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
    assert first.context_handle.generation == "rev-2"
    assert first.context_handle.repository == "wesleysimplicio/simplicio-mapper"
    assert first.context_handle.commit
    assert first.context_handle.context_schema == MAPPER_CONTEXT_SNAPSHOT_SCHEMA
    assert (
        first.context_handle.projection_digest
        == hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )

    changed = _pack(payload, recent_changes=["src/main.py"])
    assert bind_mapper_context(payload, changed).context_handle.value != first.context_handle.value


def test_fast_v3_context_provenance_is_additive_and_engine_neutral() -> None:
    handle = ContextHandle(
        snapshot_id="snap-1",
        revision="rev-2",
        source_digest="a" * 64,
        pack_hash="b" * 64,
        mapper_version="0.25.0",
        source_root_identity="root",
        projection_digest="c" * 64,
        generation="g-1",
        repository="wesleysimplicio/example",
        commit="deadbeef",
        base_generation="g-1",
        overlay_generation="overlay-1",
        engine="rust",
        capability_digest="d" * 64,
        source_hashes=(("src/main.py", "e" * 64),),
    )
    handle.validate_engine_binding()
    payload = handle.to_dict()
    assert payload["engine"] == "rust"
    assert payload["base_generation"] == "g-1"
    assert payload["source_hashes"]["src/main.py"] == "e" * 64
    assert "offset" not in json.dumps(payload)
    assert "mmap" not in json.dumps(payload)

    with pytest.raises(MapperContextError, match="ENGINE_CAPABILITIES_MISSING"):
        ContextHandle(
            snapshot_id="s",
            revision="r",
            source_digest="a" * 64,
            pack_hash="b" * 64,
            mapper_version="m",
            source_root_identity="root",
            projection_digest="c" * 64,
            generation="g",
            engine="rust",
        ).validate_engine_binding()


def test_context_binding_cache_is_cross_process_and_digest_scoped(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    first = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)

    assert cache.lookup(first.context_handle)["hit"] is False
    cache.put(first)

    # A new instance models a second Loop/Dev CLI process.  It may observe
    # metadata for the exact handle, but it never receives context content.
    second_process = ContextBindingCache(tmp_path)
    hit = second_process.lookup(first.context_handle)
    assert hit["hit"] is True
    assert "payload" not in hit
    assert hit["identity"]["source_root_identity"] == "root-hash"

    changed = bind_mapper_context(payload, _pack(payload, recent_changes=["src/main.py"]))
    miss = second_process.lookup(changed.context_handle)
    assert miss["hit"] is False
    assert miss["reason"] == "missing"


def test_context_binding_cache_reuses_unchanged_log_read_and_invalidates_after_write(
    mapper_boundary: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _payload()
    binding = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    cache.put(binding)

    reads = 0
    original = cache._read_log

    def counted_read():
        nonlocal reads
        reads += 1
        return original()

    monkeypatch.setattr(cache, "_read_log", counted_read)
    assert cache.lookup(binding.context_handle)["hit"] is True
    assert cache.lookup(binding.context_handle)["hit"] is True
    assert reads == 1

    cache.invalidate(key=binding.context_handle.value)
    assert cache.lookup(binding.context_handle)["hit"] is False
    assert reads == 3  # initial read, writer validation, then invalidated lookup


def test_context_binding_cache_refresh_invalidates_prior_revision(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    first = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    cache.put(first)

    refreshed_payload = {**payload, "revision": "rev-3"}
    refreshed = bind_mapper_context(refreshed_payload, _pack(refreshed_payload))
    receipt = cache.refresh(refreshed)

    assert receipt["reason"] == "explicit_refresh"
    assert receipt["invalidated"] == 1
    assert cache.lookup(first.context_handle)["hit"] is False
    assert cache.lookup(refreshed.context_handle)["hit"] is True


def test_context_binding_cache_enforces_revision_cas_and_fencing(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    binding = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    stored = cache.put(binding, fence="10")
    assert stored["revision"]
    with pytest.raises(MapperContextError, match="CONTEXT_CACHE_CAS_CONFLICT"):
        cache.put(binding, expected_revision="sha256:stale", fence="10")
    with pytest.raises(MapperContextError, match="CONTEXT_CACHE_FENCE_STALE"):
        cache.put(binding, expected_revision=stored["revision"], fence="9")
    assert cache.doctor()["fence"] == "10"
    before = cache.doctor()["bytes"]
    compacted = cache.compact()
    assert compacted["chain_status"] == "valid"
    assert compacted["bytes"] <= before
    assert cache.lookup(binding.context_handle)["hit"] is True


def test_context_binding_cache_uses_hashed_append_log_and_recovers_truncation(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    binding = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    cache.put(binding)

    log = tmp_path / ".simplicio" / "context-bindings.hbp"
    assert log.is_file()
    assert not (tmp_path / ".simplicio" / "context-bindings.json").is_file()
    assert cache.lookup(binding.context_handle)["hit"] is True

    with log.open("ab") as handle:
        handle.write(b"\x03")
    recovered = ContextBindingCache(tmp_path)
    assert recovered.lookup(binding.context_handle)["hit"] is False
    assert recovered.lookup(binding.context_handle)["reason"] == "corrupt_chain"
    assert recovered.doctor()["chain_status"] == "corrupt"
    assert recovered.compact()["chain_status"] == "valid"
    assert recovered.lookup(binding.context_handle)["hit"] is True


def test_context_binding_cache_migrates_legacy_json_once_and_removes_shadow_store(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    binding = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_text(
        json.dumps(
            {
                "schema": "simplicio.context-binding-cache/v1",
                "entries": {
                    binding.context_handle.value: {
                        "identity": cache._identity(binding.context_handle),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    migrated = ContextBindingCache(tmp_path)
    assert migrated.log_path.is_file()
    assert not migrated.path.is_file()
    assert migrated.lookup(binding.context_handle)["hit"] is True


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
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
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


def test_incremental_source_verification_hashes_only_the_causal_set(
    mapper_boundary: None, tmp_path: Any
) -> None:
    first = tmp_path / "src" / "main.py"
    second = tmp_path / "src" / "other.py"
    first.parent.mkdir()
    first.write_bytes(b"one\r\n")
    second.write_bytes(b"two\r\n")
    payload = _payload()
    pack = _pack(
        payload,
        files=[
            {"path": "src/main.py", "snapshot_hash": hashlib.sha256(first.read_bytes()).hexdigest()},
            {"path": "src/other.py", "snapshot_hash": hashlib.sha256(second.read_bytes()).hexdigest()},
        ],
    )
    binding = bind_mapper_context(payload, pack)
    second.write_bytes(b"changed\r\n")

    metrics = verify_context_sources(binding, source_root=str(tmp_path), paths=("src/main.py",))
    assert metrics["files_considered"] == 1
    assert metrics["files_hashed"] == 1
    assert metrics["bytes_read"] == len(first.read_bytes())
    assert metrics["generation"] == "rev-2"
    assert metrics["paths_requested"] == ["src/main.py"]
    with pytest.raises(MapperContextError, match="GENERATION_DRIFT"):
        verify_context_sources(binding, source_root=str(tmp_path), expected_generation="rev-1")
    with pytest.raises(MapperContextError, match="src/other.py"):
        verify_context_sources(binding, source_root=str(tmp_path), paths=("src/other.py",))


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


def test_latest_mapper_execution_context_can_prove_pack_origin(
    mapper_boundary: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from simplicio.plan_compiler import mapper_context

    class MapperExecutionContext:
        @staticmethod
        def validate_execution_context(_payload: Any) -> list[str]:
            return []

    original_import = mapper_context.importlib.import_module

    def import_module(name: str) -> Any:
        if name == "simplicio_mapper.execution_context":
            return MapperExecutionContext
        return original_import(name)

    monkeypatch.setattr(mapper_context.importlib, "import_module", import_module)
    snapshot = _payload()
    pack = _pack(snapshot)
    pack.pop("source_snapshot")
    execution_context = {
        "schema": MAPPER_EXECUTION_CONTEXT_SCHEMA,
        "repository": {
            "snapshot_id": snapshot["snapshot_id"],
            "root_hash": snapshot["root_hash"],
            "context_pack_hash": pack["pack_hash"],
        },
    }

    binding = bind_mapper_context(snapshot, pack, execution_context_payload=execution_context)
    assert binding.pack.pack_hash == pack["pack_hash"]
    assert (
        load_mapper_execution_context(
            execution_context,
            snapshot=binding.snapshot,
            pack=binding.pack,
        )["schema"]
        == MAPPER_EXECUTION_CONTEXT_SCHEMA
    )


def test_context_pack_without_provenance_fails_closed(mapper_boundary: None) -> None:
    snapshot = _payload()
    pack = _pack(snapshot)
    pack.pop("source_snapshot")
    with pytest.raises(MapperContextError, match="CONTEXT_PACK_PROVENANCE_REQUIRED"):
        bind_mapper_context(snapshot, pack)


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


def test_context_pack_without_raw_hash_derives_canonical_identity(mapper_boundary: None) -> None:
    payload = _payload()
    pack = _pack(payload)
    pack.pop("pack_hash")

    binding = bind_mapper_context(payload, pack)

    expected = hashlib.sha256(_canonical_json(pack)).hexdigest()
    assert binding.pack.pack_hash == expected
    assert binding.context_handle.pack_hash == expected
