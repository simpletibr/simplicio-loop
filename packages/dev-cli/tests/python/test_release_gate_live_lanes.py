from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bench.run_release_gate_live_lanes import (
    PLANES_CASE_ID,
    main,
    run_lane_report,
    write_reports,
)


def _completed(cmd, stdout: str, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def test_live_lane_report_lists_gpt54_and_planes(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr("bench.run_release_gate_live_lanes.shutil.which", lambda cmd: f"C:/bin/{cmd}.exe")

    result = run_lane_report()

    assert result["schema"] == "simplicio.dev-cli.release-gate-live-lanes/v1"
    assert result["planes_case_id"] == PLANES_CASE_ID
    gpt_lane = next(row for row in result["lanes"] if row["lane_id"] == "codex-gpt-5.4-medium")
    assert gpt_lane["route"] == "codex-cli/gpt-5.4-medium"
    assert gpt_lane["status"] == "ready"
    assert result["summary"]["gpt_5_4_medium"]["status"] == "ready"


def test_live_lane_report_probes_codex_shell_out_success(monkeypatch) -> None:
    monkeypatch.setattr("bench.run_release_gate_live_lanes.shutil.which", lambda cmd: f"C:/bin/{cmd}.exe")

    def fake_runner(cmd, **_kwargs):
        tool = Path(cmd[0]).name
        if tool == "codex.exe" and "--model" in cmd:
            assert "gpt-5.4-medium" in cmd
            return _completed(cmd, '{"type":"item.completed","item":{"text":"OK"}}')
        if tool == "codex.exe":
            return _completed(cmd, '{"type":"item.completed","item":{"text":"OK"}}')
        if tool == "claude.exe":
            return _completed(cmd, '{"result":"OK"}')
        raise AssertionError(cmd)

    result = run_lane_report(probe_shell_outs=True, runner=fake_runner)

    gpt_lane = next(row for row in result["lanes"] if row["lane_id"] == "codex-gpt-5.4-medium")
    assert gpt_lane["status"] == "measured"
    assert gpt_lane["available"] is True
    assert gpt_lane["measured"] is True
    assert result["summary"]["measured_count"] >= 1


def test_live_lane_report_records_probe_blocker(monkeypatch) -> None:
    monkeypatch.setattr("bench.run_release_gate_live_lanes.shutil.which", lambda cmd: f"C:/bin/{cmd}.exe")

    def fake_runner(cmd, **_kwargs):
        tool = Path(cmd[0]).name
        if tool == "codex.exe" and "gpt-5.4-medium" in cmd:
            return _completed(
                cmd,
                "",
                returncode=1,
                stderr="The 'gpt-5.4-medium' model is not supported when using Codex with a ChatGPT account.",
            )
        return _completed(cmd, "OK")

    result = run_lane_report(probe_shell_outs=True, runner=fake_runner)

    gpt_lane = next(row for row in result["lanes"] if row["lane_id"] == "codex-gpt-5.4-medium")
    assert gpt_lane["status"] == "blocked"
    assert "ChatGPT account" in gpt_lane["probe_stderr_tail"]


def test_live_lane_report_writes_reports_and_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("bench.run_release_gate_live_lanes.shutil.which", lambda cmd: f"C:/bin/{cmd}.exe")
    result = run_lane_report()
    json_path = tmp_path / "live-lanes.json"
    md_path = tmp_path / "live-lanes.md"

    write_reports(result, json_path, md_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["benchmark"] == "release-gate-live-lanes"
    assert "# Release Gate Live Lanes" in md_path.read_text(encoding="utf-8")

    rc = main(
        [
            "--json-output",
            str(tmp_path / "main.json"),
            "--md-output",
            str(tmp_path / "main.md"),
            "--quiet",
        ]
    )
    assert rc == 0
