from __future__ import annotations

import base64
import hashlib
import json
import sys

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
