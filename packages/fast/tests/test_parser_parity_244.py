from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from benchmarks.parser_parity_244 import (
    ParserParityError,
    build_receipt,
    main,
    validate_receipt,
)

ROOT = Path(__file__).parents[1] / "fixtures" / "conformance" / "v1"


def test_receipt_proves_python_legacy_parity_without_native_claims() -> None:
    receipt = build_receipt(ROOT)

    assert receipt["schema"] == "simplicio.fast.parser-parity-receipt/v1"
    assert receipt["status"] == "partial"
    assert receipt["determinism"] == {
        "status": "pass",
        "runs": 2,
        "canonical_bytes_identical": True,
        "adapter_payload_sha256": receipt["determinism"]["adapter_payload_sha256"],
        "declared_payload_sha256": receipt["determinism"]["declared_payload_sha256"],
    }
    assert receipt["python_legacy_parity"]["status"] == "pass"
    assert receipt["python_legacy_parity"]["files"] == [
        {
            **receipt["python_legacy_parity"]["files"][0],
            "path": "python/service.py",
            "status": "pass",
        }
    ]
    assert receipt["native_pending"] == {
        "status": "blocked",
        "reason_code": "native_parser_unavailable",
        "paths": [
            "csharp/Service.cs",
            "rust/service.rs",
            "typescript/service.ts",
        ],
    }
    assert validate_receipt(receipt)["status"] == "valid"


def test_receipt_is_repeatable_and_corpus_mutation_fails_closed(tmp_path: Path) -> None:
    first = build_receipt(ROOT)
    second = build_receipt(ROOT)
    assert first == second

    copy = tmp_path / "v1"
    shutil.copytree(ROOT, copy)
    manifest = json.loads((copy / "corpus.json").read_text(encoding="utf-8"))
    target = copy / "python" / "service.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ParserParityError, match="corpus_digest_mismatch"):
        build_receipt(copy)
    assert manifest["schema"] == "simplicio.fast.golden-corpus/v1"


def test_receipt_validator_rejects_tampered_parity_status() -> None:
    receipt = build_receipt(ROOT)
    receipt["python_legacy_parity"]["status"] = "fail"
    with pytest.raises(ParserParityError, match="receipt_parity_invalid"):
        validate_receipt(receipt)


def test_cli_fails_closed_when_native_parsers_are_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["parser_parity_244"])
    assert main() == 1
