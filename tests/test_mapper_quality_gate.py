from pathlib import Path

import sys

from scripts.mapper_quality_gate import _status, build_report, main


def test_quality_report_is_markdown_and_preserves_unavailable_evidence():
    root = Path(__file__).parents[1]
    report, code = build_report(root, runtime_binary="definitely-missing-simplicio")
    assert code == 0
    assert report.startswith("# Mapper quality gate")
    assert "Performance observations | null" in report
    assert "HBP receipt | null" in report
    assert "Runtime ecosystem doctor | null" in report


def test_runtime_requirement_blocks_missing_runtime():
    root = Path(__file__).parents[1]
    _, code = build_report(
        root,
        runtime_binary="definitely-missing-simplicio",
        require_runtime=True,
    )
    assert code == 1


def test_release_gate_fails_closed_on_legacy_json_and_missing_evidence():
    report, code = build_report(
        Path(__file__).parents[1],
        runtime_binary="definitely-missing-simplicio",
        release=True,
    )
    assert code == 1
    assert "Overall: **BLOCKED**" in report
    assert "INTERNAL_JSON .simplicio/project-map.json" in report


def test_status_distinguishes_pass_failure_and_missing_command(tmp_path):
    assert _status([sys.executable, "-c", "print('ok')"], tmp_path) == ("pass", "ok")
    status, detail = _status([sys.executable, "-c", "raise SystemExit('bad')"], tmp_path)
    assert status == "fail" and detail == "bad"
    status, _ = _status(["definitely-missing-command"], tmp_path)
    assert status == "null"


def test_main_writes_markdown_report(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[1])
    output = tmp_path / "quality.md"
    assert main(["--output", str(output), "--runtime-binary", "definitely-missing-simplicio"]) == 0
    assert output.read_text(encoding="utf-8").startswith("# Mapper quality gate")


def test_full_gate_records_each_local_check(monkeypatch):
    root = Path(__file__).parents[1]

    def fake_status(command, _root):
        return "pass", "observed"

    monkeypatch.setattr("scripts.mapper_quality_gate._status", fake_status)
    report, code = build_report(root, full=True)
    assert code == 0
    assert "Python tests | pass | observed" in report
    assert "Node unit tests | pass | observed" in report
    assert "Package contents | pass | observed" in report
