from __future__ import annotations

import json

import pytest

from simplicio import cli
from simplicio.fast_contracts import (
    FastEngineError,
    PythonFastEngine,
    capabilities_contract,
    doctor_contract,
    select_fast_engine,
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
            "simplicio.fast.changeset/v2",
            "simplicio.fast.changeset-receipt/v2",
        ],
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
    assert engine.decode_binary(b'{"generation":"g"}') == {"generation": "g"}
    assert engine.receipt()["metrics"] == {
        "decode_calls": 1,
        "bytes_decoded": 18,
        "serializations": 1,
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
