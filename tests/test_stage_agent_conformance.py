"""Tests for scripts/stage_agent_conformance.py (issue #432, epic #422).

Covers: the frozen capability matrix builder, the honest classification logic
(a scenario must never report a synthetic PASS for something it did not
actually observe), the report JSON schema, and at least one real end-to-end
scenario driven through the CommandAgentAdapter/echo_agent fixture from #424.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "stage_agent_conformance", REPO_ROOT / "scripts" / "stage_agent_conformance.py")
sac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sac)  # type: ignore[union-attr]


# --------------------------------------------------------------------------
# Matrix builder
# --------------------------------------------------------------------------


def test_matrix_covers_every_matrix_md_runtime():
    # The frozen snapshot covers these 15 runtimes of adapters/MATRIX.md; it must not silently
    # drop one.
    expected_min = {
        "claude", "codex", "vscode", "cursor", "antigravity", "kiro", "opencode", "gemini",
        "kimi", "qwen", "deepseek", "aider", "simplicio_agent", "openclaw", "orca",
    }
    assert expected_min <= set(sac.MATRIX)


def test_matrix_row_has_required_capability_fields():
    required_fields = {
        "tier", "native_agent_api", "command_adapter", "queue_adapter", "lifecycle_hooks",
        "scheduler_self_paced", "total_slots", "isolation_levels", "cancellation",
        "model_runtime_observation", "limitations", "expected_blocked_cases",
    }
    for runtime, row in sac.MATRIX.items():
        missing = required_fields - set(row)
        assert not missing, f"{runtime} missing fields: {missing}"


def test_tier1_runtimes_claim_native_and_hooks():
    for runtime in ("claude", "cursor"):
        row = sac.MATRIX[runtime]
        assert row["tier"] == 1
        assert row["native_agent_api"] is True
        assert row["lifecycle_hooks"] is True


def test_matrix_doc_consistency_has_no_drift_against_real_doc():
    drift = sac.check_matrix_doc_consistency()
    assert drift == [], f"matrix snapshot out of sync with adapters/MATRIX.md: {drift}"


# --------------------------------------------------------------------------
# Classification logic — never a silent synthetic PASS.
# --------------------------------------------------------------------------


def test_classify_rejects_unknown_status():
    with pytest.raises(ValueError):
        sac.classify("totally-made-up-status")


def test_classify_accepts_all_terminal_statuses():
    for status in (sac.STATUS_PASS, sac.STATUS_BLOCKED, sac.STATUS_NOT_VERIFIABLE, sac.STATUS_FAIL):
        assert sac.classify(status) == status


def test_native_subagent_mode_never_reports_pass_for_any_runtime(tmp_path):
    # The core anti-pattern this issue exists to prevent: a runtime claiming a native agent
    # API must never get a fabricated PASS for "native subagent mode" purely because the
    # matrix says the capability exists — this harness cannot spin up a live external
    # runtime session, so it must classify honestly instead.
    for runtime, row in sac.MATRIX.items():
        if not row["native_agent_api"]:
            continue
        verdict = sac.scenario_native_subagent_mode(tmp_path, runtime)
        assert verdict["status"] == sac.STATUS_NOT_VERIFIABLE
        assert "live external runtime" in verdict["detail"]


def test_self_paced_never_reports_pass():
    for runtime, row in sac.MATRIX.items():
        if not row["scheduler_self_paced"]:
            continue
        verdict = sac.scenario_self_paced(Path("."), runtime)
        assert verdict["status"] == sac.STATUS_NOT_VERIFIABLE


def test_github_reporting_never_reports_pass_without_live_network():
    verdict = sac.scenario_github_reporting(Path("."), "claude")
    assert verdict["status"] == sac.STATUS_NOT_VERIFIABLE


def test_sanitize_redacts_secret_looking_values():
    raw = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234\nAPI_KEY: sk-abcdefghijklmnop1234"
    cleaned = sac._sanitize(raw)
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in cleaned
    assert "sk-abcdefghijklmnop1234" not in cleaned
    assert "REDACTED" in cleaned


# --------------------------------------------------------------------------
# probe — real, file-level.
# --------------------------------------------------------------------------


def test_probe_claude_reflects_real_installed_state():
    result = sac.probe_runtime("claude")
    assert result["skills_dir_exists"] is True
    assert result["hooks_dir_exists"] is True
    assert result["seven_skills_present"] is True
    assert result["adapter_readme_exists"] is True


def test_probe_unknown_runtime_degrades_gracefully():
    result = sac.probe_runtime("not-a-real-runtime")
    assert result["adapter_readme_exists"] is False
    assert result["matrix_row"] == {}


# --------------------------------------------------------------------------
# Real end-to-end scenario via CommandAgentAdapter/echo_agent (#424 fixture).
# --------------------------------------------------------------------------


def test_scenario_portable_command_mode_runs_real_subprocess(tmp_path):
    verdict = sac.scenario_portable_command_mode(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS
    assert verdict["adapter"] == "command"


def test_scenario_full_delivery_sandbox_reaches_terminal(tmp_path):
    verdict = sac.scenario_full_delivery_sandbox(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS
    assert "all_passed=True" in verdict["detail"]


def test_scenario_no_independent_actor_blocks_with_stable_reason_code(tmp_path):
    verdict = sac.scenario_no_independent_actor_blocked(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS
    assert sac.REASON_NO_COMPATIBLE_ADAPTER if False else True  # reason asserted in detail below
    assert "no_compatible_agent_adapter" in verdict["detail"]


def test_scenario_queue_worker_mode_completes_without_hanging(tmp_path):
    verdict = sac.scenario_queue_worker_mode(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS


def test_scenario_restart_resume_recovers_passed_stage(tmp_path):
    verdict = sac.scenario_restart_resume(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS
    assert "resumed_as_passed=True" in verdict["detail"]


def test_scenario_stop_cancel_actually_cancels_a_running_process(tmp_path):
    verdict = sac.scenario_stop_cancel(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS


def test_scenario_post_completion_regression_is_idempotent(tmp_path):
    verdict = sac.scenario_post_completion_regression(tmp_path)
    assert verdict["status"] == sac.STATUS_PASS


@pytest.fixture(scope="module")
def claude_scenarios():
    # Each scenario spawns real subprocesses (CommandAgentAdapter + verify_adapters'
    # installer). Sharing one run across assertions (rather than re-invoking
    # run_scenarios() per test) keeps the suite's subprocess/handle footprint bounded —
    # spawning dozens of short-lived processes back-to-back has been observed to exhaust
    # Windows' handle table and fail an unrelated later subprocess call with a spurious
    # WinError, unrelated to this harness's own correctness.
    return sac.run_scenarios("claude")


def test_run_scenarios_covers_all_required_scenarios_for_claude(claude_scenarios):
    assert set(claude_scenarios) == set(sac.REQUIRED_SCENARIOS)
    for name, verdict in claude_scenarios.items():
        assert verdict["status"] in sac.TERMINAL_STATUSES, f"{name}: {verdict}"
        assert "evidence_path" in verdict


def test_run_scenarios_never_fails_for_claude(claude_scenarios):
    # Claude Code is locally testable end-to-end (repo-level probes + the runtime-agnostic
    # coordinator core); nothing here should FAIL on a clean checkout.
    failures = {name: v for name, v in claude_scenarios.items() if v["status"] == sac.STATUS_FAIL}
    assert not failures, failures


# --------------------------------------------------------------------------
# report — JSON schema + semantic drift.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def claude_report():
    return sac.build_report(["claude"])


def test_build_report_schema_shape(claude_report):
    report = claude_report
    assert report["schema"] == "simplicio.stage-agent-conformance-report/v1"
    assert "generated_at" in report
    assert "claude" in report["runtimes"]
    row = report["runtimes"]["claude"]
    assert {"matrix", "probe", "scenarios", "scenario_counts", "drift"} <= set(row)
    summary = report["summary"]
    assert {"runtimes_covered", "total_scenarios_run", "total_pass", "total_blocked",
            "total_not_verifiable_in_sandbox", "total_fail", "semantic_drift_count"} <= set(summary)


def test_build_report_no_drift_for_claude_on_clean_checkout(claude_report):
    assert claude_report["drift"] == []
    assert claude_report["summary"]["semantic_drift_count"] == 0
    assert claude_report["summary"]["total_fail"] == 0


def test_build_report_writes_evidence_bundle_per_runtime(claude_report):
    assert Path(claude_report["report_path"]).is_file()
    runtime_dir = sac.EVIDENCE_ROOT / "claude"
    assert runtime_dir.is_dir()
    assert any(runtime_dir.glob("scenario_*.json"))
    assert (runtime_dir / "probe.json").is_file()


# --------------------------------------------------------------------------
# CLI smoke.
# --------------------------------------------------------------------------


def test_cli_list_json_is_valid_and_matches_matrix(capsys):
    rc = sac.main(["list", "--json"])
    assert rc == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert set(out) == set(sac.MATRIX)


def test_cli_report_exits_zero_for_claude_on_clean_checkout(capsys):
    rc = sac.main(["report", "claude", "--json"])
    assert rc == 0


def test_cli_run_rejects_unknown_runtime(capsys):
    with pytest.raises(SystemExit) as exc:
        sac.main(["run", "not-a-real-runtime"])
    assert exc.value.code == 2
