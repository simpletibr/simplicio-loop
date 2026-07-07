from __future__ import annotations

import json
from pathlib import Path

from bench.run_schema_smoke_summary import (
    REQUIRED_QUANT_SMOKES,
    _passes_smoke,
    main,
    summarize_smokes,
    write_reports,
)


def test_schema_smoke_summary_normalizes_supported_formats(tmp_path):
    schema_v1 = tmp_path / "results_v14_qwen15b_q8_0_smoke_schema_v1.json"
    schema_v1.write_text(
        json.dumps(
            {
                "benchmark": "schema-v1-smoke",
                "model": "Qwen2.5-Coder-1.5B-Instruct",
                "quant": "Q8_0",
                "calls": 4,
                "go_no_go": {"pass": True},
                "summary": {"parse_ok": 2, "parse_failed": 2},
            }
        ),
        encoding="utf-8",
    )
    legacy_flat = tmp_path / "results_sp_schema_smoke_qwen3b.json"
    legacy_flat.write_text(
        json.dumps(
            {
                "model": "Qwen/Qwen2.5-Coder-3B-Instruct",
                "N": 4,
                "parse_ok_count": 4,
                "parse_failed_count": 0,
            }
        ),
        encoding="utf-8",
    )
    legacy_escalation = tmp_path / "results_sp_schema_smoke_deepseek.json"
    legacy_escalation.write_text(
        json.dumps(
            {
                "model": "deepseek/deepseek-v4-flash",
                "result": {"parse_ok": 3, "parse_fail": 1},
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_smokes([schema_v1, legacy_flat, legacy_escalation])

    assert summary["summary"]["input_files"] == 3
    assert summary["summary"]["go_no_go_passes"] == 3
    assert summary["summary"]["qwen15b_smokes"] == 1
    assert summary["summary"]["required_quant_smokes_present"] == {
        "Q8_0": True,
        "Q6_K": False,
        "Q4_K_M": False,
    }
    assert summary["summary"]["required_quant_smokes_passed"] == {
        "Q8_0": True,
        "Q6_K": False,
        "Q4_K_M": False,
    }
    assert summary["summary"]["missing_quant_smokes"] == ["Q6_K", "Q4_K_M"]
    assert summary["summary"]["failed_required_quant_smokes"] == []
    assert summary["summary"]["release_ready"] is False
    assert {row["format"] for row in summary["rows"]} == {
        "schema-v1-smoke",
        "legacy-flat",
        "legacy-escalation",
    }


def test_schema_smoke_summary_writes_reports(tmp_path):
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "model": "qwen",
                "N": 4,
                "parse_ok_count": 1,
                "parse_failed_count": 3,
            }
        ),
        encoding="utf-8",
    )
    summary = summarize_smokes([smoke])
    json_path = tmp_path / "summary.json"
    md_path = tmp_path / "summary.md"

    write_reports(summary, json_path, md_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["benchmark"] == ("schema-smoke-summary")
    md = md_path.read_text(encoding="utf-8")
    assert "# Schema Smoke Summary" in md
    assert "release ready: False" in md


def test_schema_smoke_summary_go_no_go_rounds_odd_calls_up() -> None:
    assert _passes_smoke(2, 5) is False
    assert _passes_smoke(3, 5) is True


def test_schema_smoke_summary_detects_required_qwen15b_quants(tmp_path):
    q8 = tmp_path / "results_v14_qwen15b_q8_0_smoke_schema_v1.json"
    q8.write_text(
        json.dumps(
            {
                "benchmark": "schema-v1-smoke",
                "model": "Qwen2.5-Coder-1.5B-Instruct",
                "quant": "Q8_0",
                "calls": 4,
                "go_no_go": {"pass": True},
                "summary": {"parse_ok": 4, "parse_failed": 0},
            }
        ),
        encoding="utf-8",
    )
    q6 = tmp_path / "results_v14_qwen15b_q6_k_smoke_schema_v1.json"
    q6.write_text(
        json.dumps(
            {
                "benchmark": "schema-v1-smoke",
                "model": "Qwen2.5-Coder-1.5B-Instruct",
                "calls": 4,
                "go_no_go": {"pass": True},
                "summary": {"parse_ok": 4, "parse_failed": 0},
            }
        ),
        encoding="utf-8",
    )
    q4 = tmp_path / "results_v14_qwen15b_smoke_schema_v1.json"
    q4.write_text(
        json.dumps(
            {
                "benchmark": "schema-v1-smoke",
                "model": "Qwen2.5-Coder-1.5B-Instruct",
                "model_spec": "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf",
                "calls": 4,
                "go_no_go": {"pass": True},
                "summary": {"parse_ok": 4, "parse_failed": 0},
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_smokes([q4, q6, q8])

    assert summary["summary"]["required_quant_smokes_present"] == {
        "Q8_0": True,
        "Q6_K": True,
        "Q4_K_M": True,
    }
    assert summary["summary"]["missing_quant_smokes"] == []
    assert [row["quant"] for row in summary["rows"]] == ["Q6_K", "Q8_0", "Q4_K_M"]


def test_schema_smoke_summary_main_accepts_inputs(tmp_path):
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "model": "qwen",
                "N": 4,
                "parse_ok_count": 4,
                "parse_failed_count": 0,
            }
        ),
        encoding="utf-8",
    )
    json_path = tmp_path / "out.json"
    md_path = tmp_path / "out.md"

    rc = main(
        [
            "--inputs",
            str(smoke),
            "--json-output",
            str(json_path),
            "--md-output",
            str(md_path),
            "--quiet",
        ]
    )

    assert rc == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["go_no_go_passes"] == 1


def test_schema_smoke_summary_main_defaults_to_success_with_missing_quants(tmp_path):
    smoke = tmp_path / "smoke.json"
    smoke.write_text(
        json.dumps(
            {
                "model": "qwen",
                "N": 4,
                "parse_ok_count": 4,
                "parse_failed_count": 0,
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "--inputs",
            str(smoke),
            "--json-output",
            str(tmp_path / "out.json"),
            "--md-output",
            str(tmp_path / "out.md"),
            "--quiet",
        ]
    )

    assert rc == 0


def test_schema_smoke_summary_main_can_fail_on_missing_required_quants(tmp_path):
    smoke = tmp_path / "results_v14_qwen15b_q8_0_smoke_schema_v1.json"
    smoke.write_text(
        json.dumps(
            {
                "benchmark": "schema-v1-smoke",
                "model": "Qwen2.5-Coder-1.5B-Instruct",
                "quant": "Q8_0",
                "calls": 4,
                "go_no_go": {"pass": True},
                "summary": {"parse_ok": 4, "parse_failed": 0},
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "--inputs",
            str(smoke),
            "--json-output",
            str(tmp_path / "out.json"),
            "--md-output",
            str(tmp_path / "out.md"),
            "--quiet",
            "--fail-missing-required-quants",
        ]
    )

    assert rc == 1


def test_schema_smoke_summary_main_passes_when_required_quants_present(tmp_path):
    inputs = []
    for quant in ("Q8_0", "Q6_K", "Q4_K_M"):
        smoke = tmp_path / f"results_v14_qwen15b_{quant.lower()}_smoke_schema_v1.json"
        smoke.write_text(
            json.dumps(
                {
                    "benchmark": "schema-v1-smoke",
                    "model": "Qwen2.5-Coder-1.5B-Instruct",
                    "quant": quant,
                    "calls": 4,
                    "go_no_go": {"pass": True},
                    "summary": {"parse_ok": 4, "parse_failed": 0},
                }
            ),
            encoding="utf-8",
        )
        inputs.append(smoke)

    rc = main(
        [
            "--inputs",
            *[str(path) for path in inputs],
            "--json-output",
            str(tmp_path / "out.json"),
            "--md-output",
            str(tmp_path / "out.md"),
            "--quiet",
            "--fail-missing-required-quants",
        ]
    )

    assert rc == 0


def test_schema_smoke_summary_main_fails_when_required_quant_smoke_fails(tmp_path):
    inputs = []
    for quant, passed in (("Q8_0", True), ("Q6_K", False), ("Q4_K_M", True)):
        smoke = tmp_path / f"results_v14_qwen15b_{quant.lower()}_smoke_schema_v1.json"
        smoke.write_text(
            json.dumps(
                {
                    "benchmark": "schema-v1-smoke",
                    "model": "Qwen2.5-Coder-1.5B-Instruct",
                    "quant": quant,
                    "calls": 4,
                    "go_no_go": {"pass": passed},
                    "summary": {
                        "parse_ok": 4 if passed else 1,
                        "parse_failed": 0 if passed else 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        inputs.append(smoke)

    rc = main(
        [
            "--inputs",
            *[str(path) for path in inputs],
            "--json-output",
            str(tmp_path / "out.json"),
            "--md-output",
            str(tmp_path / "out.md"),
            "--quiet",
            "--fail-missing-required-quants",
        ]
    )
    summary = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["summary"]

    assert rc == 1
    assert summary["missing_quant_smokes"] == []
    assert summary["failed_required_quant_smokes"] == ["Q6_K"]


def test_qwen15b_quant_curve_manifest_covers_required_quants() -> None:
    manifest = json.loads(Path("bench/qwen15b_quant_curve_manifest.json").read_text(encoding="utf-8"))

    assert {row["quant"] for row in manifest["required_quants"]} == set(REQUIRED_QUANT_SMOKES)
    assert all(row["filename"].endswith(".gguf") for row in manifest["required_quants"])
    assert set(manifest["final_artifacts"]) == {
        "bench/results_v14_qwen15b_quant_curve.json",
        "bench/results_v14_qwen15b_quant_curve.md",
        "bench/results_v14_qwen15b_quant_curve.pdf",
    }
