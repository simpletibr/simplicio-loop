"""Unit tests for the Mapper-owned ContextSnapshot boundary (#255)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
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


def _delta(*paths: str, base: str = "rev-2", scan: str = "rev-3", **overrides: Any) -> dict[str, Any]:
    delta = {
        "schema": "simplicio.graph-delta/v1",
        "version": 1,
        "event_type": "delta",
        "mode": "incremental",
        "base_revision": base,
        "scan_revision": scan,
        "full_rescan": False,
        "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
        "events": [],
        "affected_paths": list(paths),
        "diagnostics": [],
        "snapshot": {},
    }
    delta.update(overrides)
    return delta


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


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"engine": "wasm"}, "ENGINE_UNSUPPORTED"),
        ({"engine": "rust", "capability_digest": "", "base_generation": "g"}, "ENGINE_CAPABILITIES_MISSING"),
        ({"base_generation": "g-2", "generation": "g-1"}, "GENERATION_MISMATCH"),
        ({"source_hashes": (("src/main.py", "not-a-sha"),)}, "SOURCE_HASH_INVALID"),
    ],
)
def test_context_handle_rejects_invalid_engine_provenance(overrides: dict[str, Any], code: str) -> None:
    values: dict[str, Any] = {
        "snapshot_id": "snap",
        "revision": "rev",
        "source_digest": "a" * 64,
        "pack_hash": "b" * 64,
        "mapper_version": "0.26.9",
        "source_root_identity": "root",
        "projection_digest": "c" * 64,
        "generation": "g-1",
    }
    values.update(overrides)
    with pytest.raises(MapperContextError, match=code):
        ContextHandle(**values).validate_engine_binding()


def test_context_handle_rejects_storage_internals_in_public_view() -> None:
    class LeakingHandle(ContextHandle):
        def to_dict(self) -> dict[str, Any]:
            return {"mmap_offset": 12}

    handle = LeakingHandle(
        snapshot_id="snap",
        revision="rev",
        source_digest="a" * 64,
        pack_hash="b" * 64,
        mapper_version="0.26.9",
        source_root_identity="root",
        projection_digest="c" * 64,
        generation="g",
    )
    with pytest.raises(MapperContextError, match="ENGINE_INTERNAL_LEAK"):
        handle.validate_engine_binding()


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


def test_context_binding_cache_persists_a_disposable_lookup_index(
    mapper_boundary: None, tmp_path: Any
) -> None:
    binding = bind_mapper_context(_payload(), _pack(_payload()))
    cache = ContextBindingCache(tmp_path)
    cache.put(binding)
    assert cache.lookup(binding.context_handle)["hit"] is True

    index = tmp_path / ".simplicio" / "context-bindings.hbp.idx"
    assert index.is_file()
    assert cache.doctor()["index_present"] is True

    second_process = ContextBindingCache(tmp_path)
    second_process._read_log = lambda: pytest.fail("matching index must avoid HBP replay")
    assert second_process.lookup(binding.context_handle)["hit"] is True

    index.write_text("{broken", encoding="utf-8")
    third_process = ContextBindingCache(tmp_path)
    assert third_process.lookup(binding.context_handle)["hit"] is True


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


@pytest.mark.parametrize("worker_count", [2, 10, 50])
def test_context_binding_cache_concurrent_process_puts_preserve_all_entries(
    mapper_boundary: None, tmp_path: Any, worker_count: int
) -> None:
    handles = []
    for index in range(worker_count):
        payload = {**_payload(), "snapshot_id": f"snap-concurrent-{index}"}
        binding = bind_mapper_context(payload, _pack(payload))
        handles.append(binding.context_handle.to_dict())

    handle_file = tmp_path / "handles.json"
    handle_file.write_text(json.dumps(handles), encoding="utf-8")
    worker = (
        "import json, os, sys; "
        "from pathlib import Path; "
        "from types import SimpleNamespace; "
        "from simplicio.plan_compiler.mapper_context import ContextBindingCache, ContextHandle; "
        "items=json.loads(Path(sys.argv[2]).read_text()); "
        "item=items[int(sys.argv[3])]; "
        "cache=ContextBindingCache(sys.argv[1]); "
        "print(json.dumps(cache.put(SimpleNamespace(context_handle=ContextHandle(**{k:v for k,v in item.items() if k != 'schema'})), fence='10')));"
    )
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(item for item in (repo_root, env.get("PYTHONPATH", "")) if item)
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(tmp_path), str(handle_file), str(index)],
            cwd=repo_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(len(handles))
    ]
    results = [process.communicate(timeout=30) for process in processes]

    assert all(process.returncode == 0 for process in processes), results
    cache = ContextBindingCache(tmp_path)
    assert cache.doctor()["chain_status"] == "valid"
    assert cache.doctor()["entries"] == len(handles)


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


def test_context_binding_cache_recovery_receipt_discards_torn_tail(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    first = bind_mapper_context(payload, _pack(payload))
    second_payload = {**payload, "snapshot_id": "recovery-second"}
    second = bind_mapper_context(second_payload, _pack(second_payload))
    cache = ContextBindingCache(tmp_path)
    cache.put(first)
    cache.put(second)

    log = tmp_path / ".simplicio" / "context-bindings.hbp"
    raw = bytearray(log.read_bytes())
    raw[-1] ^= 0x01
    log.write_bytes(raw)

    receipt = ContextBindingCache(tmp_path).recover()

    assert receipt["schema"] == "simplicio.context-binding-cache-recovery/v1"
    assert receipt["recovered"] is True
    assert receipt["chain_status"] == "valid"
    assert receipt["discarded_bytes"] > 0
    recovered = ContextBindingCache(tmp_path)
    assert recovered.lookup(first.context_handle)["hit"] is True
    assert recovered.lookup(second.context_handle)["hit"] is False


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


def test_context_binding_cache_preserves_corrupt_legacy_store(mapper_boundary: None, tmp_path: Any) -> None:
    legacy = tmp_path / ".simplicio" / "context-bindings.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{not-json", encoding="utf-8")

    with pytest.raises(MapperContextError, match="legacy context cache is corrupt"):
        ContextBindingCache(tmp_path)
    assert legacy.is_file()
    assert not (tmp_path / ".simplicio" / "context-bindings.hbp").exists()


@pytest.mark.parametrize(
    "legacy",
    [[], {"schema": "wrong", "entries": {}}],
)
def test_context_binding_cache_rejects_invalid_legacy_shapes(legacy: Any, tmp_path: Any) -> None:
    path = tmp_path / ".simplicio" / "context-bindings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.raises(MapperContextError, match="legacy context cache is corrupt"):
        ContextBindingCache(tmp_path)


def test_context_binding_cache_handles_log_stat_failure(tmp_path: Any) -> None:
    cache = ContextBindingCache(tmp_path)

    class BrokenPath:
        def stat(self) -> None:
            raise OSError("stat unavailable")

    cache.log_path = BrokenPath()  # type: ignore[assignment]
    assert cache._log_signature() is None


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

    metrics = verify_context_sources(
        binding,
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=_delta("src/main.py"),
    )
    assert metrics["files_considered"] == 1
    assert metrics["files_hashed"] == 1
    assert metrics["bytes_read"] == len(first.read_bytes())
    assert metrics["generation"] == "rev-2"
    assert metrics["paths_requested"] == ["src/main.py"]
    with pytest.raises(MapperContextError, match="GENERATION_DRIFT"):
        verify_context_sources(binding, source_root=str(tmp_path), expected_generation="rev-1")
    with pytest.raises(MapperContextError, match="src/other.py"):
        verify_context_sources(binding, source_root=str(tmp_path), paths=("src/other.py",))
    with pytest.raises(MapperContextError, match="CONTEXT_CAUSAL_PATH_UNBOUND"):
        verify_context_sources(binding, source_root=str(tmp_path), paths=("src/missing.py",))


def test_real_mapper_incremental_delta_is_consumed_without_schema_copy(
    mapper_boundary: None, tmp_path: Any
) -> None:
    incremental = pytest.importorskip("simplicio_mapper.incremental")
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"exact bytes\r\n")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )
    previous = {
        "schema": "simplicio.graph-snapshot/v1",
        "version": 1,
        "revision": "rev-2",
        "snapshot_id": "previous",
        "entities": [],
        "edges": [],
    }
    current = {
        **previous,
        "revision": "rev-3",
        "snapshot_id": "current",
        "entities": [{"id": "file:src/main.py", "path": "src/main.py"}],
    }
    delta = incremental.compute_delta(previous, current, changed_paths=["src/main.py"])

    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=delta,
    )

    assert metrics["files_hashed"] == 1
    assert metrics["engine"] == "mapper-delta"
    assert metrics["delta_status"] == "accepted_causal_intersection"
    assert metrics["fallback_reason"] is None


def test_real_mapper_delta_dirty_causal_drift_blocks_before_effect(
    mapper_boundary: None, tmp_path: Any
) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"before\n")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )
    binding = bind_mapper_context(payload, pack)
    source.write_bytes(b"after\n")

    with pytest.raises(MapperContextError, match="SOURCE_DRIFT"):
        verify_context_sources(
            binding,
            source_root=str(tmp_path),
            paths=("src/main.py",),
            delta=_delta("src/main.py"),
        )


def test_graph_delta_outside_causal_set_skips_all_source_hashes(mapper_boundary: None, tmp_path: Any) -> None:
    source = tmp_path / "src" / "main.py"
    outside = tmp_path / "src" / "other.py"
    source.parent.mkdir()
    source.write_bytes(b"exact\r\nbytes")
    outside.write_bytes(b"outside")
    payload = _payload()
    pack = _pack(
        payload,
        files=[
            {"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()},
            {"path": "src/other.py", "snapshot_hash": hashlib.sha256(outside.read_bytes()).hexdigest()},
        ],
    )
    binding = bind_mapper_context(payload, pack)
    outside.write_bytes(b"drift outside the plan")

    metrics = verify_context_sources(
        binding,
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=_delta("src/other.py"),
    )

    assert metrics["files_considered"] == 0
    assert metrics["files_hashed"] == 0
    assert metrics["bytes_read"] == 0
    assert metrics["fallback_reason"] == "delta_no_causal_intersection"
    assert metrics["delta_status"] == "accepted_no_causal_intersection"


@pytest.mark.parametrize(
    ("delta", "reason"),
    [
        ({"schema": "simplicio.graph-delta/v1"}, "delta_invalid_full_verification"),
        (_delta("src/main.py", base="old-revision"), "delta_base_generation_mismatch_full_verification"),
        (_delta("src/main.py", scan="rev-2"), "delta_same_generation_ambiguous_full_verification"),
    ],
)
def test_graph_delta_invalid_or_ambiguous_falls_back_to_full_pack(
    mapper_boundary: None, tmp_path: Any, delta: dict[str, Any], reason: str
) -> None:
    first = tmp_path / "src" / "main.py"
    second = tmp_path / "src" / "other.py"
    first.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    payload = _payload()
    pack = _pack(
        payload,
        files=[
            {"path": "src/main.py", "snapshot_hash": hashlib.sha256(first.read_bytes()).hexdigest()},
            {"path": "src/other.py", "snapshot_hash": hashlib.sha256(second.read_bytes()).hexdigest()},
        ],
    )
    binding = bind_mapper_context(payload, pack)

    metrics = verify_context_sources(
        binding,
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=delta,
    )

    assert metrics["files_considered"] == 2
    assert metrics["files_hashed"] == 2
    assert metrics["fallback_reason"] == reason
    assert metrics["delta_status"] in {"invalid", "stale", "ambiguous"}


def test_legacy_mapper_without_delta_receipt_requires_full_verification(
    mapper_boundary: None, tmp_path: Any
) -> None:
    source = tmp_path / "src" / "main.py"
    other = tmp_path / "src" / "other.py"
    source.parent.mkdir()
    source.write_bytes(b"one")
    other.write_bytes(b"two")
    payload = _payload()
    pack = _pack(
        payload,
        files=[
            {"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()},
            {"path": "src/other.py", "snapshot_hash": hashlib.sha256(other.read_bytes()).hexdigest()},
        ],
    )

    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        paths=("src/main.py",),
    )

    assert metrics["files_hashed"] == 2
    assert metrics["fallback_reason"] == "delta_unavailable_full_verification"


def test_valid_delta_without_causal_set_falls_back_to_full_pack(mapper_boundary: None, tmp_path: Any) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"one")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )

    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        delta=_delta("src/main.py"),
    )

    assert metrics["files_hashed"] == 1
    assert metrics["fallback_reason"] == "causal_set_absent_full_verification"


def test_delta_resync_request_falls_back_to_full_pack(mapper_boundary: None, tmp_path: Any) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"one")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )
    delta = _delta("src/main.py", fallback={"required": True})

    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=delta,
    )

    assert metrics["files_hashed"] == 1
    assert metrics["fallback_reason"] == "delta_requires_resync_full_verification"


def test_delta_defensive_path_type_guard_falls_back(
    monkeypatch: Any, mapper_boundary: None, tmp_path: Any
) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"one")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )
    delta = _delta("src/main.py")
    delta["affected_paths"] = [None]

    import simplicio.plan_compiler.mapper_context as mapper_context

    monkeypatch.setattr(
        mapper_context.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            load_schema=lambda _schema, _root: {},
            validate_instance=lambda _payload, _schema: [],
        ),
    )
    monkeypatch.setattr(
        mapper_context.importlib.resources,
        "files",
        lambda _name: SimpleNamespace(joinpath=lambda *_parts: "mapper-contract-root"),
    )

    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=delta,
    )

    assert metrics["fallback_reason"] == "delta_affected_paths_invalid_full_verification"


def test_delta_validator_unavailable_falls_back_to_full(
    monkeypatch: Any, mapper_boundary: None, tmp_path: Any
) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_bytes(b"one")
    payload = _payload()
    pack = _pack(
        payload,
        files=[{"path": "src/main.py", "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest()}],
    )
    import simplicio.plan_compiler.mapper_context as mapper_context

    def unavailable(_name: str) -> Any:
        raise ImportError("Mapper contract unavailable")

    monkeypatch.setattr(mapper_context.importlib, "import_module", unavailable)
    metrics = verify_context_sources(
        bind_mapper_context(payload, pack),
        source_root=str(tmp_path),
        paths=("src/main.py",),
        delta=_delta("src/main.py"),
    )

    assert metrics["files_hashed"] == 1
    assert metrics["fallback_reason"] == "delta_validator_unavailable_full_verification:ImportError"


@pytest.mark.parametrize("entry_path", ["../outside.py", "/absolute.py"])
def test_full_fallback_rejects_unsafe_pack_path(
    mapper_boundary: None, tmp_path: Any, entry_path: str
) -> None:
    from simplicio.plan_compiler import mapper_context

    binding = SimpleNamespace(
        pack=SimpleNamespace(
            files=({"path": entry_path, "snapshot_hash": hashlib.sha256(b"x").hexdigest()},)
        ),
        context_handle=SimpleNamespace(generation="rev-2"),
    )

    with pytest.raises(MapperContextError, match="CONTEXT_ROOT_PATH_MISMATCH"):
        mapper_context.verify_context_sources(binding, source_root=str(tmp_path))


def test_full_fallback_reports_missing_source_as_drift(mapper_boundary: None, tmp_path: Any) -> None:
    from simplicio.plan_compiler import mapper_context

    binding = SimpleNamespace(
        pack=SimpleNamespace(files=({"path": "src/missing.py", "snapshot_hash": "a" * 64},)),
        context_handle=SimpleNamespace(generation="rev-2"),
    )

    with pytest.raises(MapperContextError, match="SOURCE_DRIFT"):
        mapper_context.verify_context_sources(binding, source_root=str(tmp_path))


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


def test_context_binding_cache_recovers_after_writer_process_dies_mid_append(
    mapper_boundary: None, tmp_path: Any
) -> None:
    payload = _payload()
    binding = bind_mapper_context(payload, _pack(payload))
    cache = ContextBindingCache(tmp_path)
    cache.put(binding)

    log = tmp_path / ".simplicio" / "context-bindings.hbp"
    lock = tmp_path / ".simplicio" / "context-bindings.hbp.lock"
    worker = (
        "import os, struct, sys; "
        "lock_fd=os.open(sys.argv[2], os.O_CREAT | os.O_EXCL | os.O_WRONLY); "
        "os.write(lock_fd, f'{os.getpid()}\\n'.encode('ascii')); "
        "os.close(lock_fd); "
        "fd=os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND); "
        "os.write(fd, struct.pack('<I', 256)); "
        "os.write(fd, b'\\x01\\x00'); "
        "os.fsync(fd); "
        "os._exit(17)"
    )
    process = subprocess.run(
        [sys.executable, "-c", worker, str(log), str(lock)],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )

    assert process.returncode == 17
    crashed = ContextBindingCache(tmp_path)
    assert crashed.lookup(binding.context_handle)["reason"] == "corrupt_chain"

    receipt = crashed.recover()

    assert receipt["schema"] == "simplicio.context-binding-cache-recovery/v1"
    assert receipt["recovered"] is True
    assert receipt["chain_status"] == "valid"
    assert receipt["bytes_after"] < receipt["bytes_before"]
    assert not lock.is_file()
    recovered = ContextBindingCache(tmp_path)
    assert recovered.lookup(binding.context_handle)["hit"] is True
