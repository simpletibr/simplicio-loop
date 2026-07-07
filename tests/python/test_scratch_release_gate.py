"""Tests for the scratch release-gate preflight harness."""

from __future__ import annotations

from bench.run_scratch_release_gate import (
    PILOT_STACKS,
    RELEASE_GOALS,
    _doer_readiness,
    _planner_readiness,
    _which,
    run_preflight,
    write_reports,
)


def test_release_gate_preflight_defines_full_matrix(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_PLANNER", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    result = run_preflight()

    assert result["gate"]["goals"] == 15
    assert result["gate"]["pilot_stacks"] == 5
    assert result["gate"]["planned_runs"] == len(RELEASE_GOALS) * len(PILOT_STACKS)
    assert {row["stack"] for row in result["stacks"]} == set(PILOT_STACKS)
    assert result["summary"]["ready_for_live_gate"] is False
    assert result["summary"]["blocker_count"] >= 2


def test_release_gate_preflight_writes_reports(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_PLANNER", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    result = run_preflight()
    json_path = tmp_path / "release-gate.json"
    md_path = tmp_path / "release-gate.md"

    write_reports(result, json_path, md_path)

    assert '"benchmark": "scratch-release-gate"' in json_path.read_text(encoding="utf-8")
    assert "# Scratch Release Gate Preflight" in md_path.read_text(encoding="utf-8")


def test_release_gate_preflight_resolves_shell_out_route_names(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "codex-cli/default")
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/default")
    monkeypatch.setattr(
        "bench.run_scratch_release_gate._which",
        lambda command: "C:/bin/codex.cmd" if command == "codex" else None,
    )

    planner = _planner_readiness()
    doer = _doer_readiness()

    assert planner["ready"] is True
    assert planner["cli_path"] == "C:/bin/codex.cmd"
    assert doer["ready"] is True
    assert doer["cli_path"] == "C:/bin/codex.cmd"


def test_release_gate_preflight_honors_tool_overrides(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_TOOL_GO", "C:/tools/go/bin/go.exe")

    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0

        assert cmd == "C:/tools/go/bin/go.exe version"
        assert kwargs["shell"] is True
        return Result()

    monkeypatch.setattr("bench.run_scratch_release_gate.subprocess.run", fake_run)

    assert _which("go") == "C:/tools/go/bin/go.exe"


def test_release_gate_preflight_rejects_broken_tool_override(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_TOOL_COMPOSER", "php missing-composer.phar")

    def fake_run(*_args, **_kwargs):
        class Result:
            returncode = 1

        return Result()

    monkeypatch.setattr("bench.run_scratch_release_gate.subprocess.run", fake_run)
    monkeypatch.setattr("bench.run_scratch_release_gate.shutil.which", lambda _cmd: None)

    assert _which("composer") is None
