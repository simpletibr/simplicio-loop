import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from simplicio_fast.snapshot import build_snapshot
from simplicio_fast.snapshot import Snapshot
from simplicio_fast.rust_session import READ_ONLY_OPERATIONS, RustCoreSession, RustSessionError, _canonical


def _run_json(executable: Path, *args: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-rust-query-") as directory:
        stdout = Path(directory) / "stdout.json"
        stderr = Path(directory) / "stderr.txt"
        with stdout.open("w", encoding="utf-8") as out, stderr.open(
            "w", encoding="utf-8"
        ) as err:
            result = subprocess.run(
                [str(executable), *args],
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                text=True,
                check=False,
            )
        assert result.returncode == 0, stderr.read_text(encoding="utf-8")
        return json.loads(stdout.read_text(encoding="utf-8"))


def _run_session(executable: Path, requests: list[dict[str, object]]) -> list[dict[str, object]]:
    process = subprocess.Popen(
        [str(executable), "--session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    handshake = json.loads(process.stdout.readline())
    assert handshake["schema"] == "simplicio.fast.engine-session/v1"
    assert handshake["abi"] == handshake["schema"]
    assert handshake["engine_version"]
    assert "simplicio.fast.context/v1" in handshake["schemas"]
    assert "simplicio.fast.relations/v1" in handshake["schemas"]
    assert handshake["binary_digest"].startswith("sha256:")
    assert handshake["source_commit"]
    assert handshake["conformance_digest"].startswith("sha256:")
    assert handshake["platform"]
    assert handshake["nonce"]
    responses = []
    for request in requests:
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        responses.append(json.loads(process.stdout.readline()))
    process.stdin.close()
    process.wait(timeout=10)
    assert process.returncode == 0
    return responses


def _symbol_key(value: dict[str, object]) -> tuple[object, ...]:
    return (
        value["qualified_name"],
        value["kind"],
        value["file"],
        value["line"],
    )


def _python_symbol_key(value: object) -> tuple[object, ...]:
    return (value.qualified_name, value.kind, value.file, value.line)


def test_rust_query_receipt_uses_exact_and_prefix_indexes(tmp_path: Path) -> None:
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is required for Rust query receipt E2E")
    root = Path(__file__).parents[1]
    subprocess.run(
        [cargo, "build", "--manifest-path", "rust/simplicio-fast-core/Cargo.toml", "--locked", "--quiet"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
    )
    executable = root / "rust" / "target" / "debug" / (
        "simplicio-fast-rs.exe"
        if shutil.which("cmd.exe")
        else "simplicio-fast-rs"
    )
    assert executable.is_file()
    (tmp_path / "a.py").write_text(
        "def helper():\n    return True\n\ndef helper_two():\n    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text("def helper():\n    return False\n", encoding="utf-8")
    snapshot = tmp_path / "service.sfast"
    build_snapshot(tmp_path, snapshot)

    exact = _run_json(executable, "--query", str(snapshot), "helper", "--limit", "1")
    prefix = _run_json(executable, "--query", str(snapshot), "help", "--limit", "1")
    by_path = _run_json(
        executable,
        "--query",
        str(snapshot),
        "helper",
        "--path",
        "b.py",
        "--limit",
        "1",
    )
    by_kind = _run_json(
        executable,
        "--query",
        str(snapshot),
        "helper",
        "--kind",
        "function",
        "--limit",
        "1",
    )
    relations = _run_json(
        executable,
        "--relations",
        str(snapshot),
        "--kind",
        "definition",
        "--limit",
        "20",
    )
    limited_relations = _run_json(
        executable,
        "--relations",
        str(snapshot),
        "--kind",
        "definition",
        "--limit",
        "1",
    )
    handle_relations = _run_json(
        executable,
        "--relations",
        str(snapshot),
        "--handle",
        "helper",
        "--limit",
        "20",
    )
    assert exact["planner"]["selected_index"] == "persisted.exact"
    assert prefix["planner"]["selected_index"] == "persisted.prefix"
    assert by_path["planner"]["selected_index"] == "persisted.exact+path"
    assert by_kind["planner"]["selected_index"] == "persisted.exact+kind"
    assert by_path["matches"][0]["file"] == "b.py"
    assert by_kind["matches"][0]["kind"] == "function"
    assert relations["schema"] == "simplicio.fast.relations/v1"
    assert relations["relations"]
    assert all(item["kind"] == "definition" for item in relations["relations"])
    assert len(limited_relations["relations"]) <= 1
    assert handle_relations["relations"]
    assert all(
        item["origin"] == "helper" or item["destination"] == "helper"
        or item.get("origin_id") == "helper" or item.get("destination_id") == "helper"
        for item in handle_relations["relations"]
    )
    assert exact["planner"]["records_decoded"] == 1
    assert prefix["planner"]["records_decoded"] == 1
    with Snapshot(snapshot) as python_snapshot:
        python_exact = python_snapshot.search("helper")[:1]
        python_prefix = python_snapshot.search("help", prefix=True)[:1]
    assert [match["qualified_name"] for match in exact["matches"]] == [
        symbol.qualified_name for symbol in python_exact
    ]
    assert [match["qualified_name"] for match in prefix["matches"]] == [
        symbol.qualified_name for symbol in python_prefix
    ]

    context = _run_json(
        executable,
        "--context",
        str(snapshot),
        str(tmp_path),
        "hel",
        "--limit",
        "3",
    )
    assert context["planner"]["source_files_read"] == 2
    assert context["planner"]["source_cache_hits"] == 1
    assert context["planner"]["source_bytes_read"] > 0

    first_page = _run_json(
        executable, "--query", str(snapshot), "helper", "--limit", "1"
    )
    cursor = first_page["planner"]["next_cursor"]
    assert isinstance(cursor, str) and cursor.isdigit()
    second_page = _run_json(
        executable,
        "--query",
        str(snapshot),
        "helper",
        "--limit",
        "1",
        "--cursor",
        cursor,
    )
    assert second_page["matches"]
    assert second_page["matches"][0]["file"] != first_page["matches"][0]["file"]
    assert second_page["planner"]["records_decoded"] == 1

    session_responses = _run_session(
        executable,
        [
            {
                "operation": "query",
                "payload": {"snapshot": str(snapshot), "term": "helper", "limit": 1},
            },
            {
                "operation": "query",
                "payload": {"snapshot": str(snapshot), "term": "help", "limit": 1},
            },
            {
                "operation": "relations",
                "payload": {"snapshot": str(snapshot), "kind": "definition", "limit": 20},
            },
            {"operation": "session_cache_stats", "payload": {}},
            {
                "operation": "query",
                "payload": {
                    "snapshot": str(snapshot),
                    "term": "helper",
                    "limit": 1,
                    "generation": "SFAST001:" + "0" * 64,
                },
            },
        ],
    )
    assert session_responses[0]["ok"] and session_responses[1]["ok"]
    assert session_responses[2]["ok"]
    assert session_responses[2]["result"]["relations"]
    assert session_responses[3] == {"ok": True, "result": {"snapshots": 1}}
    assert session_responses[4] == {"ok": False, "reason": "generation_mismatch"}

    with RustCoreSession(executable) as session:
        result = session.call(
            "query",
            {"snapshot": str(snapshot), "term": "helper", "limit": 1},
        )
        assert result["planner"]["records_decoded"] == 1
        relation_result = session.call(
            "relations",
            {"snapshot": str(snapshot), "kind": "definition", "limit": 20},
        )
        assert relation_result["relations"]
        assert session.call("session_cache_stats", {}) == {"snapshots": 1}
        process = session._process
        process.kill()
        assert session.call(
            "query", {"snapshot": str(snapshot), "term": "helper", "limit": 1}
        )["planner"]["records_decoded"] == 1
        assert session.call("session_cache_stats", {}) == {"snapshots": 1}
        metrics = session.metrics()
        assert metrics["starts"] == 2
        assert metrics["reconnects"] == 1
        assert metrics["retries"] == 1
        assert metrics["failures"] == 1
        assert metrics["requests"] == 5
        assert metrics["bytes_in"] > 0
        assert metrics["bytes_out"] > 0
        assert metrics["wall_ms"] >= 0
        assert metrics["mapped_generations"] == 1
        assert metrics["cache_hits"] == 2
    assert session.closed
    with pytest.raises(RustSessionError, match="session_closed"):
        session.call("stats", {})
    session.close()

    with RustCoreSession(executable) as non_read_only_session:
        non_read_only_session.restart()
        non_read_only_session._process.kill()
        with pytest.raises(RustSessionError, match="session_operation_invalid"):
            non_read_only_session.call("write", {})
        metrics = non_read_only_session.metrics()
        assert metrics["starts"] == 2
        assert metrics["reconnects"] == 1
        assert metrics["retries"] == 0

    with RustCoreSession(executable) as concurrent_session:
        def read_query(_: int) -> int:
            result = concurrent_session.call(
                "query",
                {"snapshot": str(snapshot), "term": "helper", "limit": 1},
            )
            return int(result["planner"]["records_decoded"])

        with ThreadPoolExecutor(max_workers=20) as pool:
            decoded = list(pool.map(read_query, range(20)))
        assert decoded == [1] * 20
        assert concurrent_session.call("session_cache_stats", {}) == {"snapshots": 1}
        concurrent_metrics = concurrent_session.metrics()
        assert concurrent_metrics["starts"] == 1
        assert concurrent_metrics["requests"] == 21
        assert concurrent_metrics["mapped_generations"] == 1


def test_resident_handshake_rejects_manifest_version_drift() -> None:
    handshake = {
        "schema": "simplicio.fast.engine-session/v1",
        "abi": "simplicio.fast.engine-session/v1",
        "engine": "rust",
        "status": "ready",
        "engine_version": "2.0.20",
        "schemas": ["simplicio.fast.context/v1"],
        "capabilities": sorted(READ_ONLY_OPERATIONS),
        "binary_digest": "sha256:" + "0" * 64,
        "source_commit": "a" * 40,
        "conformance_digest": "sha256:" + "1" * 64,
        "platform": "windows-x86_64",
        "nonce": "nonce",
    }
    with pytest.raises(RustSessionError, match="session_version_mismatch"):
        RustCoreSession._validate_handshake(
            handshake, {"version": "2.0.21"}
        )


def test_resident_handshake_rejects_empty_identity_and_invalid_call_frames() -> None:
    handshake = {
        "schema": "simplicio.fast.engine-session/v1",
        "abi": "simplicio.fast.engine-session/v1",
        "engine": "rust",
        "status": "ready",
        "engine_version": "2.0.20",
        "schemas": ["simplicio.fast.context/v1"],
        "capabilities": sorted(READ_ONLY_OPERATIONS),
        "binary_digest": "sha256:" + "0" * 64,
        "source_commit": "a" * 40,
        "conformance_digest": "sha256:" + "1" * 64,
        "platform": "windows-x86_64",
        "nonce": "nonce",
    }
    for field in ("binary_digest", "source_commit", "conformance_digest", "platform", "nonce"):
        invalid = {**handshake, field: " "}
        with pytest.raises(RustSessionError, match="session_handshake_invalid"):
            RustCoreSession._validate_handshake(invalid)
    with pytest.raises(RustSessionError, match="session_capabilities_invalid"):
        RustCoreSession._validate_handshake({**handshake, "capabilities": ["stats", 1, "context"]})
    session = object.__new__(RustCoreSession)
    with pytest.raises(RustSessionError, match="session_operation_invalid"):
        session.call("", {})
    with pytest.raises(RustSessionError, match="session_operation_invalid"):
        session.call("write", {})
    with pytest.raises(RustSessionError, match="session_payload_invalid"):
        session.call("query", [])
    with pytest.raises(RustSessionError, match="session_payload_invalid"):
        _canonical({"invalid": object()})
    with pytest.raises(RustSessionError, match="session_payload_invalid"):
        _canonical({"invalid": float("nan")})


def test_resident_handshake_rejects_non_object_root() -> None:
    with pytest.raises(RustSessionError, match="session_handshake_invalid"):
        RustCoreSession._validate_handshake([])  # type: ignore[arg-type]


def test_rust_queries_match_python_on_frozen_conformance_golden(tmp_path: Path) -> None:
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo is required for frozen conformance parity")
    root = Path(__file__).parents[1]
    subprocess.run(
        [cargo, "build", "--manifest-path", "rust/simplicio-fast-core/Cargo.toml", "--locked", "--quiet"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
    )
    executable = root / "rust" / "target" / "debug" / (
        "simplicio-fast-rs.exe" if shutil.which("cmd.exe") else "simplicio-fast-rs"
    )
    fixture_root = root / "fixtures" / "conformance" / "v1"
    snapshot = tmp_path / "conformance.sfast"
    build_snapshot(fixture_root, snapshot)

    cases = [
        ("resolve", {}, "exact"),
        ("res", {}, "prefix"),
        ("resolve_number", {"--path": "rust/service.rs", "--kind": "function"}, "exact+path+kind"),
    ]
    with Snapshot(snapshot) as python_snapshot:
        for term, filters, selected_index in cases:
            rust = _run_json(
                executable,
                "--query",
                str(snapshot),
                term,
                *[argument for pair in filters.items() for argument in pair],
                "--limit",
                "50",
            )
            if selected_index == "prefix":
                expected = python_snapshot.search(term, prefix=True)
            else:
                expected = python_snapshot.find_exact(term)
                if "--path" in filters:
                    expected = [item for item in expected if item.file == filters["--path"]]
                if "--kind" in filters:
                    expected = [item for item in expected if item.kind == filters["--kind"]]
            assert rust["planner"]["selected_index"] == f"persisted.{selected_index}"
            assert rust["planner"]["records_decoded"] == len(expected)
            assert sorted(_symbol_key(item) for item in rust["matches"]) == sorted(
                _python_symbol_key(item) for item in expected
            )
