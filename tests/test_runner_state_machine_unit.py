"""In-process unit tests for the simplicio_loop.runner state machine (issue #275).

PR #321 raised simplicio_loop/cli.py coverage via in-process dispatch tests but left
simplicio_loop/runner.py's goal loop / retry / convergence logic largely untouched.
These tests target the highest-value uncovered branches named by issue #275:

  - state transitions (verify_run, conclude_run, change_phase, reconcile_delivery)
  - retry/backoff and dead-letter behaviour in dispatch_operator_batch
  - resume/idempotency (a journaled success is never re-attempted)
  - stagnation / no-progress paths that must end with an explicit diagnostic

All tests are in-process (no subprocess/CLI layer) so they register with
coverage.py, and all fakes are deterministic (no real time, no network, no real
mapper/dev-cli/watcher binaries).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import local_capacity, openrouter_operator, runner as runner_mod


@pytest.fixture(autouse=True)
def _use_thread_dispatch_for_in_process_fakes(monkeypatch):
    """Keep this state-machine harness independent of the host's physical pressure."""
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    # These tests use synthetic RunJournal fixtures and do not initialize a
    # repository-scoped MapperStore, so they pin the legacy route explicitly;
    # mapper-backed behavior (the default) is covered by integration tests.
    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "legacy")

    def healthy_probe(_root, *, requested_workers, now_ns=None, **_kwargs):
        requested = max(1, int(requested_workers))
        return local_capacity.CapacitySample(
            requested_workers=requested,
            safe_workers=requested,
            cpu_count=8,
            memory_available_bytes=8 << 30,
            disk_free_bytes=100 << 30,
            measured=("cpu_count", "disk_free_bytes", "memory_available_bytes"),
            unavailable=(),
            null_reasons={},
            observed_at_ns=int(now_ns or 1),
        )

    monkeypatch.setattr(local_capacity, "probe_local_capacity", healthy_probe)
    monkeypatch.setattr(
        local_capacity,
        "_physical_pressure",
        lambda _root: {
            "available": True,
            "pressure_percent": 0.0,
            "disk_used_percent": 0.0,
            "disk_free_bytes": 100 << 30,
            "memory_used_percent": 0.0,
            "disk_suspend": False,
        },
    )

TASK = """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenacao de linhas
Tipo: Evolucao

COMO analista do ONS,
QUERO organizar as linhas
PARA melhorar a analise

1. Criterios de Aceite

Cenario 1: Estrutural aparece primeiro
  Dado que existe uma linha estrutural
  Quando a tela for exibida
  Entao a linha estrutural aparece primeiro [RN01]

2. Regras de Negocio

RN01 - Estrutural sempre primeiro.
"""


def _arm_fixture(tmp_path, monkeypatch):
    """Arm one deterministic run without any real mapper/dev-cli/network calls."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".simplicio-loop/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", ".gitignore", "src/app.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Simplicio Tests", "-c", "user.email=tests@simplicio.local",
         "commit", "-qm", "fixture"],
        cwd=repo, check=True,
    )
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")

    fingerprint = {"head": "head-fixed", "tree_hash": "tree-fixed", "dirty_status_hash": "status-fixed"}
    monkeypatch.setattr(runner_mod, "_repo_fingerprint", lambda path: dict(fingerprint))
    monkeypatch.setattr(
        runner_mod, "_changed_paths",
        lambda path: (["src/app.py"]
                      if (Path(path) / "src" / "app.py").read_text(encoding="utf-8")
                      != "def main():\n    return 'ok'\n" else []),
    )

    def fake_mapper(repo_path, run_root, **kwargs):
        runner_mod._write_json(run_root / "mapper-preflight.json", {
            "tool": "simplicio-mapper", "identity_ok": True, "version_ok": True,
            "missing_verbs": [], "repo_state": dict(fingerprint),
        })
        payload = {
            "scan": {"returncode": 0, "stdout": {}, "stderr": ""},
            "inspect": {"returncode": 0, "stdout": {
                "status": {"artifacts_present": True, "fresh": True},
                "evidence": {"artifacts": {
                    "project_map": {"exists": True},
                    "precedent_index": {"exists": True},
                }},
            }, "stderr": ""},
            "handoff": {"returncode": 0, "stdout": {
                "context_pack": {"pack_hash": "pack-fixed",
                                "files": [{"path": "src/app.py", "tests": []}]},
            }, "stderr": ""},
            "generated_at": "2026-07-14T00:00:00Z",
            "repo_state_before": dict(fingerprint),
            "repo_state_after": dict(fingerprint),
        }
        runner_mod._write_json(run_root / "mapper-context.json", payload)
        return payload

    def fake_operator_preflight(repo_path, run_root):
        help_surface = "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json"
        receipt = {
            "tool": "simplicio-dev-cli", "identity_ok": True, "version_ok": True,
            "help_stdout": help_surface, "task_help_stdout": help_surface,
            "required_tokens": list(runner_mod.DEVCLI_REQUIRED_TOKENS),
            "missing_tokens": [],
            "required_capabilities": list(runner_mod.DEVCLI_REQUIRED_CAPABILITIES),
            "missing_capabilities": [],
            "repo_state": dict(fingerprint),
        }
        runner_mod._write_json(run_root / "operator-preflight.json", receipt)
        return receipt

    monkeypatch.setattr(runner_mod, "_run_mapper", fake_mapper)
    monkeypatch.setattr(runner_mod, "_preflight_operator", fake_operator_preflight)
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps({
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    assert armed["state"]["phase"] == "awaiting_decision", armed["state"]
    return repo, armed["manifest"]["run_id"], Path(armed["run_dir"])


# ---------------------------------------------------------------------------
# verify_run: independent watcher gate + convergence to "done"
# ---------------------------------------------------------------------------

def test_verify_run_is_a_noop_on_terminal_phases(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    runner_mod.change_phase(str(repo), run_id, "cancelled", "test terminal")

    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "cancelled"


def test_verify_run_blocks_when_watcher_script_is_unavailable(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    # The watcher ships with the package; simulate a broken install.
    monkeypatch.setattr(runner_mod, "_watcher_script", lambda: tmp_path / "missing" / "watcher_verify.py")

    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "blocked"
    assert "watcher_verify.py is unavailable" in result["state"]["blockers"][0]
    assert result["state"]["current_action"] == "watcher_unavailable"


def test_verify_run_blocks_when_watcher_rejects_the_run(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "watcher_verify.py").write_text("# stub\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text, timeout, env):
        watcher_dir = Path(env["SIMPLICIO_LOOP_DIR"])
        watcher_dir.mkdir(parents=True, exist_ok=True)
        (watcher_dir / "watcher_state.json").write_text(json.dumps({
            "status": "MEASURED", "match": False, "reported": "criteria mismatch",
        }), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="watcher ran", stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)

    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "blocked"
    assert result["state"]["blockers"] == ["criteria mismatch"]
    assert result["state"]["evidence"]["status"] == "UNVERIFIED"


def test_verify_run_blocks_when_watcher_process_exits_nonzero(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "watcher_verify.py").write_text("# stub\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text, timeout, env):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="watcher crashed")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)

    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "blocked"
    assert "watcher crashed" in result["state"]["blockers"][0]


def test_verify_run_converges_to_done_when_watcher_and_delivery_pass(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "watcher_verify.py").write_text("# stub\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text, timeout, env):
        watcher_dir = Path(env["SIMPLICIO_LOOP_DIR"])
        watcher_dir.mkdir(parents=True, exist_ok=True)
        (watcher_dir / "watcher_state.json").write_text(json.dumps({
            "status": "MEASURED", "match": True,
        }), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runner_mod, "reconcile_delivery",
        lambda repo_arg, rid, current_state, **kwargs: {
            "run_dir": str(run_dir), "manifest": {}, "state": {
                **runner_mod.read_status(str(repo), run_id)["state"],
                "delivery": {"ready": True, "target": current_state, "current_state": current_state},
            },
        },
    )

    # wi612 (#612): quality matrix + oracle gates devem ser satisfeitos.
    # Testamos a INTEGRACAO do runner (os proprios gates tem testes dedicados em
    # test_quality_matrix_*.py / test_oracle_gates_unit.py), entao injetamos
    # os gates verdes via monkeypatch.
    import simplicio_loop.oracle as _oracle_mod
    monkeypatch.setattr(
        _oracle_mod, "_quality_matrix_gate",
        lambda rd: (True, {"name": "quality_matrix", "ok": True}, {"ready": True}),
    )
    monkeypatch.setattr(
        _oracle_mod, "evaluate_matrix",
        lambda loop_dir, rd, response_text="", flow_gap="": {
            "schema": "simplicio.oracle-matrix/v1",
            "parity": True,
            "adapters": [{"ready": True, "verdict": "VERIFIED",
                         "reason_code": "oracle_complete", "tag": "MEASURED"}],
            "signature": [True, "VERIFIED", "oracle_complete", "MEASURED"],
        },
    )
    # This state-machine fixture intentionally models only the pre-existing
    # watcher/delivery/oracle seam; the runtime handoff has its own integration
    # coverage in test_loop_execution_receipt.py.
    published = []

    def fake_publish(**kwargs):
        published.append(kwargs)
        return {"status": "VERIFIED", "reason": "unit_fixture"}

    monkeypatch.setattr(runner_mod, "publish_loop_execution_receipt", fake_publish)

    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "done"
    assert result["state"]["completion"]["verdict"] == "VERIFIED"
    assert result["state"]["completion"]["reason_code"] == "watcher_and_delivery_verified"
    assert result["state"]["completion"]["tag"] == "MEASURED"
    assert published == [{
        "repo": repo,
        "run_dir": run_dir,
        "manifest": result["manifest"],
    }]


def test_verify_run_blocks_when_quality_matrix_missing(tmp_path, monkeypatch):
    """wi612 (#612): done e bloqueado quando falta quality-matrix receipt."""
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "watcher_verify.py").write_text("# stub\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text, timeout, env):
        watcher_dir = Path(env["SIMPLICIO_LOOP_DIR"])
        watcher_dir.mkdir(parents=True, exist_ok=True)
        (watcher_dir / "watcher_state.json").write_text(json.dumps({
            "status": "MEASURED", "match": True,
        }), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runner_mod, "reconcile_delivery",
        lambda repo_arg, rid, current_state, **kwargs: {
            "run_dir": str(run_dir), "manifest": {}, "state": {
                **runner_mod.read_status(str(repo), run_id)["state"],
                "delivery": {"ready": True, "target": current_state, "current_state": current_state},
            },
        },
    )

    # NENHUM quality-matrix.json escrito -> gate deve bloquear
    result = runner_mod.verify_run(str(repo), run_id)

    assert result["state"]["phase"] == "blocked"
    # The per-requirement gate (simplicio_loop/quality_matrix.py::_requirement_gate)
    # now reports a missing matrix through each unproven requirement's own
    # "not passing" verdict rather than a single generic "file missing" string --
    # still the same underlying block (no quality-matrix evidence at all).
    assert "evidence is not passing" in (result["state"].get("blockers") or [""])[0]
    assert result["state"]["current_action"] == "quality_matrix_failed"


def test_verify_run_stops_short_of_done_when_delivery_is_not_ready(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "watcher_verify.py").write_text("# stub\n", encoding="utf-8")

    def fake_run(argv, cwd, capture_output, text, timeout, env):
        watcher_dir = Path(env["SIMPLICIO_LOOP_DIR"])
        watcher_dir.mkdir(parents=True, exist_ok=True)
        (watcher_dir / "watcher_state.json").write_text(json.dumps({
            "status": "MEASURED", "match": True,
        }), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    not_ready_status = {
        "run_dir": str(run_dir), "manifest": {}, "state": {"delivery": {"ready": False}, "phase": "partial"},
    }
    monkeypatch.setattr(
        runner_mod, "reconcile_delivery",
        lambda repo_arg, rid, current_state, **kwargs: not_ready_status,
    )

    result = runner_mod.verify_run(str(repo), run_id)

    assert result is not_ready_status
    assert result["state"]["phase"] == "partial"


# ---------------------------------------------------------------------------
# conclude_run: fail-closed diff-coverage gate, human override still audited
# ---------------------------------------------------------------------------

def test_conclude_run_blocks_when_production_diff_lacks_operator_receipt(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "_operator_run_diff_coverage",
        lambda repo_path, rd: {"coverage_ok": False, "uncovered_paths": ["src/app.py"]},
    )

    with pytest.raises(RuntimeError, match="production diff paths without an operator receipt"):
        runner_mod.conclude_run(str(repo), run_id)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert "gates" not in state or state.get("gates") == []


def test_conclude_run_force_overrides_but_still_records_the_violation(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "_operator_run_diff_coverage",
        lambda repo_path, rd: {"coverage_ok": False, "uncovered_paths": ["src/app.py"]},
    )

    result = runner_mod.conclude_run(str(repo), run_id, force=True)

    gate = result["state"]["operator_run_gate"]
    assert gate["coverage_ok"] is False
    assert gate["forced"] is True
    assert gate["uncovered_paths"] == ["src/app.py"]
    assert result["state"]["gates"][-1] == gate


def test_conclude_run_passes_through_when_coverage_is_ok(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "_operator_run_diff_coverage",
        lambda repo_path, rd: {"coverage_ok": True, "uncovered_paths": []},
    )

    result = runner_mod.conclude_run(str(repo), run_id)

    gate = result["state"]["operator_run_gate"]
    assert gate["coverage_ok"] is True
    assert gate["forced"] is False
    # conclude_run re-transitions to the SAME phase it found; awaiting_decision is a valid phase.
    assert result["state"]["phase"] == "awaiting_decision"


# ---------------------------------------------------------------------------
# change_phase / read_status: state-machine invariants
# ---------------------------------------------------------------------------

def test_change_phase_rejects_transition_from_terminal_state(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    runner_mod.change_phase(str(repo), run_id, "done", "test terminal")

    with pytest.raises(ValueError, match="run already terminal"):
        runner_mod.change_phase(str(repo), run_id, "awaiting_decision", "should not work")


def test_change_phase_to_awaiting_decision_clears_maintenance_deferral(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    runner_mod.defer_maintenance_backlog_only(
        str(repo), run_id, correction_summary="freeze",
        deferral_reason="maintenance window", resume_instructions=["resume later"],
    )

    result = runner_mod.change_phase(str(repo), run_id, "awaiting_decision", "resume from maintenance")

    assert result["state"]["maintenance"]["mode"] == "active"
    assert result["state"]["maintenance"]["disposition"] == "operator"
    assert result["state"]["operator"]["execution_state"] == "invalidated"
    assert result["state"]["evidence"]["status"] == "INVALIDATED"
    assert result["state"]["next_action"] == "mapper_scan_required"


def test_change_phase_to_cancelled_clears_next_action(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)

    result = runner_mod.change_phase(str(repo), run_id, "cancelled", "operator cancelled")

    assert result["state"]["phase"] == "cancelled"
    assert result["state"]["next_action"] == "none"


def test_read_status_graceful_when_no_runs_directory_exists(tmp_path):
    """Regression for issue #500: no longer raises; returns a graceful no_runs state."""
    repo = tmp_path / "empty-repo"
    repo.mkdir()

    result = runner_mod.read_status(str(repo))
    assert result["run_dir"] is None
    assert result["state"]["phase"] == "no_runs"
    assert result["state"]["completion"]["verdict"] == "NO_RUNS"


def test_read_status_graceful_when_runs_directory_is_empty(tmp_path):
    """Regression for issue #500: loop-runs exists but empty -> graceful no_runs."""
    repo = tmp_path / "repo"
    (repo / ".simplicio-loop" / "loop-runs").mkdir(parents=True)

    result = runner_mod.read_status(str(repo))
    assert result["state"]["phase"] == "no_runs"
    assert result["state"]["completion"]["verdict"] == "NO_RUNS"


def test_read_status_graceful_no_runs_directory(tmp_path):
    """Issue #500: read_status must return a graceful no-runs state instead of
    raising FileNotFoundError when the repository has no .simplicio-loop/loop-runs dir."""
    repo = tmp_path / "consumer_repo"
    repo.mkdir()

    result = runner_mod.read_status(str(repo))

    assert result["run_dir"] is None
    assert result["manifest"] is None
    assert result["state"]["phase"] == "no_runs"
    assert result["state"]["completion"]["verdict"] == "NO_RUNS"
    assert result["state"]["completion"]["ready"] is False
    assert "no runs directory" in result["state"]["message"]


def test_read_status_graceful_no_runs_empty_dir(tmp_path):
    """Issue #500 (variant): loop-runs exists but is empty -> graceful NO_RUNS."""
    repo = tmp_path / "consumer_repo"
    (repo / ".simplicio-loop" / "loop-runs").mkdir(parents=True)

    result = runner_mod.read_status(str(repo))

    assert result["state"]["phase"] == "no_runs"
    assert result["state"]["completion"]["verdict"] == "NO_RUNS"


def test_read_status_without_run_id_picks_the_lexicographically_latest_run(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    runs_root = run_dir.parent
    older = runs_root / "run-000-earlier"
    older.mkdir()
    (older / "manifest.json").write_text(json.dumps({"run_id": "run-000-earlier"}), encoding="utf-8")
    (older / "state.json").write_text(json.dumps({"phase": "done"}), encoding="utf-8")

    result = runner_mod.read_status(str(repo))

    assert result["manifest"]["run_id"] == run_id


# ---------------------------------------------------------------------------
# reconcile_delivery: ready / not-ready / reopened (regression) branches
# ---------------------------------------------------------------------------

def test_reconcile_delivery_marks_ready_and_advances_to_delivering(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "build_delivery_receipt",
        lambda run_dir_arg, target, **kwargs: {
            "target": target, "current_state": kwargs["current_state"], "ready": True,
            "source_checked_at": "2026-07-14T00:00:00Z", "gates": [],
        },
    )
    monkeypatch.setattr(runner_mod, "reconcile_delivery_observation", lambda prev, cur: {"status": "confirmed"})
    monkeypatch.setattr(runner_mod, "write_delivery_receipt", lambda run_dir_arg, receipt: None)

    result = runner_mod.reconcile_delivery(str(repo), run_id, "pr-open", source_kind="github")

    assert result["state"]["delivery"]["ready"] is True
    assert result["state"]["current_action"] == "delivery_reconciled"
    assert result["state"]["phase"] == "delivering"


def test_reconcile_delivery_records_blocker_when_not_ready(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "build_delivery_receipt",
        lambda run_dir_arg, target, **kwargs: {
            "target": target, "current_state": kwargs["current_state"], "ready": False,
            "source_checked_at": "2026-07-14T00:00:00Z",
            "gates": [{"status": "fail", "detail": "checks are not green"}],
        },
    )
    monkeypatch.setattr(runner_mod, "reconcile_delivery_observation", lambda prev, cur: {"status": "pending"})
    monkeypatch.setattr(runner_mod, "write_delivery_receipt", lambda run_dir_arg, receipt: None)

    result = runner_mod.reconcile_delivery(str(repo), run_id, "pr-open", source_kind="github")

    assert result["state"]["delivery"]["ready"] is False
    assert result["state"]["current_action"] == "delivery_reconciliation_failed"
    assert result["state"]["blockers"] == ["checks are not green"]
    assert result["state"]["phase"] == "partial"


def test_reconcile_delivery_reopens_run_on_regression(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "build_delivery_receipt",
        lambda run_dir_arg, target, **kwargs: {
            "target": target, "current_state": kwargs["current_state"], "ready": False,
            "source_checked_at": "2026-07-14T00:00:00Z",
            "gates": [{"status": "fail", "detail": "checks regressed to red"}],
        },
    )
    monkeypatch.setattr(
        runner_mod, "reconcile_delivery_observation",
        lambda prev, cur: {"status": "reopened", "reason_code": "checks_regressed"},
    )
    monkeypatch.setattr(runner_mod, "write_delivery_receipt", lambda run_dir_arg, receipt: None)

    result = runner_mod.reconcile_delivery(str(repo), run_id, "pr-open", source_kind="github")

    assert result["state"]["current_action"] == "delivery_reopened"
    assert result["state"]["next_action"] == "requery_source"
    assert result["state"]["phase"] == "partial"
    assert "delivery reopened" in result["state"]["blockers"][0]


# ---------------------------------------------------------------------------
# apply_human_decision: replanning boundary invalidates dependent artifacts
# ---------------------------------------------------------------------------

def test_apply_human_decision_raises_when_decision_id_is_unknown(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="decision id not found"):
        runner_mod.apply_human_decision(str(repo), run_id, "Q-DOES-NOT-EXIST", "answer")


def test_apply_human_decision_raises_when_contract_has_no_tasks(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    contract_path = runner_mod._contract_path(run_dir)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["tasks"] = []
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="task contract collection is empty"):
        runner_mod.apply_human_decision(str(repo), run_id, "anything", "answer")


def test_apply_human_decision_resolves_bucket_item_and_invalidates_artifacts(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    contract_path = runner_mod._contract_path(run_dir)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["tasks"][0]["questions"] = [{"id": "Q-BUCKET-1"}]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "operator-receipt.json").exists()

    result = runner_mod.apply_human_decision(str(repo), run_id, "Q-BUCKET-1", "answered", impact="scope-change")

    assert result["state"]["phase"] == "awaiting_decision"
    assert result["state"]["operator"]["execution_state"] == "invalidated"
    assert result["state"]["evidence"]["status"] == "INVALIDATED"
    assert result["state"]["delivery"]["ready"] is False
    assert not (run_dir / "plan.json").exists()
    assert not (run_dir / "operator-receipt.json").exists()
    updated_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    resolved = updated_contract["tasks"][0]["questions"][0]
    assert resolved["resolved"] is True
    assert resolved["answer"] == "answered"
    assert resolved["resolution_impact"] == "scope-change"
    assert updated_contract["revision"] == contract.get("revision", 1) + 1


# ---------------------------------------------------------------------------
# sync_source_state: only github is a supported source
# ---------------------------------------------------------------------------

def test_sync_source_state_rejects_unsupported_source(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="unsupported source: 'gitlab'"):
        runner_mod.sync_source_state(str(repo), run_id, "gitlab")


def test_sync_source_state_delegates_to_reconcile_delivery_for_github(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner_mod, "github_delivery_payload",
        lambda external_repo, pr=None, tag="", target_state="": {"pr": {"url": "https://x/1"}},
    )
    monkeypatch.setattr(runner_mod, "infer_github_delivery_state", lambda payload: "pr-open")
    captured = {}

    def fake_reconcile(repo_arg, rid, current_state, source_kind="local", source_payload=None):
        captured["args"] = (repo_arg, rid, current_state, source_kind, source_payload)
        return {"state": {"phase": "partial"}}

    monkeypatch.setattr(runner_mod, "reconcile_delivery", fake_reconcile)

    result = runner_mod.sync_source_state(str(repo), run_id, "github", external_repo="org/repo", pr=42)

    assert result == {"state": {"phase": "partial"}}
    assert captured["args"][2] == "pr-open"
    assert captured["args"][3] == "github"


# ---------------------------------------------------------------------------
# dispatch_operator_batch: retry/backoff, dead-letter, resume-idempotency
# ---------------------------------------------------------------------------

def _fake_item(repo, run_id="run-synthetic", task_index=1, worker_id=None):
    return {
        "repo": str(repo), "run_id": run_id, "task_index": task_index,
        "worker_id": worker_id or f"worker-{task_index}",
    }


def test_dispatch_operator_batch_rejects_duplicate_repo_run_task_items(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="duplicate repo/run/task items"):
        runner_mod.dispatch_operator_batch([_fake_item(repo), _fake_item(repo)])


def test_dispatch_operator_batch_propagates_provider_worker_to_attempt(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    seen = []

    def fake_attempt(item):
        seen.append(item.get("provider_worker"))
        return {
            "schema": "simplicio.operator-worker/v1",
            "worker_id": item["worker_id"],
            "repo": item["repo"],
            "run_id": item["run_id"],
            "task_index": item["task_index"],
            "status": "succeeded",
            "failure_fingerprint": "",
            "receipt_status": "VERIFIED",
        }

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    result = runner_mod.dispatch_operator_batch(
        [_fake_item(repo)], provider_worker="OpenRouter", retry_budget=0,
    )

    assert result["completed_task_indices"] == [1]
    assert seen == ["openrouter"]


def test_dispatch_operator_batch_retries_until_success_within_budget(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = {"n": 0}

    def fake_attempt(item):
        calls["n"] += 1
        status = "succeeded" if calls["n"] >= 3 else "failed"
        return {
            "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
            "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
            "status": status, "failure_fingerprint": "" if status == "succeeded" else f"fp-{calls['n']}",
            "receipt_status": "VERIFIED" if status == "succeeded" else "UNVERIFIED",
        }

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    result = runner_mod.dispatch_operator_batch([_fake_item(repo)], retry_budget=3)

    assert calls["n"] == 3
    assert result["completed_task_indices"] == [1]
    assert result["failed_task_indices"] == []
    assert result["dead_letter_task_indices"] == []
    assert result["retry_contract"]["attempts_by_task"]["1"] == 3


def test_dispatch_operator_batch_exhausts_retry_budget_and_dead_letters(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = {"n": 0}

    def fake_attempt(item):
        calls["n"] += 1
        return {
            "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
            "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
            "status": "failed", "failure_fingerprint": "same-fingerprint-always",
            "receipt_status": "UNVERIFIED",
        }

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    result = runner_mod.dispatch_operator_batch([_fake_item(repo)], retry_budget=2)

    # retry_budget=2 means at most 3 attempts (1 initial + 2 retries) before giving up.
    assert calls["n"] == 3
    assert result["failed_task_indices"] == [1]
    assert result["dead_letter_task_indices"] == [1]
    assert result["completed_task_indices"] == []
    assert result["blockers"][0]["task_index"] == 1
    worker = result["workers"][0]
    assert worker["attempt_count"] == 3
    assert worker["retry_scope"] == "worker"
    assert [entry["dispatch_attempt"] for entry in worker["attempt_history"]] == [1, 2, 3]
    # First retry after a failure is flagged distinctly from a same-fingerprint bounded retry.
    assert worker["attempt_history"][1]["failure_fingerprint"] == "same-fingerprint-always"


def test_dispatch_operator_batch_resume_skips_already_succeeded_tasks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal_path = journal_dir / "operator-batch.jsonl"
    journal_path.write_text(json.dumps({
        "repo": str(Path(repo).resolve()), "run_id": "run-synthetic", "task_index": 1,
        "status": "succeeded", "dispatch_attempt": 1,
    }) + "\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_attempt(item):
        calls["n"] += 1
        return {"status": "succeeded", "repo": item["repo"], "run_id": item["run_id"],
                "task_index": item["task_index"], "worker_id": item["worker_id"]}

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    result = runner_mod.dispatch_operator_batch(
        [_fake_item(repo)], retry_budget=1, journal_dir=str(journal_dir),
    )

    # Resume must never repeat an already-confirmed effect: the worker is never invoked.
    assert calls["n"] == 0
    assert result["skipped_completed"] == 1
    assert result["completed_task_indices"] == [1]


def test_dispatch_operator_batch_converges_multiple_independent_tasks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    seen = []

    def fake_attempt(item):
        seen.append(item["task_index"])
        return {"status": "succeeded", "repo": item["repo"], "run_id": item["run_id"],
                "task_index": item["task_index"], "worker_id": item["worker_id"]}

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    items = [
        _fake_item(repo, task_index=1, worker_id="w1"),
        _fake_item(repo, task_index=2, worker_id="w2"),
        _fake_item(repo, task_index=3, worker_id="w3"),
    ]
    for item in items:
        item["isolation_key"] = f"isolated-{item['task_index']}"
    result = runner_mod.dispatch_operator_batch(items, max_workers=3, retry_budget=0)

    assert sorted(seen) == [1, 2, 3]
    assert result["completed_task_indices"] == [1, 2, 3]
    assert result["max_workers"] == 3
    assert result["serial_fallback_reason"] == ""


def test_dispatch_operator_batch_forces_serial_fallback_for_shared_run_state(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_attempt(item):
        return {"status": "succeeded", "repo": item["repo"], "run_id": item["run_id"],
                "task_index": item["task_index"], "worker_id": item["worker_id"]}

    monkeypatch.setattr(runner_mod, "_operator_dispatch_attempt", fake_attempt)

    # Two items sharing one isolation_key (the default: the resolved repo path) cannot run
    # in parallel without corrupting one shared state.json/working tree.
    items = [_fake_item(repo, task_index=1, worker_id="w1"), _fake_item(repo, task_index=2, worker_id="w2")]
    result = runner_mod.dispatch_operator_batch(items, max_workers=4, retry_budget=0)

    assert result["max_workers"] == 1
    assert result["serial_fallback_reason"] == "shared_run_state"


# ---------------------------------------------------------------------------
# _operator_worker_limit: bounded pool sizing (no empty pool, no over-provisioning)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("requested", "item_count", "expected"),
    [
        (None, 0, 0),
        (None, 20, 20),
        (0, 20, 20),
        (-3, 20, 20),
        (2, 5, 2),
        (99, 5, 5),
        (3, 0, 0),
    ],
)
def test_operator_worker_limit_bounds_pool_size(requested, item_count, expected, monkeypatch):
    # Logical demand has no fixed six-worker cap. Physical admission is separate.
    monkeypatch.delenv("SIMPLICIO_LOOP_OPERATOR_WORKERS", raising=False)
    monkeypatch.setattr(runner_mod.os, "cpu_count", lambda: 64)
    assert runner_mod._operator_worker_limit(requested, item_count) == expected


def test_operator_worker_auto_env_preserves_full_demand(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_OPERATOR_WORKERS", "0")
    assert runner_mod._operator_worker_limit(None, 100) == 100


def test_operator_worker_invalid_env_fails_explicitly(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_OPERATOR_WORKERS", "invalid")
    with pytest.raises(ValueError, match="must be an integer"):
        runner_mod._operator_worker_limit(None, 10)


# ---------------------------------------------------------------------------
# _operator_run_diff_coverage: every production diff path must trace to a receipt
# ---------------------------------------------------------------------------

# Note: _changed_paths() shells out to real `git diff`/`git status`. Driving it through a
# real repo is flaky under fast successive writes on some filesystems (the classic "racy
# git" mtime-cache problem), so these tests pin _changed_paths deterministically and focus
# on _operator_run_diff_coverage's own receipt-matching logic -- the part issue #275 cares
# about (a production diff must trace to exactly one covering operator receipt).

def test_operator_run_diff_coverage_ok_when_receipt_covers_every_changed_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_changed_paths", lambda repo_path: ["app.py"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "operator-receipt.json").write_text(json.dumps({
        "status": "applied", "changed_paths": ["app.py"],
    }), encoding="utf-8")

    coverage = runner_mod._operator_run_diff_coverage(tmp_path, run_dir)

    assert coverage["coverage_ok"] is True
    assert coverage["uncovered_paths"] == []
    assert coverage["covered_paths"] == ["app.py"]
    assert coverage["receipt_count"] == 1


def test_operator_run_diff_coverage_flags_uncovered_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_changed_paths", lambda repo_path: ["app.py"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # No receipt at all: the changed path was produced outside the operator bridge.

    coverage = runner_mod._operator_run_diff_coverage(tmp_path, run_dir)

    assert coverage["coverage_ok"] is False
    assert coverage["uncovered_paths"] == ["app.py"]
    assert coverage["receipt_count"] == 0


def test_operator_run_diff_coverage_ignores_receipts_that_did_not_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "_changed_paths", lambda repo_path: ["app.py"])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "operator-receipt.json").write_text(json.dumps({
        "status": "blocked", "changed_paths": ["app.py"],
    }), encoding="utf-8")

    coverage = runner_mod._operator_run_diff_coverage(tmp_path, run_dir)

    assert coverage["coverage_ok"] is False
    assert coverage["uncovered_paths"] == ["app.py"]


# ---------------------------------------------------------------------------
# _restore_operator_checkpoint: rollback safety edge cases
# ---------------------------------------------------------------------------

def test_restore_checkpoint_noop_when_nothing_changed(tmp_path):
    # The on-disk file must actually match the checkpoint snapshot; otherwise the function
    # correctly detects the drift itself (see the "no_change_declared_but_drifted" case
    # below) rather than trusting an empty changed_paths list blindly.
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    checkpoint = {"safe_targets": ["a.py"], "files": [{"path": "a.py", "exists": True, "content": "x"}]}
    result = runner_mod._restore_operator_checkpoint(checkpoint, tmp_path, changed_paths=[])
    assert result == {"attempted": False, "restored": False, "reason": "no_changed_paths"}


def test_restore_checkpoint_detects_drift_even_when_changed_paths_claims_empty(tmp_path):
    # If the checkpointed file no longer matches on disk, the guard must not trust a caller
    # that (incorrectly) reports no changed paths -- it independently verifies drift.
    checkpoint = {"safe_targets": ["a.py"], "files": [{"path": "a.py", "exists": True, "content": "original"}]}
    (tmp_path / "a.py").write_text("drifted", encoding="utf-8")

    result = runner_mod._restore_operator_checkpoint(checkpoint, tmp_path, changed_paths=[])

    assert result == {"attempted": True, "restored": True, "reason": "restored_checkpoint"}
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "original"


def test_restore_checkpoint_refuses_when_checkpoint_has_no_targets(tmp_path):
    checkpoint = {"safe_targets": [], "files": []}
    result = runner_mod._restore_operator_checkpoint(checkpoint, tmp_path, changed_paths=["a.py"])
    assert result == {"attempted": False, "restored": False, "reason": "checkpoint_targets_missing"}


def test_restore_checkpoint_refuses_changes_outside_checkpoint_scope(tmp_path):
    checkpoint = {"safe_targets": ["a.py"], "files": [{"path": "a.py", "exists": True, "content": "x"}]}
    result = runner_mod._restore_operator_checkpoint(checkpoint, tmp_path, changed_paths=["b.py"])
    assert result == {"attempted": False, "restored": False, "reason": "changed_paths_outside_checkpoint_scope"}


def test_restore_checkpoint_restores_deleted_file_and_removes_created_file(tmp_path):
    (tmp_path / "a.py").write_text("new-content", encoding="utf-8")
    checkpoint = {
        "safe_targets": ["a.py", "b.py"],
        "files": [
            {"path": "a.py", "exists": True, "content": "original-content"},
            {"path": "b.py", "exists": False, "content": None},
        ],
    }
    (tmp_path / "b.py").write_text("created-by-operator", encoding="utf-8")

    result = runner_mod._restore_operator_checkpoint(checkpoint, tmp_path, changed_paths=["a.py", "b.py"])

    assert result == {"attempted": True, "restored": True, "reason": "restored_checkpoint"}
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "original-content"
    assert not (tmp_path / "b.py").exists()


# ---------------------------------------------------------------------------
# worktree/queue scheduling helpers (fan-out isolation)
# ---------------------------------------------------------------------------

class _FakeAllocation:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeWorktreeQueue:
    def __init__(self, *, register_error=None, allocate_error=None):
        self.register_error = register_error
        self.allocate_error = allocate_error
        self.registered = []
        self.allocated = []
        self.recorded = []
        self.torn_down = []

    def register_tasks(self, specs):
        self.registered.extend(specs)
        if self.register_error:
            raise self.register_error

    def allocate(self, spec, **kwargs):
        if self.allocate_error:
            raise self.allocate_error
        self.allocated.append((spec, kwargs))
        return _FakeAllocation(
            task_id=spec.id, run_id="run-x", mode=kwargs.get("isolation", "worktree"),
            path="", branch="lane/" + spec.id, base_sha="base", head_sha="head",
            tree_sha="tree", lane="lane-1", reattached=False, lock_receipt="",
        )

    def record_context(self, task_id, context):
        self.recorded.append((task_id, context))

    def teardown(self, task_id):
        self.torn_down.append(task_id)


def _item(repo, run_id="run-x", task_index=1, isolation="worktree"):
    return {"repo": str(repo), "run_id": run_id, "task_index": task_index,
            "worker_id": f"w{task_index}", "task_id": f"task-{task_index}",
            "isolation": isolation}


def test_prepare_worktree_contexts_noop_without_a_queue(tmp_path):
    items = [_item(tmp_path)]
    runner_mod._prepare_worktree_contexts(items, None)
    assert "worktree_context" not in items[0]
    assert "worktree_error" not in items[0]


def test_prepare_worktree_contexts_rejects_unsupported_isolation_mode(tmp_path):
    queue = _FakeWorktreeQueue()
    items = [_item(tmp_path, isolation="branch")]
    runner_mod._prepare_worktree_contexts(items, queue)
    assert "unsupported worktree isolation mode" in items[0]["worktree_error"]


def test_prepare_worktree_contexts_defers_shared_isolation(tmp_path):
    queue = _FakeWorktreeQueue()
    items = [_item(tmp_path, isolation="shared")]
    runner_mod._prepare_worktree_contexts(items, queue)
    assert items[0]["worktree_deferred"] is True
    assert items[0]["isolation_key"] == f"{items[0]['repo']}:run-x"
    assert queue.allocated == []


def test_prepare_worktree_contexts_allocates_worktree_and_records_context(tmp_path):
    queue = _FakeWorktreeQueue()
    items = [_item(tmp_path)]
    runner_mod._prepare_worktree_contexts(items, queue)
    assert "worktree_error" not in items[0]
    assert items[0]["worktree_context"]["task_id"] == "task-1"
    assert len(queue.recorded) == 1


def test_prepare_worktree_contexts_marks_error_when_register_tasks_raises(tmp_path):
    queue = _FakeWorktreeQueue(register_error=RuntimeError("registration boom"))
    items = [_item(tmp_path, task_index=1), _item(tmp_path, task_index=2)]
    runner_mod._prepare_worktree_contexts(items, queue)
    assert "registration boom" in items[0]["worktree_error"]
    assert "registration boom" in items[1]["worktree_error"]


def test_prepare_worktree_contexts_marks_error_when_allocate_raises(tmp_path):
    queue = _FakeWorktreeQueue(allocate_error=RuntimeError("allocate boom"))
    items = [_item(tmp_path)]
    runner_mod._prepare_worktree_contexts(items, queue)
    assert "allocate boom" in items[0]["worktree_error"]


def test_ensure_deferred_worktree_context_allocates_shared_lease_once(tmp_path):
    queue = _FakeWorktreeQueue()
    item = _item(tmp_path, isolation="shared")
    item["worktree_deferred"] = True

    runner_mod._ensure_deferred_worktree_context(item, queue)

    assert item["worktree_context"]["task_id"] == "task-1"
    assert len(queue.allocated) == 1

    # A second call is a no-op: the context is already present.
    runner_mod._ensure_deferred_worktree_context(item, queue)
    assert len(queue.allocated) == 1


def test_ensure_deferred_worktree_context_skips_when_not_deferred(tmp_path):
    queue = _FakeWorktreeQueue()
    item = _item(tmp_path)

    runner_mod._ensure_deferred_worktree_context(item, queue)

    assert "worktree_context" not in item
    assert queue.allocated == []


def test_ensure_deferred_worktree_context_records_error_on_allocate_failure(tmp_path):
    queue = _FakeWorktreeQueue(allocate_error=RuntimeError("shared lease unavailable"))
    item = _item(tmp_path, isolation="shared")
    item["worktree_deferred"] = True

    runner_mod._ensure_deferred_worktree_context(item, queue)

    assert "shared lease unavailable" in item["worktree_error"]


def test_release_shared_context_tears_down_only_shared_mode(tmp_path):
    queue = _FakeWorktreeQueue()
    shared_item = {"worktree_context": {"mode": "shared", "task_id": "task-1"}}
    worktree_item = {"worktree_context": {"mode": "worktree", "task_id": "task-2"}}

    runner_mod._release_shared_context(shared_item, queue)
    runner_mod._release_shared_context(worktree_item, queue)

    assert queue.torn_down == ["task-1"]


def test_release_shared_context_swallows_teardown_exceptions(tmp_path):
    class _RaisingQueue(_FakeWorktreeQueue):
        def teardown(self, task_id):
            raise RuntimeError("teardown boom")

    queue = _RaisingQueue()
    item = {"worktree_context": {"mode": "shared", "task_id": "task-1"}}

    runner_mod._release_shared_context(item, queue)  # must not raise


# ---------------------------------------------------------------------------
# reconcile_delivery: a corrupt prior receipt is tolerated, not fatal
# ---------------------------------------------------------------------------

def test_reconcile_delivery_tolerates_corrupt_prior_receipt(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    (run_dir / "delivery-receipt.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(
        runner_mod, "build_delivery_receipt",
        lambda run_dir_arg, target, **kwargs: {
            "target": target, "current_state": kwargs["current_state"], "ready": True,
            "source_checked_at": "2026-07-14T00:00:00Z", "gates": [],
        },
    )
    monkeypatch.setattr(runner_mod, "reconcile_delivery_observation", lambda prev, cur: {"status": "confirmed"})
    monkeypatch.setattr(runner_mod, "write_delivery_receipt", lambda run_dir_arg, receipt: None)

    result = runner_mod.reconcile_delivery(str(repo), run_id, "pr-open", source_kind="github")

    assert result["state"]["delivery"]["ready"] is True


# ---------------------------------------------------------------------------
# apply_human_decision: resolves a decision-ledger item (not only bucket items)
# ---------------------------------------------------------------------------

def test_apply_human_decision_resolves_decision_ledger_item(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    contract_path = runner_mod._contract_path(run_dir)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["tasks"][0]["decision_ledger"] = [{"id": "Q-LEDGER-1", "resolved": False}]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    result = runner_mod.apply_human_decision(str(repo), run_id, "Q-LEDGER-1", "resolved answer")

    assert result["state"]["phase"] == "awaiting_decision"
    updated = json.loads(contract_path.read_text(encoding="utf-8"))
    ledger_item = updated["tasks"][0]["decision_ledger"][0]
    assert ledger_item["resolved"] is True
    assert ledger_item["answer"] == "resolved answer"


def test_operator_dispatch_attempt_fails_closed_on_worktree_error(tmp_path):
    item = {
        "repo": str(tmp_path), "run_id": "run-x", "task_index": 1, "worker_id": "w1",
        "task_id": "task-1", "worktree_error": "allocation failed: disk full",
    }

    record = runner_mod._operator_dispatch_attempt(item)

    assert record["status"] == "failed"
    assert record["reason_code"] == "worktree_context_unpersisted"
    assert record["execution_state"] == "error"
    assert record["failure_fingerprint"]


def test_operator_dispatch_attempt_wraps_unexpected_exception(tmp_path, monkeypatch):
    def raising_execute_operator(repo, run_id, task_index=1, **kwargs):
        raise RuntimeError("execute_operator exploded")

    monkeypatch.setattr(runner_mod, "execute_operator", raising_execute_operator)
    item = {"repo": str(tmp_path), "run_id": "run-x", "task_index": 1, "worker_id": "w1", "task_id": "task-1"}

    record = runner_mod._operator_dispatch_attempt(item)

    assert record["status"] == "failed"
    assert record["reason_code"] == "operator_exception"
    assert "execute_operator exploded" in record["error"]
    assert record["failure_fingerprint"]


def test_openrouter_to_mechanical_edit_fails_closed_without_host_plan(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)

    def opener(*_args, **_kwargs):
        raise AssertionError("OpenRouter must not be called without a host plan")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.setenv("SIMPLICIO_MODEL", "test-model")
    monkeypatch.setenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "0")
    monkeypatch.delenv("SIMPLICIO_PROVIDER_WORKER", raising=False)
    monkeypatch.setattr(runner_mod, "_openrouter_operator_enabled", lambda: True)
    monkeypatch.setattr(openrouter_operator.urllib.request, "urlopen", opener)
    monkeypatch.setattr(
        runner_mod,
        "_execute_operator_effect",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("apply must be skipped")),
    )

    result = runner_mod._execute_operator_unleased(str(repo), run_id)

    receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert receipt["reason_code"] == "plan_required"
    assert receipt["execution_state"] == "blocked"
    assert receipt["provider_config"]["route"] == "openrouter-to-mechanical-edit"
    assert result["state"]["phase"] == "blocked"


def test_host_edit_plan_applies_without_calling_openrouter(tmp_path, monkeypatch):
    repo, run_id, run_dir = _arm_fixture(tmp_path, monkeypatch)
    plan = {
        "schema": "simplicio.dev-cli.edit-plan/v1",
        "operations": [
            {"op": "replace_range", "path": "src/app.py", "start_line": 1, "end_line": 2, "text": "def main():\n    return 'fixed'\n"},
        ],
    }
    (run_dir / "edit-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def opener(*_args, **_kwargs):
        raise AssertionError("OpenRouter must not generate a host plan")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.example/api/v1")
    monkeypatch.setenv("SIMPLICIO_MODEL", "test-model")
    monkeypatch.setenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "0")
    monkeypatch.setattr(runner_mod, "_openrouter_operator_enabled", lambda: True)
    monkeypatch.setattr(openrouter_operator.urllib.request, "urlopen", opener)
    monkeypatch.setattr(runner_mod, "gate_completion", lambda _evidence: (True, ""))

    def fake_effect(*, argv, repo_path, **_kwargs):
        assert "edit" in argv
        plan_path = Path(argv[argv.index("--plan") + 1])
        loaded = json.loads(plan_path.read_text(encoding="utf-8"))
        assert loaded["schema"] == "simplicio.dev-cli.edit-plan/v1"
        operation = loaded["operations"][0]
        target = repo_path / operation["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(operation["text"], encoding="utf-8")
        return {
            "returncode": 0,
            "stdout": {},
            "stderr": "",
            "source": "test",
            "effect_receipt": {},
            "uncertain": False,
            "hookwall_evidence": {},
        }

    monkeypatch.setattr(runner_mod, "_execute_operator_effect", fake_effect)
    result = runner_mod._execute_operator_unleased(str(repo), run_id)
    receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert receipt["provider_config"]["route"] == "host-edit-plan"
    assert receipt["execution_state"] in {"applied", "no_change"}
    assert result["state"]["operator"]["execution_state"] == receipt["execution_state"]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _selfrun import run_module
    run_module(globals(), "test_runner_state_machine_unit")
