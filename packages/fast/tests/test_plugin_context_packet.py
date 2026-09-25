from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from simplicio_fast.hbp_codec import seal_receipt
from simplicio_fast.plugin_context_packet import (
    ABI_MAJOR,
    HANDLE_SCHEMA,
    HBP_SCHEMA,
    PACKET_SCHEMA,
    PluginContextBudget,
    PluginContextError,
    PluginContextHandle,
    PluginContextRequest,
    PluginContextStore,
    contract_manifest,
    decode_hbp,
    encode_hbp,
    measure_compile,
    negotiate_abi,
    validate_relative_path,
    verify_packet,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "plugin-context-packet" / "v1"
FIXTURES = ROOT / "fixtures" / "plugin-context-packet" / "v1"


def _files() -> dict[str, bytes]:
    return {
        "src/app.py": b"class UserService:\n    def get(self):\n        return 1\n",
        "src/auth.py": b"SECRET = 'x'\n",
        "README.md": b"# demo\n",
    }


def _store(files: dict[str, bytes] | None = None) -> PluginContextStore:
    store = PluginContextStore()
    store.load_generation(
        generation="g1",
        repo="wesleysimplicio/simplicio-fast",
        commit="c" * 40,
        files=files or _files(),
        spans={
            "plugin:src/app.py:UserService": {
                "path": "src/app.py",
                "kind": "symbol",
                "start_line": 1,
                "end_line": 3,
                "start_offset": 0,
                "end_offset": len((files or _files())["src/app.py"]),
            }
        },
    )
    store.pin("task-1", "session-1", "g1")
    return store


def _handle(**overrides: object) -> PluginContextHandle:
    payload = {
        "handle": "plugin:src/app.py:UserService",
        "generation": "g1",
        "source_ref": "c" * 40,
    }
    payload.update(overrides)
    return PluginContextHandle(
        handle=str(payload["handle"]),
        generation=str(payload["generation"]),
        source_ref=str(payload["source_ref"]),
        overlay_id=payload.get("overlay_id"),  # type: ignore[arg-type]
    )


def _request(store: PluginContextStore | None = None, **overrides: object) -> PluginContextRequest:
    kwargs = {
        "task_id": "task-1",
        "session_id": "session-1",
        "handle": _handle(),
        "budget": PluginContextBudget(4096, 8, 2048, "exact"),
        "requested_handles": ("plugin:src/app.py:UserService",),
    }
    kwargs.update(overrides)
    return PluginContextRequest(**kwargs)  # type: ignore[arg-type]


def test_negotiate_abi_rejects_unknown_major() -> None:
    assert negotiate_abi() == {"major": 1, "minor": 0}
    assert negotiate_abi({"major": 1, "minor": 0})["major"] == ABI_MAJOR
    with pytest.raises(PluginContextError, match="plugin_abi_unsupported"):
        negotiate_abi({"major": 2, "minor": 0})


def test_handle_digest_is_canonical_and_tamper_evident() -> None:
    first = _handle()
    second = PluginContextHandle.from_mapping(first.to_dict())
    assert first.digest == second.digest
    assert first.to_dict()["schema"] == HANDLE_SCHEMA
    tampered = first.to_dict()
    tampered["digest"] = "0" * 64
    with pytest.raises(PluginContextError, match="handle_tampered"):
        PluginContextHandle.from_mapping(tampered)


def test_generation_pin_source_change_and_overlay_isolation() -> None:
    store = _store()
    base = store.compile(_request())
    assert base["generation"] == "g1"
    assert "class UserService" in base["spans"][0]["text"]
    store.apply_overlay("g1", "dirty-1", {"src/app.py": b"class UserService:\n    pass\n"})
    overlay = store.compile(
        _request(handle=_handle(overlay_id="dirty-1"))
    )
    assert overlay["overlay_id"] == "dirty-1"
    assert overlay["spans"][0]["text"] == "class UserService:\n    pass\n"
    still_base = store.compile(_request())
    assert still_base["spans"][0]["text"].startswith("class UserService:\n    def get")
    assert still_base["source_hashes"]["src/app.py"] != overlay["source_hashes"]["src/app.py"]
    with pytest.raises(PluginContextError, match="source_hash_mismatch"):
        store.compile(
            _request(
                handle=_handle(overlay_id="dirty-1"),
                expected_source_hashes={"src/app.py": still_base["source_hashes"]["src/app.py"]},
            )
        )
    store.load_generation(
        generation="g2",
        repo="wesleysimplicio/simplicio-fast",
        commit="d" * 40,
        files=_files(),
    )
    with pytest.raises(PluginContextError, match="generation_stale"):
        store.pin("task-1", "session-1", "g2")
    with pytest.raises(PluginContextError, match="generation_missing"):
        store.pin("task-1", "session-1", "g-missing")


def test_byte_and_fidelity_budgets_are_exact() -> None:
    store = _store()
    exact = store.compile(_request(budget=PluginContextBudget(4096, 8, 2048, "exact")))
    summary = store.compile(_request(budget=PluginContextBudget(4096, 8, 2048, "summary")))
    metadata = store.compile(_request(budget=PluginContextBudget(4096, 8, 2048, "metadata")))
    assert exact["fidelity"] == "exact"
    assert "class UserService" in exact["spans"][0]["text"]
    assert summary["payload"]["items"][0]["preview"]
    assert metadata["payload"]["handles"] == ["plugin:src/app.py:UserService"]
    assert metadata["spans"][0]["text"] is None
    tiny = store.compile(_request(budget=PluginContextBudget(4096, 1, 12, "exact")))
    assert tiny["truncated"] is True
    assert "span_budget" in tiny["truncation_reasons"]
    assert tiny["spans"][0]["byte_length"] == 12
    assert tiny["encoded_bytes"] <= 4096
    squeezed = store.compile(_request(budget=PluginContextBudget(1500, 8, 2048, "exact")))
    assert squeezed["truncated"] is True
    assert "byte_budget" in squeezed["truncation_reasons"]
    assert squeezed["encoded_bytes"] <= 1500


def test_span_budget_reports_delivered_range_and_distinct_content_hash() -> None:
    store = _store()
    packet = store.compile(
        _request(budget=PluginContextBudget(4096, 1, 12, "exact"))
    )
    span = packet["spans"][0]
    assert span["requested_start_line"] == 1
    assert span["requested_end_line"] == 3
    assert span["start_line"] == 1
    assert span["end_line"] == 1
    assert span["fidelity"] == "partial"
    assert span["needs_broader_context"] is True
    assert span["source_sha256"] != span["content_sha256"]
    assert span["end_byte"] - span["start_byte"] == span["byte_length"]
    assert span["omitted_ranges"] == [[1, 3]]


def test_cache_cold_warm_and_invalidation() -> None:
    store = _store()
    first = store.compile(_request())
    second = store.compile(_request())
    assert first["cache_status"] == "cold"
    assert second["cache_status"] == "warm"
    assert first["packet_hash"] == second["packet_hash"]
    removed = store.invalidate(["src/app.py"])
    assert removed
    third = store.compile(_request())
    assert third["cache_status"] == "cold"
    receipt = store.cache_receipt()
    assert receipt["hit"] == 1
    assert receipt["miss"] >= 2
    assert receipt["invalidation"] == len(removed)


def test_tamper_path_escape_and_stale_handle() -> None:
    store = _store()
    packet = store.compile(_request())
    packet["spans"][0]["text"] = "mutated"
    with pytest.raises(PluginContextError, match="packet_corrupt"):
        verify_packet(packet)
    with pytest.raises(PluginContextError, match="path_escape"):
        validate_relative_path("../secret")
    with pytest.raises(PluginContextError, match="path_escape"):
        store.load_generation(
            generation="g2", repo="r", commit="c", files={"C:/Windows/system32": b"x"}
        )
    with pytest.raises(PluginContextError, match="path_escape"):
        store.apply_overlay("g1", "bad", {"../escape.py": b"x"})
    with pytest.raises(PluginContextError, match="generation_stale"):
        store.compile(_request(handle=_handle(generation="g-other")))
    with pytest.raises(PluginContextError, match="handle_missing"):
        store.compile(_request(requested_handles=("plugin:missing",)))
    with pytest.raises(PluginContextError, match="generation_missing"):
        store.compile(
            PluginContextRequest(
                task_id="other-task",
                session_id="session-1",
                handle=_handle(),
                budget=PluginContextBudget(1024, 1, 128, "exact"),
            )
        )


def test_private_offsets_and_unknown_schema_are_rejected() -> None:
    store = _store()
    packet = store.compile(_request())
    packet["payload"] = {"mmap_offset": 4, "spans": packet["payload"]["spans"]}
    packet.pop("packet_hash")
    with pytest.raises(PluginContextError, match="private_layout_field"):
        verify_packet({**packet, "packet_hash": "x"})
    with pytest.raises(PluginContextError, match="plugin_schema_unsupported"):
        PluginContextHandle.from_mapping(
            {"schema": "simplicio.plugin.context-handle/v2", "handle": "h", "generation": "g", "source_ref": "c"}
        )


def test_large_repo_serves_handle_without_whole_pack_copy() -> None:
    files = {f"src/mod_{index:04d}.py": f"VALUE = {index}\n".encode() for index in range(400)}
    files["src/app.py"] = _files()["src/app.py"]
    store = PluginContextStore()
    store.load_generation(
        generation="g-large",
        repo="repo",
        commit="d" * 40,
        files=files,
        spans={
            "plugin:src/app.py:UserService": {
                "path": "src/app.py",
                "kind": "symbol",
                "start_line": 1,
                "end_line": 3,
                "start_offset": 0,
                "end_offset": len(files["src/app.py"]),
            }
        },
    )
    store.pin("task-large", "session-1", "g-large")
    packet = store.compile(
        PluginContextRequest(
            task_id="task-large",
            session_id="session-1",
            handle=PluginContextHandle(
                "plugin:src/app.py:UserService", "g-large", "d" * 40
            ),
            budget=PluginContextBudget(2048, 1, 512, "exact"),
            requested_handles=("plugin:src/app.py:UserService",),
        )
    )
    assert packet["spans"][0]["path"] == "src/app.py"
    assert len(packet["spans"]) == 1
    assert packet["encoded_bytes"] < 2048
    assert "mod_0000" not in json.dumps(packet)
    sliced = store.slice(packet, "plugin:src/app.py:UserService")
    assert sliced["byte_length"] == len(files["src/app.py"])


def test_python_hbp_semantic_parity_and_golden_vectors() -> None:
    store = _store()
    packet = store.compile(_request())
    row = encode_hbp(packet)
    decoded = decode_hbp(row)
    assert decoded["packet_hash"] == packet["packet_hash"]
    assert decoded["schema"] == PACKET_SCHEMA
    assert HBP_SCHEMA in row
    golden = json.loads((CONTRACT / "golden-vectors.json").read_text(encoding="utf-8"))
    handle = _handle()
    assert handle.digest == golden["vectors"]["handle_digest"]
    assert packet["packet_hash"] == golden["vectors"]["packet_hash"]
    assert row == golden["vectors"]["hbp_row"]
    fixture = json.loads((FIXTURES / "single-span.json").read_text(encoding="utf-8"))
    verify_packet(fixture)
    assert fixture["packet_hash"] == packet["packet_hash"]


def test_cancellation_and_missing_generation_fail_closed() -> None:
    store = _store()
    with pytest.raises(PluginContextError, match="cancellation_requested"):
        store.compile(_request(cancelled=lambda: True))
    with pytest.raises(PluginContextError, match="generation_missing"):
        store.pin("t", "s", "missing")
    with pytest.raises(PluginContextError, match="generation_tampered"):
        store.load_generation(
            generation="g1",
            repo="other",
            commit="c" * 40,
            files=_files(),
        )


def test_load_tree_indexes_relative_files_and_rejects_escape() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "src").mkdir()
        (root / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
        store = PluginContextStore()
        store.load_tree(generation="g-tree", repo="r", commit="c", root=root)
        store.pin("task-tree", "session-1", "g-tree")
        packet = store.compile(
            PluginContextRequest(
                task_id="task-tree",
                session_id="session-1",
                handle=PluginContextHandle("plugin:src/ok.py", "g-tree", "c"),
                budget=PluginContextBudget(2048, 4, 512, "exact"),
            )
        )
        assert packet["spans"][0]["path"] == "src/ok.py"
    with pytest.raises(PluginContextError, match="path_escape"):
        PluginContextStore().load_generation(
            generation="g-escape",
            repo="r",
            commit="c",
            files={"../outside.py": b"nope"},
        )
    with pytest.raises(PluginContextError, match="generation_missing"):
        PluginContextStore().load_tree(
            generation="g-missing-root", repo="r", commit="c", root="definitely-missing-root"
        )


def test_metadata_mode_lists_handles_without_copying_text() -> None:
    store = _store()
    packet = store.compile(
        _request(
            handle=_handle(handle="plugin:catalog"),
            requested_handles=(),
            budget=PluginContextBudget(4096, 8, 128, "metadata"),
        )
    )
    assert packet["fidelity"] == "metadata"
    assert packet["payload"]["handles"]
    assert all(span["text"] is None for span in packet["spans"])


def test_latency_bytes_and_optional_rss_are_measured() -> None:
    store = _store()
    report = measure_compile(store, _request(), iterations=21)
    assert report["iterations"] == 21
    assert report["p50_ns"] > 0
    assert report["p95_ns"] >= report["p50_ns"]
    assert report["p99_ns"] >= report["p95_ns"]
    assert len(report["raw_ns"]) == 21
    assert report["encoded_bytes"] > 0
    if report["rss_kib"] is None:
        assert report["rss_kib_null_reason"] == "RSS_UNAVAILABLE"
    else:
        assert report["rss_kib"] >= 0
        assert report["rss_kib_null_reason"] is None


def test_contract_manifest_and_runtime_fixture_are_read_only() -> None:
    manifest = contract_manifest()
    assert manifest["writes"] is False
    assert manifest["authority"] == "derived_read_only"
    schema = json.loads((CONTRACT / "schema.json").read_text(encoding="utf-8"))
    assert schema["schema"] == PACKET_SCHEMA
    consumer = json.loads((FIXTURES / "runtime-consumer.json").read_text(encoding="utf-8"))
    assert consumer["producer"] == "simplicio-fast"
    assert consumer["writes"] is False
    packet = json.loads((FIXTURES / "single-span.json").read_text(encoding="utf-8"))
    assert packet["provenance"]["writes"] is False
    verify_packet(packet, expected_generation="g1")


def test_compile_is_deterministic_across_runs() -> None:
    first = _store().compile(_request())
    second = _store().compile(_request())
    assert first["packet_hash"] == second["packet_hash"]
    assert first["encoded_bytes"] == second["encoded_bytes"]


def test_overlay_tombstone_and_missing_overlay_fail_closed() -> None:
    store = _store()
    store.apply_overlay("g1", "tomb", {"src/app.py": None})
    with pytest.raises(PluginContextError, match="slice_missing"):
        store.compile(_request(handle=_handle(overlay_id="tomb")))
    with pytest.raises(PluginContextError, match="overlay_escape"):
        store.compile(_request(handle=_handle(overlay_id="absent")))
    with pytest.raises(PluginContextError, match="generation_missing"):
        store.apply_overlay("missing", "x", {"src/app.py": b"x"})


def test_hbp_and_packet_verification_fail_closed() -> None:
    store = _store()
    packet = store.compile(_request())
    with pytest.raises(PluginContextError, match="packet_schema_invalid"):
        verify_packet({"schema": "nope"})
    with pytest.raises(PluginContextError, match="generation_stale"):
        verify_packet(packet, expected_generation="other")
    with pytest.raises(PluginContextError, match="packet_corrupt"):
        decode_hbp("")
    with pytest.raises(PluginContextError, match="plugin_schema_unsupported"):
        decode_hbp(seal_receipt("schema=other.schema/v1|kind=packet|digest=x|payload=e30="))
    with pytest.raises(PluginContextError, match="slice_missing"):
        store.slice(packet, "plugin:missing")
    with pytest.raises(PluginContextError, match="budget_invalid"):
        measure_compile(store, _request(), iterations=0)
    budget = PluginContextBudget.from_mapping(None)
    assert budget.fidelity == "exact"
    with pytest.raises(PluginContextError, match="budget_invalid"):
        PluginContextBudget.from_mapping("nope")
    with pytest.raises(PluginContextError, match="plugin_abi_unsupported"):
        negotiate_abi("1.0")
    with pytest.raises(PluginContextError, match="handle_missing"):
        PluginContextHandle.from_mapping("nope")
    with pytest.raises(PluginContextError, match="generation_tampered"):
        store.load_generation(
            generation="g-bad", repo="r", commit="c", files={"src/app.py": "not-bytes"}
        )
