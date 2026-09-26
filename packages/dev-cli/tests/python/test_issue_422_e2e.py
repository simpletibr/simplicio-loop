from __future__ import annotations

import sys

from scripts.issue_422_e2e import run, write_reports


def test_issue_422_runner_exercises_real_transactions_without_claiming_missing_capabilities(tmp_path):
    payload = run(tmp_path, repeats=10)
    assert payload["schema"] == "simplicio.dev-cli.issue-422-evidence/v1"
    scenarios = {row["scenario"]: row for row in payload["scenarios"]}
    assert scenarios["auto_without_runtime"]["effective_mode"] == "standalone"
    for count in (1, 20, 200):
        row = scenarios[f"standalone_changeset_{count}"]
        assert row["status"] == "PASS"
        assert row["repetitions"] == 10
        assert row["replay_status"] == "ok"
        assert f"fast_python_binary_{count}" not in scenarios
    assert "fast_rust" not in scenarios
    assert "fast" not in payload["components"]
    assert payload["claims"]["performance_improvement"] is None
    if sys.platform.startswith("win"):
        assert scenarios["windows_locked_file"]["status"] == "PASS"
    else:
        assert scenarios["windows_locked_file"]["status"] == "UNAVAILABLE"


def test_issue_422_reports_are_reproducible_artifacts(tmp_path):
    payload = run(tmp_path, repeats=10)
    output = tmp_path / "evidence.md"
    write_reports(payload, output)
    assert output.is_file()
    assert output.with_suffix(".json").is_file()
    assert output.with_suffix(".jsonl").is_file()
    assert output.with_suffix(".csv").is_file()
