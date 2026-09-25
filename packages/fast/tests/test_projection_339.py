from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from simplicio_fast.knowledge import KnowledgeFacade
from simplicio_fast.prism_arena import PrismArena
from simplicio_fast.parser_adapter import build_projection
from simplicio_fast.projection import (
    ProjectionEnvelope,
    ProjectionError,
    ProjectionStore,
    contract_manifest,
    _canonical,
    _reject_private_fields,
)
from simplicio_fast.skills import SkillCatalog


def test_code_knowledge_and_operations_share_deterministic_envelope() -> None:
    encoded = []
    for projection_type in ("code", "knowledge", "operations"):
        envelope = ProjectionEnvelope.create(
            projection_type,
            producer="mapper",
            producer_schema="mapper.context/v1",
            generation="g1",
            stable_handle=f"{projection_type}:item-1",
            payload={"items": [{"id": "item-1", "value": 3}]},
        )
        assert ProjectionEnvelope.decode(envelope.encode()) == envelope
        encoded.append(envelope.encode())
    assert len({value for value in encoded}) == 3


def test_projection_bytes_are_deterministic_and_tamper_evident() -> None:
    first = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:abc",
        payload={"z": 1, "a": ["x", "y"]},
    )
    second = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:abc",
        payload={"a": ["x", "y"], "z": 1},
    )
    assert first.encode() == second.encode()
    tampered = first.encode().replace(b'"z":1', b'"z":2')
    with pytest.raises(ProjectionError, match="payload_digest_mismatch"):
        ProjectionEnvelope.decode(tampered)


def test_shared_python_rust_projection_fixture_decodes() -> None:
    fixture = Path("fixtures/projection/v1/code-symbol.json").read_bytes()
    envelope = ProjectionEnvelope.decode(fixture)
    assert envelope.stable_handle == "code:symbol"
    assert envelope.encode() == fixture


def test_projection_rejects_future_schema_and_private_offsets() -> None:
    with pytest.raises(ProjectionError, match="projection_schema_unsupported"):
        ProjectionEnvelope.decode(b'{"schema":"simplicio.fast.projection/v2"}')
    with pytest.raises(ProjectionError, match="projection_exposes_offset"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper.context/v1",
            generation="g1",
            stable_handle="symbol:abc",
            payload={"items": [{"mmap_offset": 4}]},
        )


def test_projection_dataclass_boundary_rejects_tampered_digest() -> None:
    envelope = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:abc",
        payload={"name": "abc"},
    )
    with pytest.raises(ProjectionError, match="payload_digest_mismatch"):
        replace(envelope, payload_sha256="sha256:" + "0" * 64)


def test_projection_dataclass_normalizes_mutable_contract_fields() -> None:
    payload = {"name": "abc", "nested": {"items": ["stable"]}}
    base = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:abc",
        payload=payload,
    )
    envelope = replace(
        base,
        payload=payload,
        stable_handles=["symbol:abc"],
        capabilities_required=["projection.decode.v1"],
        truncation_reasons=["budget"],
        tombstones=["symbol:old"],
        budgets={"bytes": 1024},
    )
    assert envelope.stable_handles == ("symbol:abc",)
    assert envelope.capabilities_required == ("projection.decode.v1",)
    assert envelope.truncation_reasons == ("budget",)
    assert envelope.tombstones == ("symbol:old",)
    assert envelope.budgets == {"bytes": 1024}
    payload["mutated"] = True
    payload["nested"]["items"].append("external")
    assert "mutated" not in envelope.payload
    assert envelope.payload["nested"] == {"items": ["stable"]}


def test_projection_manifest_and_provenance_fields_are_strict_and_deterministic() -> None:
    manifest = contract_manifest()
    assert manifest["envelope"]["schema"] == "simplicio.fast.projection/v1"
    assert manifest["envelope"]["major"] == 1
    assert manifest["envelope"]["minor"] == 0
    assert manifest["type_manifest"]["types"] == ["code", "knowledge", "operations"]
    disk_manifest = json.loads(
        (
            Path(__file__).parents[1]
            / "contracts"
            / "projection"
            / "v1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert disk_manifest == manifest
    envelope = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:abc",
        producer_version="2.0.20",
        repository_scope="org/repo",
        tenant_scope="tenant-a",
        domain_scope="code",
        capabilities_required=("projection.decode.v1",),
        budgets={"bytes": 1024},
        truncation_reasons=("budget",),
        payload={"name": "abc"},
    )
    decoded = ProjectionEnvelope.decode(envelope.encode())
    assert decoded.repository_scope == "org/repo"
    assert decoded.capabilities_required == ("projection.decode.v1",)
    assert decoded.budgets == {"bytes": 1024}
    assert decoded.truncation_reasons == ("budget",)
    with pytest.raises(ProjectionError, match="projection_depth_limit"):
        deep: object = "x"
        for _ in range(34):
            deep = {"deep": deep}
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper.context/v1",
            generation="g1",
            stable_handle="symbol:abc",
            payload=deep,
        )


def test_projection_decode_preserves_all_optional_provenance_fields() -> None:
    envelope = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="projection-g2",
        stable_handle="symbol:abc",
        schema_version="1.1",
        projection_type_version="1.2",
        producer_version="2.0.20",
        repository_scope="org/repo",
        tenant_scope="tenant-a",
        domain_scope="code",
        source_generation="source-g1",
        projection_generation="projection-g2",
        config_fingerprint="config-1",
        toolchain_fingerprint="toolchain-1",
        parser_fingerprint="parser-1",
        stable_handles=("symbol:abc", "symbol:related"),
        capabilities_required=("projection.decode.v1",),
        budgets={"bytes": 1024},
        truncation_reasons=("budget",),
        parent_generation="parent-g0",
        base_generation="base-g1",
        delta_generation="delta-g2",
        tombstones=("symbol:old",),
        completeness="partial",
        fidelity="estimated",
        observed_sequence="42",
        conformance_digest="conformance-1",
        payload={"name": "abc"},
    )
    assert ProjectionEnvelope.decode(envelope.encode()) == envelope


def test_knowledge_and_operations_producers_use_the_same_abi(tmp_path) -> None:
    catalog = SkillCatalog(tmp_path, generation="g1", scope="repo")
    knowledge = KnowledgeFacade(catalog)
    knowledge_projection = knowledge.projection("find parser", sources=("skills",))
    assert knowledge_projection.projection_type == "knowledge"
    assert ProjectionEnvelope.decode(knowledge_projection.encode()) == knowledge_projection

    arena = PrismArena.publish(
        tmp_path / "arena", "org/repo", "source-1", {"a.py": b"value = 1\n"}
    )
    try:
        operations_projection = arena.projection()
        assert operations_projection.projection_type == "operations"
        assert ProjectionEnvelope.decode(operations_projection.encode()) == operations_projection
    finally:
        arena.close()


def test_code_parser_producer_uses_the_same_abi(tmp_path) -> None:
    (tmp_path / "service.py").write_text(
        "def parse_request(value):\n    return value\n", encoding="utf-8"
    )
    projection = build_projection(tmp_path, mode="bootstrap")
    assert projection.projection_type == "code"
    assert projection.producer_schema == "simplicio.fast.parser-adapter/v1"
    assert ProjectionEnvelope.decode(projection.encode()) == projection


def test_projection_store_applies_bounded_delta_and_reports_closure() -> None:
    store = ProjectionStore("repo-a")
    first = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper.context/v1",
        generation="g1",
        stable_handle="symbol:a",
        payload={"repository": "repo-a", "name": "a"},
    )
    second = ProjectionEnvelope.create(
        "knowledge",
        producer="skills",
        producer_schema="skills/v1",
        generation="g1",
        stable_handle="skill:b",
        payload={"repository": "repo-a", "name": "b"},
    )
    store.publish(first)
    receipt = store.apply_delta(
        "g1", changed=(second,), deleted_handles=("symbol:a",), closure_handles=("symbol:c",)
    )
    assert receipt["changed_handles"] == ["skill:b"]
    assert receipt["deleted_handles"] == ["symbol:a"]
    assert receipt["closure_handles"] == ["skill:b", "symbol:a", "symbol:c"]
    assert [item["stable_handle"] for item in store.snapshot()] == ["skill:b"]


def test_projection_store_rejects_stale_and_cross_repository_data() -> None:
    store = ProjectionStore("repo-a")
    foreign = ProjectionEnvelope.create(
        "operations",
        producer="runtime",
        producer_schema="runtime/v1",
        generation="g2",
        stable_handle="slot:1",
        payload={"repository": "repo-b"},
    )
    with pytest.raises(ProjectionError, match="projection_repository_mismatch"):
        store.publish(foreign)
    local = ProjectionEnvelope.create(
        "operations",
        producer="runtime",
        producer_schema="runtime/v1",
        generation="g1",
        stable_handle="slot:1",
        payload={"repository": "repo-a"},
    )
    store.publish(local)
    with pytest.raises(ProjectionError, match="projection_generation_stale"):
        store.apply_delta("g2", changed=())


def test_projection_store_save_load_is_atomic_and_tamper_evident(tmp_path) -> None:
    store = ProjectionStore("repo-a")
    record = ProjectionEnvelope.create(
        "knowledge",
        producer="skills",
        producer_schema="skills/v1",
        generation="g1",
        stable_handle="skill:a",
        payload={"repository": "repo-a", "name": "a"},
    )
    store.publish(record)
    path = tmp_path / "derived" / "projection.json"
    receipt = store.save(path)
    assert receipt["status"] == "saved"
    restored = ProjectionStore.load(path, "repo-a")
    assert restored.snapshot() == store.snapshot()
    path.write_text(path.read_text(encoding="utf-8").replace("skill:a", "skill:b"), encoding="utf-8")
    with pytest.raises(ProjectionError, match="projection_store_digest_mismatch"):
        ProjectionStore.load(path, "repo-a")
    with pytest.raises(ProjectionError, match="projection_repository_mismatch"):
        ProjectionStore.load(tmp_path / "derived" / "projection.json", "repo-b")


def test_projection_envelope_rejects_budget_and_payload_contract_edges() -> None:
    envelope = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:a",
        payload={"name": "a"},
    )
    with pytest.raises(ProjectionError, match="projection_type_unsupported"):
        ProjectionEnvelope.create(
            "other",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={},
        )
    with pytest.raises(ProjectionError, match="projection_type_unsupported"):
        replace(envelope, projection_type="other")
    with pytest.raises(ProjectionError, match="payload_invalid"):
        replace(envelope, payload=[])
    with pytest.raises(ProjectionError, match="payload_not_json"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={"bad": object()},
        )
    with pytest.raises(ProjectionError, match="stable_handles_invalid"):
        replace(envelope, stable_handles=())
    with pytest.raises(ProjectionError, match="budgets_invalid"):
        replace(envelope, budgets={"bytes": True})
    with pytest.raises(ProjectionError, match="parent_generation_invalid"):
        replace(envelope, parent_generation=1)
    with pytest.raises(ProjectionError, match="capabilities_required_invalid"):
        replace(envelope, capabilities_required=("",))
    with pytest.raises(ProjectionError, match="config_fingerprint_invalid"):
        replace(envelope, config_fingerprint=1)
    with pytest.raises(ProjectionError, match="payload_invalid"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload=[],
        )
    with pytest.raises(ProjectionError, match="projection_size_limit"):
        _canonical("x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(ProjectionError, match="projection_item_limit"):
        _reject_private_fields(list(range(100_001)))
    with pytest.raises(ProjectionError, match="budgets_invalid"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={},
            budgets={"bytes": True},
        )
    with pytest.raises(ProjectionError, match="producer_invalid"):
        replace(envelope, producer="")
    with pytest.raises(ProjectionError, match="projection_text_limit"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={"text": "x" * 4097},
        )
    with pytest.raises(ProjectionError, match="capabilities_required_invalid"):
        replace(envelope, capabilities_required="bad")
    with pytest.raises(ProjectionError, match="truncation_reasons_invalid"):
        replace(envelope, truncation_reasons=("",))
    with pytest.raises(ProjectionError, match="projection_invalid_json"):
        ProjectionEnvelope.decode(b"{")
    missing_digest = json.loads(envelope.encode())
    missing_digest.pop("payload_sha256")
    with pytest.raises(ProjectionError, match="payload_digest_missing"):
        ProjectionEnvelope.decode(json.dumps(missing_digest).encode())
    invalid_payload = json.loads(envelope.encode())
    invalid_payload["payload"] = []
    with pytest.raises(ProjectionError, match="payload_invalid"):
        ProjectionEnvelope.decode(json.dumps(invalid_payload).encode())
    with pytest.raises(ProjectionError, match="projection_invalid_json"):
        ProjectionEnvelope.decode(None)  # type: ignore[arg-type]
    with pytest.raises(ProjectionError, match="payload_not_json"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={"score": float("nan")},
        )
    with pytest.raises(ProjectionError, match="payload_not_json"):
        ProjectionEnvelope.create(
            "code",
            producer="mapper",
            producer_schema="mapper/v1",
            generation="g1",
            stable_handle="x",
            payload={1: "not-a-json-object-key"},  # type: ignore[dict-item]
        )
    with pytest.raises(ProjectionError, match="payload_not_json"):
        _canonical({1: "not-a-json-object-key"})  # type: ignore[dict-item]
    with pytest.raises(ProjectionError, match="payload_sha256_invalid"):
        replace(envelope, payload_sha256="sha256:short")


def test_projection_store_rejects_conflicts_invalid_deltas_and_loads(tmp_path) -> None:
    store = ProjectionStore("repo-a")
    with pytest.raises(ProjectionError, match="projection_envelope_invalid"):
        store.publish(object())  # type: ignore[arg-type]
    with pytest.raises(ProjectionError, match="changed_invalid"):
        store.apply_delta("g1", changed=(object(),))  # type: ignore[tuple-item]
    first = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:a",
        payload={"repository": "repo-a", "name": "a"},
    )
    store.publish(first)
    conflict = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:a",
        payload={"repository": "repo-a", "name": "different"},
    )
    with pytest.raises(ProjectionError, match="projection_handle_conflict"):
        store.publish(conflict)
    with pytest.raises(ProjectionError, match="projection_delta_conflict"):
        store.apply_delta("g1", changed=(first,), deleted_handles=("code:a",))
    changed_generation = ProjectionEnvelope.create(
        "knowledge",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g2",
        stable_handle="knowledge:b",
        payload={"repository": "repo-a"},
    )
    with pytest.raises(ProjectionError, match="projection_generation_stale"):
        store.apply_delta("g1", changed=(changed_generation,))
    with pytest.raises(ProjectionError, match="projection_generation_stale"):
        store.publish(changed_generation)
    path = tmp_path / "store.json"
    store.save(path)
    invalid_cases = [
        ("{", "projection_store_invalid"),
        ("[]", "projection_store_invalid"),
        (json.dumps({"body": {"schema": "wrong"}, "store_sha256": "x"}), "projection_store_schema_unsupported"),
    ]
    for index, (content, reason) in enumerate(invalid_cases):
        candidate = tmp_path / f"invalid-{index}.json"
        candidate.write_text(content, encoding="utf-8")
        with pytest.raises(ProjectionError, match=reason):
            ProjectionStore.load(candidate, "repo-a")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["body"]["records"] = "not-a-list"
    document["store_sha256"] = __import__("simplicio_fast.projection", fromlist=["_digest"])._digest(document["body"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProjectionError, match="projection_store_invalid"):
        ProjectionStore.load(path, "repo-a")
    store.save(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["body"]["generation"] = "g2"
    document["store_sha256"] = __import__("simplicio_fast.projection", fromlist=["_digest"])._digest(document["body"])
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProjectionError, match="projection_generation_mismatch"):
        ProjectionStore.load(path, "repo-a")


def test_projection_generation_swap_never_exposes_mixed_records() -> None:
    store = ProjectionStore("repo-a")
    first = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:a",
        payload={"repository": "repo-a", "name": "a"},
    )
    second = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:b",
        payload={"repository": "repo-a", "name": "b"},
    )
    replacement = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g2",
        stable_handle="code:c",
        payload={"repository": "repo-a", "name": "c"},
    )
    store.publish(first)
    store.publish(second)

    def read_snapshots(_: int) -> set[tuple[str, ...]]:
        observed: set[tuple[str, ...]] = set()
        for _ in range(50):
            records = store.snapshot()
            observed.add(
                tuple(sorted({str(record["generation"]) for record in records}))
            )
        return observed

    with ThreadPoolExecutor(max_workers=20) as pool:
        readers = [pool.submit(read_snapshots, index) for index in range(20)]
        store.apply_delta("g2", base_generation="g1", changed=(replacement,), deleted_handles=("code:a", "code:b"))
        observed = [result.result() for result in readers]

    assert all(generations in {("g1",), ("g2",)} for item in observed for generations in item)
    assert store.generation == "g2"
    assert [record["stable_handle"] for record in store.snapshot()] == ["code:c"]
