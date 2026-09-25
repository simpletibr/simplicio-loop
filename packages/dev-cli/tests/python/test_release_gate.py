from __future__ import annotations

from pathlib import Path

from bench.run_release_gate import run_gate, write_reports


def test_release_gate_runs_with_local_imports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "bench.run_release_gate.verify_runtime_identity",
        lambda: {
            "verified": False,
            "binary": None,
            "reason": "runtime-binary-not-found",
            "product": None,
            "expected_product": "simplicio-runtime",
            "capabilities": [],
        },
    )
    result = run_gate()
    json_path = tmp_path / "release-gate.json"
    md_path = tmp_path / "release-gate.md"

    write_reports(result, json_path, md_path)

    assert result["schema"] == "simplicio.dev-cli.release-gate/v1"
    assert result["proof_kind"] == "deterministic-provider-free"
    assert result["matrix"]["cases"] == 12
    assert result["release_gates"]["deterministic_corpus_complete"] is False
    assert result["metrics"]["cases_passed"] == 1
    assert any(
        case["case_id"] == "planes-ordering" and case["outcome_ok"] is False for case in result["cases"]
    )
    assert "GPT-5.4 medium via Simplicio Runtime live lane" in result["missing_release_evidence"]
    assert json_path.exists()
    assert md_path.exists()
