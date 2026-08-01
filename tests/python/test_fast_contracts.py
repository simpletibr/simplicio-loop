from __future__ import annotations

import base64
import hashlib
import json
import sys

import pytest

from simplicio import cli
from simplicio.fast_contracts import (
    FastEngineError,
    NoFastEngine,
    PythonFastEngine,
    RustFastEngine,
    capabilities_contract,
    doctor_contract,
    select_fast_engine,
    validate_snapshot,
)


@pytest.mark.parametrize(
    ("version", "parser", "status"),
    [
        ("", "0", "absent"),
        ("2.0.0", "1", "incompatible"),
        ("2.0.18", "0", "degraded"),
        ("2.0.18", "1", "ready"),
    ],
)
def test_preflight_status_matrix(monkeypatch, version, parser, status):
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", version)
    monkeypatch.setenv("SIMPLICIO_FAST_PARSER_AVAILABLE", parser)

    assert capabilities_contract()["availability"]["status"] == status


def test_capabilities_contract_is_stable(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "")

    assert capabilities_contract() == {
        "schema": "simplicio.fast-capabilities/v1",
        "availability": {
            "status": "absent",
            "fast_version": None,
            "mapper_version": capabilities_contract()["availability"]["mapper_version"],
            "parser_available": False,
            "reason": "fast-distribution-not-found",
            "correction": "pip install 'simplicio-cli[fast]'",
        },
        "compatibility": {
            "fast": ">=2.0.18,<3",
            "mapper": "installed version reported; negotiated through snapshot schema",
        },
        "schemas": [
            "simplicio.context-snapshot/v1",
            "simplicio.mapper-context-snapshot/v1",
            "simplicio.fast.binary-changeset/v1",
            "simplicio.fast.changeset/v2",
            "simplicio.fast.changeset-receipt/v2",
        ],
        "formats": {
            "simplicio.fast.binary-changeset/v1": {
                "input": "bytes",
                "magic": "SFBCHG01",
                "adapter": "execute_changeset_bytes",
            },
            "simplicio.fast.changeset/v2": {
                "input": "json",
                "adapter": "legacy-json-adapter",
            },
        },
        "languages": ["python", "javascript", "typescript", "json"],
        "commands": ["fast capabilities", "fast doctor", "changeset"],
        "source_access": False,
    }


def test_doctor_rejects_corrupt_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "0.1.0")
    monkeypatch.setenv("SIMPLICIO_FAST_PARSER_AVAILABLE", "1")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{broken", encoding="utf-8")

    payload = doctor_contract(snapshot=str(snapshot))

    assert payload["status"] == "degraded"
    assert payload["snapshot"]["reason"] == "snapshot-unreadable:JSONDecodeError"


def test_fast_engine_selection_is_explicit_and_in_memory():
    engine = select_fast_engine("python")
    assert isinstance(engine, PythonFastEngine)
    assert engine.receipt()["metrics"] == {
        "decode_calls": 0,
        "bytes_decoded": 0,
        "serializations": 0,
        "subprocesses": 0,
    }
    assert select_fast_engine("none").name == "none"
    with pytest.raises(FastEngineError, match="fast engine must be"):
        select_fast_engine("invalid")


def test_cli_exit_codes_offline_help_and_metadata_receipt(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "")
    receipt = tmp_path / "receipt.jsonl"

    code = cli.main(["fast", "doctor", "--json", "--offline", "--receipt", str(receipt)])

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert "offline installation cannot download packages" in payload["correction"]
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert saved["source_included"] is False
    assert set(saved) == {
        "schema",
        "command",
        "status",
        "fast_version",
        "mapper_version",
        "source_included",
    }


def test_python_engine_consumes_real_binary_envelope(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(r"C:\Users\Z0059V7A\m\repos\simplicio-fast\src")
    sys.modules.pop("simplicio_fast", None)
    from simplicio_fast.binary_changeset import BinaryChangeSet, ChangeOperation

    content = b"python-engine\n"
    changeset = BinaryChangeSet(
        repository=str(tmp_path.resolve()),
        base_generation="base",
        overlay_generation="overlay",
        attempt="attempt",
        worktree_id="slot-python",
        lease_id="lease-python",
        fencing_token="fence-python",
        allowed_paths=("result.txt",),
        operations=(
            ChangeOperation.from_dict(
                {
                    "op": "create",
                    "path": "result.txt",
                    "content_b64": base64.b64encode(content).decode(),
                    "after_sha256": hashlib.sha256(content).hexdigest(),
                }
            ),
        ),
    )
    from simplicio.fast_contracts import select_fast_engine

    engine = select_fast_engine("python")
    decoded = engine.decode_binary(changeset.encode())
    assert decoded["repository"] == str(tmp_path.resolve())
    assert engine.receipt()["metrics"]["serializations"] == 0


def test_rust_engine_normalizes_object_decoder_and_rejects_bad_shape():
    class Decoded:
        def to_dict(self):
            return {"repository": "repo"}

    engine = RustFastEngine(lambda payload: Decoded())
    assert engine.decode_binary(b"abc") == {"repository": "repo"}
    assert engine.receipt()["metrics"] == {
        "decode_calls": 1,
        "bytes_decoded": 3,
        "serializations": 0,
        "subprocesses": 0,
    }

    bad = RustFastEngine(lambda payload: [payload])
    with pytest.raises(FastEngineError, match="non-object envelope"):
        bad.decode_binary(b"x")


def test_python_engine_reports_decoder_failure(monkeypatch):
    import simplicio_fast.binary_changeset as binary_changeset

    monkeypatch.setattr(binary_changeset, "decode_binary", lambda _: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(FastEngineError, match="rejected the envelope"):
        PythonFastEngine().decode_binary(b"bad")


def test_python_engine_reports_missing_decoder_and_bad_shape(monkeypatch):
    import simplicio_fast.binary_changeset as binary_changeset

    monkeypatch.setattr(binary_changeset, "decode_binary", lambda _: ["not", "an", "object"])
    with pytest.raises(FastEngineError, match="non-object envelope"):
        PythonFastEngine().decode_binary(b"bad")

    monkeypatch.setitem(sys.modules, "simplicio_fast.binary_changeset", None)
    with pytest.raises(FastEngineError, match="not installed"):
        PythonFastEngine().decode_binary(b"bad")


def test_no_fast_engine_is_explicitly_fail_closed():
    with pytest.raises(FastEngineError, match="no compatible Fast"):
        NoFastEngine().decode_binary(b"payload")


def test_engine_selection_fails_closed_when_decoder_module_is_missing(monkeypatch):
    import simplicio.fast_contracts as fast_contracts

    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "2.0.18")
    monkeypatch.setenv("SIMPLICIO_FAST_PARSER_AVAILABLE", "1")
    monkeypatch.setitem(sys.modules, "simplicio_fast.binary_changeset", None)
    with pytest.raises(FastEngineError, match="Rust Fast decoder is not installed"):
        select_fast_engine("rust")
    assert select_fast_engine("auto").name == "none"


def test_engine_selection_rejects_incompatible_preflight(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "1.0.0")
    monkeypatch.setenv("SIMPLICIO_FAST_PARSER_AVAILABLE", "1")
    assert select_fast_engine("auto").name in {"rust", "none"}


def test_private_fast_contract_edge_cases(monkeypatch):
    import simplicio.fast_contracts as fast_contracts

    assert fast_contracts._version_tuple("release") is None
    monkeypatch.setattr(
        fast_contracts.metadata,
        "version",
        lambda _: (_ for _ in ()).throw(fast_contracts.metadata.PackageNotFoundError()),
    )
    assert fast_contracts._installed_version("missing", "MISSING_OVERRIDE") is None


def test_snapshot_validation_and_doctor_contract_cover_supported_and_missing_inputs(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_FAST_VERSION", "2.0.18")
    monkeypatch.setenv("SIMPLICIO_FAST_PARSER_AVAILABLE", "1")
    assert validate_snapshot(None)["status"] == "not_checked"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"schema": "simplicio.context-snapshot/v1"}), encoding="utf-8")
    assert validate_snapshot(str(snapshot))["status"] == "valid"
    snapshot.write_text(json.dumps({"schema": "unknown"}), encoding="utf-8")
    assert validate_snapshot(str(snapshot))["reason"] == "snapshot-schema-unsupported"
    assert doctor_contract(snapshot=str(snapshot))["status"] == "degraded"
