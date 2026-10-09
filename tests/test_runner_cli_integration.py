import hashlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import pytest

from simplicio_loop import runner as runner_mod
from tests._contract_only_hookwall import ContractOnlyHookwallLedger


@pytest.fixture(autouse=True)
def _contract_only_hookwall(monkeypatch):
    patch_runner(monkeypatch, "_hookwall_ledger",
        lambda *_args, **_kwargs: ContractOnlyHookwallLedger(),
    )
from simplicio_loop.oracle import persist_completion_receipt
from tests.planning_gate_fixtures import stage_valid_planning_receipt
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner
from tests.runner_patch import patch_runner

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = [sys.executable, "-m", "simplicio_loop.cli"]

TASK = """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenação de linhas
Tipo: Evolução

COMO analista do ONS,
QUERO organizar as linhas
PARA melhorar a análise

1. Critérios de Aceite

Cenário 1: Estrutural aparece primeiro
  Dado que existe uma linha estrutural
  Quando a tela for exibida
  Então a linha estrutural aparece primeiro [RN01]

2. Regras de Negócio

RN01 – Estrutural sempre primeiro.
"""


def _run(cmd, cwd, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30,
                          stdin=subprocess.DEVNULL, env=full_env)


def _arm_result(repo, task, *, env=None, delivery="verified", max_iterations=12):
    """Exercise the explicit preparation API for tests that need an armed intermediate run."""
    with patch.dict(os.environ, env or {}, clear=False):
        payload = runner_mod.arm_run(
            str(repo), str(task), delivery, max_iterations,
        )
    return subprocess.CompletedProcess(
        args=["arm_run"], returncode=0,
        stdout=json.dumps(payload, ensure_ascii=False), stderr="",
    )


def test_repo_state_equivalent_ignores_dirty_status_noise_when_tree_is_stable():
    before = {
        "head": "abc123",
        "dirty_status_hash": "before",
        "tree_hash": "tree-1",
    }
    after = {
        "head": "abc123",
        "dirty_status_hash": "after",
        "tree_hash": "tree-1",
    }

    assert runner_mod._repo_state_equivalent(before, after) is True
    assert runner_mod._repo_state_equivalent(before, {**after, "tree_hash": "tree-2"}) is False
    assert runner_mod._repo_state_equivalent(before, {**after, "head": "def456"}) is False


def test_plan_relevant_changed_paths_ignores_loop_owned_storage(monkeypatch, tmp_path):
    patch_runner(monkeypatch, "_changed_paths",
        lambda _repo: [
            ".simplicio-loop/events.jsonl",
            ".simplicio-loop/loop-runs/run-1/state.json",
            "site/checkers.html",
            "requirements/checkers-tasks.md",
        ],
    )

    assert runner_mod._plan_relevant_changed_paths(tmp_path) == [
        "requirements/checkers-tasks.md",
        "site/checkers.html",
    ]


def test_loop_generated_framework_artifacts_do_not_change_repo_fingerprint(tmp_path):
    before = runner_mod._repo_fingerprint(tmp_path)
    generated = [
        tmp_path / ".agents" / "_generated" / "run-1" / "task.agent.md",
        tmp_path / ".catalog" / "_generated" / "run-1" / "generation-receipt.json",
        tmp_path / ".catalog" / "project-capabilities.json",
        tmp_path / ".skills" / "_generated" / "run-1" / "task" / "SKILL.md",
    ]
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("framework-owned\n", encoding="utf-8")

    after = runner_mod._repo_fingerprint(tmp_path)

    assert before["tree_hash"] == after["tree_hash"]
    assert before["dirty_status_hash"] == after["dirty_status_hash"]


def test_external_completion_response_is_persisted_after_gated_execution(tmp_path):
    run_dir = tmp_path / "run"
    loop_dir = run_dir / "loop"
    loop_dir.mkdir(parents=True)
    (loop_dir / "scratchpad.md").write_text(
        'completion_promise: "run-123-verified"\n', encoding="utf-8"
    )
    (run_dir / "operator-receipt.json").write_text(json.dumps({
        "provider_config": {"route": "openrouter-to-mechanical-edit"},
    }), encoding="utf-8")

    path = runner_mod._persist_external_completion_response(run_dir)

    assert path.endswith("/loop/last_response.txt")
    assert (loop_dir / "last_response.txt").read_text(encoding="utf-8") == (
        "<promise>run-123-verified</promise>\n"
        "Coordinator response persisted after independent watcher and quality gates: "
        f"{loop_dir / 'watcher_state.json'}\n"
    )


def test_verified_external_run_materializes_append_only_loop_journal(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "loop").mkdir(parents=True)

    path = runner_mod._ensure_verified_loop_journal(run_dir)

    assert path.endswith("/loop/journal.jsonl")
    record = json.loads((run_dir / "loop" / "journal.jsonl").read_text(encoding="utf-8"))
    assert record["gate"] == "pass"
    assert record["execution_state"] == "verified"


def test_verified_loop_journal_does_not_rewrite_existing_attempt_memory(tmp_path):
    run_dir = tmp_path / "run"
    loop_dir = run_dir / "loop"
    loop_dir.mkdir(parents=True)
    original = '{"iteration":1,"action":"attempt","hypothesis":"h","gate":"blocked","fingerprint":"abc123def456","note":"n","ts":"2026-01-01T00:00:00Z"}\n'
    (loop_dir / "journal.jsonl").write_text(original, encoding="utf-8")

    runner_mod._ensure_verified_loop_journal(run_dir)

    assert (loop_dir / "journal.jsonl").read_text(encoding="utf-8") == original


def test_operator_env_defaults_to_codex_gpt54_medium(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_CODEX_EFFORT", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_OPERATOR_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_OPERATOR_EFFORT", raising=False)

    env = runner_mod._operator_env()

    assert env["SIMPLICIO_MODEL"] == "codex-cli/gpt-5.4"
    assert env["SIMPLICIO_CODEX_EFFORT"] == "medium"


def test_operator_env_preserves_explicit_outer_configuration(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/custom-model")
    monkeypatch.setenv("SIMPLICIO_CODEX_EFFORT", "high")
    monkeypatch.setenv("SIMPLICIO_LOOP_OPERATOR_MODEL", "codex-cli/gpt-5.4")
    monkeypatch.setenv("SIMPLICIO_LOOP_OPERATOR_EFFORT", "medium")

    env = runner_mod._operator_env()

    assert env["SIMPLICIO_MODEL"] == "codex-cli/custom-model"
    assert env["SIMPLICIO_CODEX_EFFORT"] == "high"


def test_mapper_preflight_requires_receipt_contract_minimum(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    run_root = repo / "run"
    repo.mkdir()
    run_root.mkdir()
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON", json.dumps({
        "version_stdout": "simplicio-mapper 0.18.9",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
    }))

    with pytest.raises(RuntimeError, match="below minimum version"):
        runner_mod._preflight_mapper(repo, run_root)

    receipt = json.loads((run_root / "mapper-preflight.json").read_text(encoding="utf-8"))
    assert receipt["min_version"] == "0.19.0"
    assert receipt["version_ok"] is False


def test_operator_timeout_defaults_and_override(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOOP_OPERATOR_TIMEOUT_SEC", raising=False)
    assert runner_mod._operator_timeout("dry_run") == 60
    assert runner_mod._operator_timeout("execute") == 600

    monkeypatch.setenv("SIMPLICIO_LOOP_OPERATOR_TIMEOUT_SEC", "450")
    assert runner_mod._operator_timeout("dry_run") == 450
    assert runner_mod._operator_timeout("execute") == 450


def test_operator_env_promotes_loop_test_cmd_when_test_cmd_missing(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    monkeypatch.setenv("SIMPLICIO_LOOP_TEST_CMD", "python -m pytest tests/python/test_task_spec.py -q")

    env = runner_mod._operator_env()

    assert env["SIMPLICIO_TEST_CMD"] == "python -m pytest tests/python/test_task_spec.py -q"


def test_devcli_cmd_prefers_repo_checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / "simplicio").mkdir(parents=True)
    (repo / "simplicio" / "cli.py").write_text("print('ok')\n", encoding="utf-8")

    cmd = runner_mod._devcli_cmd(repo, "task", "--help")
    env = runner_mod._devcli_env(repo, {"PYTHONPATH": "BASE"})

    assert cmd[:3] == [sys.executable, "-m", "simplicio.cli"]
    assert cmd[3:] == ["task", "--help"]
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(repo)
    assert env["SIMPLICIO_LOCAL_LLM_DISABLED"] == "1"
    assert "--local" not in cmd


def test_devcli_env_removes_local_model_selector(tmp_path):
    env = runner_mod._devcli_env(tmp_path, {"SIMPLICIO_MODEL": "local/qwen"})

    assert env["SIMPLICIO_LOCAL_LLM_DISABLED"] == "1"
    assert "SIMPLICIO_MODEL" not in env



def test_task_spec_payload_preserves_loop_contract_and_source():
    task = runner_mod.compile_many(TASK, source_path="issue-299.md")["tasks"][0]
    payload = runner_mod._task_spec_payload(task)

    assert payload["schema"] == "simplicio.task-spec/v2"
    assert payload["original_text"] == task["original_text"]
    assert payload["loop_task_contract"] == task
    assert payload["acceptance_criteria"][0]["id"] == "SCN1"
    assert len(payload["source_hash"]) == 64
    assert payload["source"]["locator"] == "issue-299.md"


def test_task_spec_payload_uses_declared_test_command(monkeypatch):
    task = runner_mod.compile_many(TASK)["tasks"][0]
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "npm test")

    payload = runner_mod._task_spec_payload(task)

    assert payload["verification_commands"] == [{"command": "npm test", "verifier": "declared"}]


def test_prepare_operator_receipt_uses_typed_task_spec_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "worker.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    task = runner_mod.compile_many(TASK)["tasks"][0]
    captured = {}

    patch_runner(monkeypatch, "_preflight_operator", lambda *args: {})

    def fake_run(argv, **kwargs):
        if "edit" in argv or "task" in argv:
            captured["task_argv"] = list(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    receipt = runner_mod._prepare_operator_receipt(repo, run_root, task, "src/worker.py")
    task_spec_path = run_root / "task-spec.json"
    task_spec = json.loads(task_spec_path.read_text(encoding="utf-8"))

    assert receipt["returncode"] == 0
    task_argv = captured["task_argv"]
    # The dry run proves the plan surface; it never calls the prose `task` path.
    assert task_argv[-2:] == ["edit", "--help"]
    assert "task" not in task_argv
    assert task_spec["original_text"] == task["original_text"]
    assert receipt["task_spec_path"] == str(task_spec_path)
    assert receipt["task_spec_hash"] == hashlib.sha256(
        json.dumps(task_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_prepare_operator_receipt_propagates_canonical_context_when_mapper_supplies_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "worker.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    handle = "sha256:" + "a" * 64
    (run_root / "mapper-context.json").write_text(json.dumps({
        "handoff": {"stdout": {
            "context_snapshot": {"schema": "simplicio.context-snapshot/v1", "snapshot_id": "snap-1"},
            "canonical_context_pack": {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-1"},
            "execution_context": {"schema": "simplicio.execution-context/v1", "snapshot_id": "snap-1"},
            "context_handle": handle,
        }}
    }), encoding="utf-8")
    task = runner_mod.compile_many(TASK)["tasks"][0]
    captured = {}

    patch_runner(monkeypatch, "_preflight_operator", lambda *args: {})

    def fake_run(argv, **kwargs):
        if "edit" in argv or "task" in argv:
            captured["task_argv"] = list(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    receipt = runner_mod._prepare_operator_receipt(repo, run_root, task, "src/worker.py")
    task_argv = captured["task_argv"]

    assert receipt["context_handoff"]["status"] == "propagated"
    assert receipt["context_handoff"]["context_handle"] == handle
    assert task_argv[-2:] == ["edit", "--help"]
    assert json.loads((run_root / "context-snapshot.json").read_text(encoding="utf-8"))["snapshot_id"] == "snap-1"
    assert json.loads((run_root / "context-pack.json").read_text(encoding="utf-8"))["pack_hash"] == "pack-1"
    assert json.loads((run_root / "execution-context.json").read_text(encoding="utf-8"))["snapshot_id"] == "snap-1"


def test_prepare_operator_receipt_uses_standalone_degraded_context_pack(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "worker.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "mapper-context.json").write_text(json.dumps({
        "degraded_local": True,
        "handoff": {"stdout": {"context_pack": {
            "schema": "simplicio.context-pack/v1",
            "pack_hash": "pack-degraded",
            "files": [{"path": "src/worker.py"}],
            "fidelity": {"gate": "degraded_local", "status": "UNVERIFIED"},
        }}},
    }), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    monkeypatch.setenv("SIMPLICIO_LOOP_ALLOW_DEGRADED_MAPPER", "1")
    task = runner_mod.compile_many(TASK)["tasks"][0]
    captured = {}

    patch_runner(monkeypatch, "_preflight_operator", lambda *args: {})

    def fake_run(argv, **kwargs):
        if "edit" in argv or "task" in argv:
            captured["task_argv"] = list(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    receipt = runner_mod._prepare_operator_receipt(repo, run_root, task, "src/worker.py")

    task_argv = captured["task_argv"]
    assert receipt["context_handoff"]["status"] == "degraded_local"
    assert task_argv[-2:] == ["edit", "--help"]
    assert "task" not in task_argv


def test_context_handoff_uses_snapshot_fallback_without_requiring_handle(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    snapshot_dir = repo / ".simplicio-loop"
    snapshot_dir.mkdir()
    (snapshot_dir / "context-snapshot.json").write_text(
        json.dumps({"schema": "simplicio.context-snapshot/v1", "snapshot_id": "snap-fallback"}),
        encoding="utf-8",
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "mapper-context.json").write_text(json.dumps({
        "handoff": {"stdout": {
            "context_pack": {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-1"},
            "execution_context": {"schema": "simplicio.execution-context/v1", "snapshot_id": "snap-fallback"},
        }}
    }), encoding="utf-8")

    args, receipt = runner_mod._context_handoff_args(repo, run_root)

    assert receipt["status"] == "propagated", receipt
    assert "--context-handle" not in args
    assert args[args.index("--context-snapshot") + 1] == str(snapshot_dir / "context-snapshot.json")
    assert json.loads((run_root / "context-pack.json").read_text(encoding="utf-8"))["pack_hash"] == "pack-1"
    assert json.loads((run_root / "execution-context.json").read_text(encoding="utf-8"))["snapshot_id"] == "snap-fallback"


def test_context_handoff_derives_handle_when_mapper_omits_it(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    handle = "sha256:" + "b" * 64
    (run_root / "mapper-context.json").write_text(json.dumps({
        "handoff": {"stdout": {
            "context_snapshot": {"schema": "simplicio.context-snapshot/v1", "snapshot_id": "snap-2"},
            "context_pack": {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-2"},
            "execution_context": {"schema": "simplicio.execution-context/v1", "snapshot_id": "snap-2"},
        }}
    }), encoding="utf-8")
    patch_runner(monkeypatch, "_derive_context_handle", lambda *args: handle)

    args, receipt = runner_mod._context_handoff_args(repo, run_root)

    assert receipt["context_handle"] == handle
    assert args[args.index("--context-handle") + 1] == handle


def test_run_mapper_requests_snapshot_and_execution_context(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TOKEN_BUDGET", "24000")
    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", "2400")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": True,
        "help_stdout": "  snapshot build",
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    runner_mod._run_mapper(repo, run_root, goal="goal", target_hint="src/app.py")

    assert ["simplicio-mapper", "snapshot", "build", "--json", "."] in calls
    initial_scan = next(argv for argv in calls if argv[:2] == ["simplicio-mapper", "scan"])
    initial_inspect = next(argv for argv in calls if argv[:2] == ["simplicio-mapper", "inspect"])
    assert initial_scan[initial_scan.index("--timeout") + 1] == "2400"
    assert initial_inspect[initial_inspect.index("--timeout") + 1] == "2400"
    assert "--await" not in initial_scan
    assert "--await" not in initial_inspect
    assert "--sync" not in initial_scan
    assert any(
        argv[:2] == ["simplicio-mapper", "inspect"] and "--await" in argv
        for argv in calls
    )
    handoff_argv = next(argv for argv in calls if argv[:2] == ["simplicio-mapper", "handoff"])
    assert "--execution-context" in handoff_argv
    assert "--await" not in handoff_argv
    assert handoff_argv[handoff_argv.index("--timeout") + 1] == "2400"
    assert handoff_argv[handoff_argv.index("--target") + 1] == "src/app.py"


    assert handoff_argv[handoff_argv.index("--token-budget") + 1] == "24000"


def test_run_mapper_reconciles_stale_inspect_after_handoff(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    inspect_calls = 0

    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": False,
        "help_stdout": "",
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        nonlocal inspect_calls
        if argv[:2] == ["simplicio-mapper", "inspect"]:
            inspect_calls += 1
            fresh = inspect_calls == 3
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": {"artifacts_present": True, "fresh": fresh}}),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root)

    assert inspect_calls == 3
    assert result["inspect"]["stdout"]["status"]["fresh"] is True
    assert "inspect_reconcile_wall_seconds" in result["execution_route"]["phase_timings_seconds"]


def test_run_mapper_sync_rollback_is_explicit_and_receipted(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_SYNC_ROLLBACK", "1")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": False, "help_stdout": ""
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        if argv[:2] == ["simplicio-mapper", "scan"]:
            stdout = {"deep": {"job_id": "job-1", "pid": 42}}
        else:
            stdout = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(stdout), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root)

    scan = next(argv for argv in calls if argv[:2] == ["simplicio-mapper", "scan"])
    assert "--sync" in scan
    assert result["execution_route"]["mode"] == "synchronous_rollback"
    assert result["execution_route"]["background"] == {
        "status": "consumed_by_sync_rollback", "work_id": "job-1", "pid": 42,
        "state_path": None,
    }
    assert result["execution_route"]["phase_timings_seconds"]["scan_wall_seconds"] >= 0


def test_cancel_run_stops_queued_mapper_background_job(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_dir = repo / ".simplicio-loop" / "loop-runs" / "run-1"
    run_dir.mkdir(parents=True)
    state = {
        "run_id": "run-1",
        "phase": "mapping",
        "mapper": {
            "execution_route": {
                "background": {"status": "queued", "work_id": "job-1", "pid": 42}
            }
        },
    }
    calls = []

    patch_runner(monkeypatch, "read_status", lambda *_args: {
        "run_dir": str(run_dir), "state": state, "manifest": {}
    })
    patch_runner(monkeypatch, "_run_cmd", lambda argv, cwd: (
        calls.append((argv, cwd)) or SimpleNamespace(
            returncode=0, stdout=json.dumps({"status": "cancelled"}), stderr=""
        )
    ))
    patch_runner(monkeypatch, "_transition", lambda *_args, **_kwargs: None)

    runner_mod.change_phase(str(repo), "run-1", "cancelled", "operator stop")

    assert calls[0][0] == ["simplicio-mapper", "background", "cancel", ".", "--json"]
    receipt = json.loads((run_dir / "mapper-background-cancel.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "cancelled"
    assert state["mapper"]["execution_route"]["background"]["status"] == "cancelled"


def test_run_mapper_preserves_explicit_target_when_handoff_omits_it(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": True, "help_stdout": ""
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        if argv[:2] == ["simplicio-mapper", "handoff"]:
            stdout = {"context_pack": {"files": [{"path": "scripts/other.py"}]}}
        else:
            stdout = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(stdout), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root, target_hint="src/app.py")
    files = result["handoff"]["stdout"]["context_pack"]["files"]
    assert {item["path"] for item in files} == {"scripts/other.py", "src/app.py"}
    assert result["handoff"]["stdout"]["context_pack"]["explicit_target_added"] == "src/app.py"


def test_mapper_subprocess_uses_configured_timeout(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", "17")

    def fake_subprocess_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_subprocess_run)
    runner_mod._run_cmd(["simplicio-mapper", "scan", "."], tmp_path)
    runner_mod._run_cmd(["git", "status"], tmp_path)

    assert calls[0][1]["timeout"] == 17
    assert calls[1][1]["timeout"] == 180


def test_mapper_timeout_becomes_degraded_receipt_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", "17")

    def fake_subprocess_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output="partial", stderr="worker stalled")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_subprocess_run)
    result = runner_mod._run_cmd(["simplicio-mapper", "scan", "."], tmp_path)

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert "worker stalled" in result.stderr
    assert "timed out after 17s" in result.stderr


def test_run_mapper_ignores_invalid_mapper_token_budget(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TOKEN_BUDGET", "invalid")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": True,
        "help_stdout": "",
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    runner_mod._run_mapper(repo, run_root, goal="goal")

    handoff_argv = next(argv for argv in calls if argv[:2] == ["simplicio-mapper", "handoff"])
    assert "--token-budget" not in handoff_argv


def test_run_mapper_skips_unsupported_optional_snapshot(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.delenv("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", raising=False)
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": False,
        "help_stdout": "  inspect <path>\n  handoff <path>",
    })
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root)

    assert result["snapshot"]["returncode"] == 0
    assert result["snapshot"]["stdout"]["reason"] == "optional_command_unavailable"
    assert not any(argv[:2] == ["simplicio-mapper", "snapshot"] for argv in calls)
    assert any(argv[:2] == ["simplicio-mapper", "scan"] and "--timeout" in argv for argv in calls)


def test_run_mapper_degrades_to_explicit_local_target_on_scan_timeout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls = []

    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    monkeypatch.setenv("SIMPLICIO_LOOP_LOCAL_FALLBACK", "1")
    monkeypatch.setenv("SIMPLICIO_LOOP_ALLOW_DEGRADED_MAPPER", "1")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": True,
        "help_stdout": "  inspect <path>\n  handoff <path>",
    })

    def fake_run(argv, cwd):
        calls.append(list(argv))
        if argv[1] == "scan":
            return SimpleNamespace(
                returncode=1,
                stdout=json.dumps({"deep": {"failure_reason": "scan_timeout"}}),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"ready": False, "context_pack": {}}),
            stderr="",
        )

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(
        repo, run_root, target_hint="src/app.py", goal="update app",
    )

    assert result["degraded_local"] is True
    assert result["evidence_status"] == "UNVERIFIED"
    assert result["handoff"]["stdout"]["ready"] is True
    assert result["handoff"]["stdout"]["context_pack"]["files"][0]["path"] == "src/app.py"
    assert result["handoff"]["stdout"]["context_pack"]["fidelity"]["gate"] == "degraded_local"
    assert any(argv[:2] == ["simplicio-mapper", "scan"] for argv in calls)


def test_run_mapper_degraded_pack_refuses_unbounded_candidates_without_target_hint(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "candidate.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()

    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "standalone")
    monkeypatch.setenv("SIMPLICIO_LOOP_LOCAL_FALLBACK", "1")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {
        "task_aware_supported": False,
        "help_stdout": "  inspect <path>\n  handoff <path>",
    })

    def fake_run(argv, cwd):
        return SimpleNamespace(returncode=1, stdout="{}", stderr="timed out")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(repo, run_root)

    files = result["handoff"]["stdout"]["context_pack"]["files"]
    assert files == []
    assert result["handoff"]["stdout"]["ready"] is False
    assert result["evidence_status"] == "UNVERIFIED"


def test_extract_repo_file_hints_accepts_rust_targets(tmp_path):
    repo = tmp_path / "repo"
    (repo / "rust").mkdir(parents=True)
    (repo / "rust" / "supervisor.rs").write_text("fn main() {}\n", encoding="utf-8")

    assert runner_mod._extract_repo_file_hints(
        "Arquivos alvo: rust/supervisor.rs", repo
    ) == ["rust/supervisor.rs"]


def test_extract_repo_file_hints_accepts_html_and_css_targets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    assert runner_mod._extract_repo_file_hints(
        "Arquivos alvo: site/index.html e site/styles.css; contrato: requirements/task.md",
        repo,
    ) == ["site/index.html", "site/styles.css"]


def test_build_plan_uses_mapper_summary_hash_and_task_scoped_creation_targets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = [
        {
            "identity": {"system": "PAGE-101", "feature": "landing", "type": "creation"},
            "original_text": "Arquivo-alvo: site/index.html",
            "scenarios": [{"id": "S1", "title": "landing", "rule_refs": ["RN1"],
                           "verification_intent": "file exists"}],
            "rules": [{"id": "RN1", "text": "must exist"}],
        },
        {
            "identity": {"system": "PAGE-102", "feature": "navigation", "type": "editing"},
            "original_text": "Arquivo-alvo: site/index.html",
            "scenarios": [{"id": "S2", "title": "navigation", "rule_refs": ["RN2"],
                           "verification_intent": "navigation exists"}],
            "rules": [{"id": "RN2", "text": "must preserve landing"}],
        },
    ]
    state = runner_mod._repo_fingerprint(repo)
    mapper_payload = {
        "handoff": {
            "stdout": {
                "context_pack": {
                    "summary": {"pack_hash": "pack-modern"},
                    "files": [{"path": "bench/verify.py"}],
                }
            }
        },
        "repo_state_before": state,
        "repo_state_after": state,
        "generated_at": "2026-07-10T00:00:00Z",
    }

    plan = runner_mod._build_plan_with_hints(
        tasks, mapper_payload, repo, "Arquivo-alvo: site/index.html; site/styles.css",
        contract_hash="contract-1",
    )

    assert plan["mapper_pack_hash"] == "pack-modern"
    assert plan["context_pack_hash"] == "pack-modern"
    assert plan["steps"][0]["candidate_targets"][0] == "site/index.html"
    assert plan["steps"][0]["to_create"] == ["site/index.html"]
    assert plan["steps"][1]["candidate_targets"][0] == "site/index.html"
    assert plan["steps"][1]["to_create"] == []


def test_build_plan_recognizes_portuguese_creation_task_type(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = [{
        "identity": {"system": "Simplicio", "feature": "damas", "type": "criação"},
        "original_text": "Target: site/checkers.html",
        "scenarios": [{"id": "S1", "title": "creation", "verification_intent": "file exists"}],
        "rules": [],
    }]
    state = runner_mod._repo_fingerprint(repo)
    mapper_payload = {
        "handoff": {
            "stdout": {
                "context_pack": {
                    "summary": {"pack_hash": "pack-checkers"},
                    "files": [{"path": "requirements/checkers-tasks.md"}],
                }
            }
        },
        "repo_state_before": state,
        "repo_state_after": state,
        "generated_at": "2026-09-12T00:00:00Z",
    }

    plan = runner_mod._build_plan_with_hints(
        tasks, mapper_payload, repo, "Target: site/checkers.html",
        contract_hash="checkers-contract",
    )

    assert plan["steps"][0]["candidate_targets"] == ["site/checkers.html"]
    assert plan["steps"][0]["to_create"] == ["site/checkers.html"]


def test_build_plan_uses_filtered_candidate_targets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "worker.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    (repo / "src" / "worker.rs").write_text("fn run() {}\n", encoding="utf-8")
    task_payload = runner_mod.compile_many(TASK, source_path="task.md")
    tasks = task_payload["tasks"]
    mapper_payload = {
        "handoff": {
            "stdout": {
                "context_pack": {
                    "pack_hash": "pack-1",
                    "files": [
                        {"path": ".simplicio-loop/orchestrator/loop/runtime_run_task.md"},
                        {"path": "docs/README.md"},
                        {"path": "src/worker.py"},
                        {"path": "src/worker.rs"},
                    ],
                }
            }
        },
        "repo_state_before": {"head": "abc", "tree_hash": "tree", "dirty_status_hash": "one"},
        "repo_state_after": {"head": "abc", "tree_hash": "tree", "dirty_status_hash": "two"},
        "generated_at": "2026-07-10T00:00:00Z",
    }

    plan = runner_mod._build_plan(tasks, mapper_payload, repo)
    assert plan["mapper_targets"] == ["src/worker.py", "src/worker.rs"], plan["mapper_targets"]
    assert plan["steps"][0]["candidate_targets"] == ["src/worker.py", "src/worker.rs"]


def test_build_plan_promotes_explicit_task_file_hints(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "simplicio").mkdir()
    (repo / "tests" / "python").mkdir(parents=True)
    (repo / "simplicio" / "task_spec.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "python" / "test_task_spec.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    task_payload = runner_mod.compile_many(TASK, source_path="task.md")
    tasks = task_payload["tasks"]
    mapper_payload = {
        "handoff": {
            "stdout": {
                "context_pack": {
                    "pack_hash": "pack-1",
                    "files": [
                        {"path": "bench/compare_sp.py"},
                    ],
                }
            }
        },
        "repo_state_before": {"head": "abc", "tree_hash": "tree", "dirty_status_hash": "one"},
        "repo_state_after": {"head": "abc", "tree_hash": "tree", "dirty_status_hash": "two"},
        "generated_at": "2026-07-10T00:00:00Z",
    }

    plan = runner_mod._build_plan_with_hints(
        tasks,
        mapper_payload,
        repo,
        "Arquivos alvo: simplicio/task_spec.py tests/python/test_task_spec.py",
    )
    assert plan["steps"][0]["candidate_targets"][:2] == [
        "simplicio/task_spec.py",
        "tests/python/test_task_spec.py",
    ]


def test_arm_run_writes_a_valid_dashboard_event_stream(tmp_path, monkeypatch):
    """#1398: a real armed run emits schema-valid dashboard events with gap-free seq."""
    from simplicio_loop import dashboard_events

    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path)
    payload = runner_mod.arm_run(str(repo), str(task), "verified", 9)
    run_dir = Path(payload["run_dir"])
    module = dashboard_events.load()
    assert module is not None
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
              if line.strip()]
    events = [evt for evt in events if evt.get("schema") == "simplicio.dashboard-event/v1"]
    assert events, "arm_run emitted no dashboard events"
    assert [evt["seq"] for evt in events] == list(range(1, len(events) + 1))
    assert all(module.validate_envelope(evt) == [] for evt in events)
    assert {evt["run_id"] for evt in events} == {payload["manifest"]["run_id"]}
    kinds = [evt["kind"] for evt in events]
    assert kinds[0] == "run_started"
    assert "phase_entered" in kinds
    assert "decision_requested" in kinds
    assert payload["state"]["phase"] == "awaiting_decision"


def test_arm_run_persists_state_for_status_resume_cancel(tmp_path, monkeypatch):
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path)
    payload = runner_mod.arm_run(str(repo), str(task), "verified", 9)
    run_id = payload["manifest"]["run_id"]
    run_dir = Path(payload["run_dir"])
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "state.json").exists()
    assert (run_dir / "task-contract.json").exists()
    assert (run_dir / "mapper-preflight.json").exists()
    assert (run_dir / "operator-preflight.json").exists()
    assert (run_dir / "mapper-context.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "operator-receipt.json").exists()
    assert (run_dir / "delivery-receipt.json").exists()
    assert (run_dir / "loop" / "scratchpad.md").exists()
    assert (run_dir / "loop" / "watcher_challenge.json").exists()
    assert payload["state"]["phase"] == "awaiting_decision"
    assert payload["state"]["mapper"]["ready"] is True
    assert payload["state"]["operator"]["ready"] is True
    assert payload["state"]["operator"]["execution_state"] == "dry_run"
    assert payload["state"]["delivery"]["target"] == "verified"
    assert payload["state"]["delivery"]["current_state"] == "implemented"

    status = _run(CLI + ["status", "--repo", str(repo), "--run-id", run_id], REPO,
                  env={})
    assert status.returncode == 0, status.stdout + status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["state"]["coverage"]["scenarios"]["total"] == 1
    assert status_payload["state"]["coverage"]["rules"]["total"] == 1
    assert status_payload["state"]["mapper"]["receipt"].endswith("mapper-context.json")
    assert status_payload["state"]["operator"]["receipt"].endswith("operator-receipt.json")
    assert status_payload["state"]["delivery"]["receipt"].endswith("delivery-receipt.json")
    assert status_payload["state"]["completion"]["reason_code"] == "oracle_incomplete"

    resumed = _run(CLI + ["resume", "--repo", str(repo), run_id], REPO)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["state"]["phase"] == "awaiting_decision"
    assert len(resumed_payload["state"]["history"]) >= 2

    cancelled = _run(CLI + ["cancel", "--repo", str(repo), run_id], REPO)
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
    cancelled_payload = json.loads(cancelled.stdout)
    assert cancelled_payload["state"]["phase"] == "cancelled"


def _start_run_for_maintenance_cli(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON", json.dumps({
        "version_stdout": "simplicio-mapper 0.19.0",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
        "version_returncode": 0,
        "help_returncode": 0,
    }))
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON", json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
        "help_returncode": 0,
    }))
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps({
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    return repo, armed["manifest"]["run_id"], Path(armed["run_dir"])


def test_maintenance_deferred_cli_serializes_mode_without_operator(tmp_path, monkeypatch):
    repo, run_id, run_dir = _start_run_for_maintenance_cli(tmp_path, monkeypatch)
    operator_receipt = run_dir / "operator-receipt.json"
    operator_before = operator_receipt.read_text(encoding="utf-8") if operator_receipt.exists() else None

    deferred = _run(CLI + [
        "maintenance-deferred", "--repo", str(repo), run_id,
        "--mode", "maintenance_deferred", "--disposition", "backlog_only",
        "--correction-summary", "Corrected the maintenance backlog entry.",
        "--deferral-reason", "Operator maintenance window is active.",
        "--resume-instruction", "Resume from the maintenance receipt.",
        "--resume-instruction", "Run the operator after maintenance.",
    ], REPO)
    assert deferred.returncode == 0, deferred.stdout + deferred.stderr
    status = json.loads(deferred.stdout)

    receipt = json.loads((run_dir / "maintenance-receipt.json").read_text(encoding="utf-8"))
    assert receipt["mode"] == "maintenance_deferred"
    assert receipt["disposition"] == "backlog_only"
    assert receipt["completion_ready"] is False
    if operator_before is None:
        assert not operator_receipt.exists()
    else:
        assert operator_receipt.read_text(encoding="utf-8") == operator_before
    assert status["state"]["completion"]["ready"] is False
    assert status["state"]["completion"]["tag"] == "UNVERIFIED"
    assert status["state"]["maintenance"]["mode"] == "maintenance_deferred"
    assert status["state"]["next_action"] == "resume_from_maintenance_receipt"


def test_maintenance_deferred_cli_rejects_non_deferred_mode(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_id = "missing-run"
    rejected = _run(CLI + [
        "maintenance-deferred", "--repo", str(repo), run_id,
        "--mode", "active", "--disposition", "backlog_only",
        "--correction-summary", "summary", "--deferral-reason", "reason",
    ], REPO)
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout) == {
        "ready": False,
        "reason_code": "maintenance_mode_invalid",
        "tag": "UNVERIFIED",
    }
    assert not (repo / ".simplicio-loop/orchestrator" / "runs" / run_id / "maintenance-receipt.json").exists()


def test_resume_rejects_terminal_cancelled_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    started = _arm_result(
        repo, task, env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator}
    )
    assert started.returncode == 0, started.stdout + started.stderr
    run_id = json.loads(started.stdout)["manifest"]["run_id"]
    cancelled = _run(CLI + ["cancel", "--repo", str(repo), run_id], REPO)
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr

    resumed = _run(CLI + ["resume", "--repo", str(repo), run_id], REPO)
    assert resumed.returncode != 0, resumed.stdout + resumed.stderr
    assert "run already terminal" in resumed.stderr or "run already terminal" in resumed.stdout


def test_cancel_rejects_terminal_cancelled_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    started = _arm_result(
        repo, task, env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator}
    )
    assert started.returncode == 0, started.stdout + started.stderr
    run_id = json.loads(started.stdout)["manifest"]["run_id"]
    cancelled = _run(CLI + ["cancel", "--repo", str(repo), run_id], REPO)
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr

    cancelled_again = _run(CLI + ["cancel", "--repo", str(repo), run_id], REPO)
    assert cancelled_again.returncode != 0, cancelled_again.stdout + cancelled_again.stderr
    assert "run already terminal" in cancelled_again.stderr or "run already terminal" in cancelled_again.stdout


def test_status_surfaces_completion_receipt_reason_code(tmp_path, monkeypatch):
    repo, _, payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = payload["manifest"]["run_id"]
    loop_dir = run_dir / "loop"
    receipt_payload = {
        "ready": False,
        "verdict": "DELIVERY_PENDING",
        "reason_code": "watcher_mismatch",
        "reason": "watcher receipt is not MEASURED/matching",
        "tag": "UNVERIFIED",
        "gates": [],
    }
    persist_completion_receipt(receipt_payload, str(loop_dir), str(run_dir))

    status = _run(CLI + ["status", "--repo", str(repo), "--run-id", run_id], REPO)
    assert status.returncode == 0, status.stdout + status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["state"]["completion"]["receipt"].endswith("completion-receipt.json")
    assert status_payload["state"]["completion"]["reason_code"] == "watcher_mismatch"


def test_tick_executes_real_operator_boundary_and_binds_receipt(tmp_path, monkeypatch):
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    stage_valid_planning_receipt(repo=repo, run_dir=run_dir, armed_payload=armed_payload,
                                 run_id=armed_payload["manifest"]["run_id"])
    env = {
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON": json.dumps({
            "returncode": 0, "stdout": {"kind": "operator-applied", "ok": True}, "stderr": "",
            "write_files": {"src/app.py": "def main():\n    return 'updated'\n"},
        }),
    }
    run_id = armed_payload["manifest"]["run_id"]
    with patch.dict(os.environ, env, clear=False):
        payload = runner_mod.execute_operator(str(repo), run_id)
    assert payload["state"]["phase"] == "validating"
    receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert receipt["mode"] == "execute"
    assert receipt["execution_state"] == "applied"
    assert receipt["attempt"] == 1
    assert receipt["retry_budget"] == 3
    assert receipt["failure_fingerprint"] == ""
    assert receipt["task_contract_hash"]
    assert receipt["plan_hash"]
    assert receipt["target_within_repo"] is True
    assert (run_dir / "operator-receipt-1.json").is_file()


def test_direct_tick_reuses_run_authority_attempt_after_prior_task(tmp_path, monkeypatch):
    from tests.test_store_adapter import fake_mapper

    fake_mapper(monkeypatch)
    monkeypatch.setenv("SIMPLICIO_STORAGE_ROUTE", "mapper")
    patch_runner(monkeypatch, "_ensure_mapper_operations_store",
        lambda *args, **kwargs: {"status": "ok", "route": "mapper"},
    )
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["attempts"] = 1
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    captured = {}

    class FakeLease:
        attempt_id = "attempt-2"
        lease_id = "lease-2"
        fence_token = 2

    class FakeOperations:
        def complete(self, lease, *, status, receipt):
            return {"status": status, "receipt": receipt}

    patch_runner(monkeypatch, "_claim_mapper_operation_attempt",
        lambda *args, **kwargs: (FakeOperations(), SimpleNamespace(lease=FakeLease())),
    )

    def fake_unleased(*args, **kwargs):
        captured["authority_attempt"] = kwargs["authority_attempt"]
        return {
            "state": {
                "operator": {"ready": True, "execution_state": "applied", "receipt": "operator.json"},
                "evidence": {"receipt": "evidence.json"},
            }
        }

    patch_runner(monkeypatch, "_execute_operator_unleased", fake_unleased)
    runner_mod.execute_operator(str(repo), run_id, task_index=1)

    assert captured["authority_attempt"] == 1


def test_tick_rolls_back_failed_operator_when_change_stays_within_authorized_target(tmp_path, monkeypatch):
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    stage_valid_planning_receipt(repo=repo, run_dir=run_dir, armed_payload=armed_payload,
                                 run_id=armed_payload["manifest"]["run_id"])
    target = repo / "src" / "app.py"
    original = target.read_text(encoding="utf-8")
    env = {
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON": json.dumps({
            "returncode": 1,
            "stdout": {"kind": "operator-applied", "ok": False},
            "stderr": "validation failed",
            "write_files": {"src/app.py": "def main():\n    return 'broken'\n"},
        }),
    }
    run_id = armed_payload["manifest"]["run_id"]
    with patch.dict(os.environ, env, clear=False):
        payload = runner_mod.execute_operator(str(repo), run_id)
    assert payload["state"]["phase"] == "blocked"
    assert target.read_text(encoding="utf-8") == original
    receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert receipt["attempt"] == 1
    assert receipt["retry_budget"] == 3
    assert receipt["failure_fingerprint"]
    assert receipt["rollback"]["attempted"] is True
    assert receipt["rollback"]["restored"] is True
    assert receipt["changed_paths"] == []
    assert receipt["checkpoint"]["safe_targets"] == ["src/app.py"]


def test_deliver_reconciles_external_delivery_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    fake_mapper_preflight = json.dumps({
        "version_stdout": "simplicio-mapper 0.19.0",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
        "version_returncode": 0,
        "help_returncode": 0
    })
    fake_devcli_preflight = json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
        "help_returncode": 0
    })
    started = _arm_result(
        repo, task, delivery="merge-ready", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
             "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
             "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    run_id = payload["manifest"]["run_id"]
    source_payload = {
        "pr": {"url": "https://example/pr/99", "head_sha": "abc123", "base_sha": "def456"},
        "checks": {"green": True},
        "reviews": {"approvals": 1, "open_threads": 0},
        "branch": {"up_to_date": True}
    }
    evidence_file = tmp_path / "merge-ready.json"
    evidence_file.write_text(json.dumps(source_payload), encoding="utf-8")
    delivered = _run(CLI + ["deliver", "--repo", str(repo), run_id, "--state", "merge-ready",
                            "--source-kind", "github", "--payload-file", str(evidence_file)], REPO)
    assert delivered.returncode == 0, delivered.stdout + delivered.stderr
    delivered_payload = json.loads(delivered.stdout)
    assert delivered_payload["state"]["delivery"]["current_state"] == "merge-ready"
    assert delivered_payload["state"]["delivery"]["ready"] is True
    assert delivered_payload["state"]["phase"] == "delivering"


def test_decide_invalidates_plan_and_receipts_after_human_answer(tmp_path, monkeypatch):
    task_text = TASK + """

3. Requisitos Não Funcionais

Nenhum requisito não-funcional identificado na entrada — validar com o time.

6. Dependências

Nenhuma dependência identificada na entrada — validar com o time.

7. Sinais de Impacto

Frontend: ✓
Backend: Possível
Banco: ✗
Integrações: ✗
"""
    repo, _, payload, run_dir = _arm_deterministic_preflight_fixture(
        monkeypatch, tmp_path, task_text=task_text,
    )
    run_id = payload["manifest"]["run_id"]
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "operator-receipt.json").exists()
    decided = _run(CLI + ["decide", "--repo", str(repo), run_id, "--decision-id", "Q-LAYER-1",
                          "--answer", "Implementar no frontend apenas", "--impact", "behavior-change"], REPO)
    assert decided.returncode == 0, decided.stdout + decided.stderr
    decided_payload = json.loads(decided.stdout)
    assert decided_payload["state"]["phase"] == "awaiting_decision"
    assert decided_payload["state"]["operator"]["execution_state"] == "invalidated"
    assert decided_payload["state"]["evidence"]["status"] == "INVALIDATED"
    assert not (run_dir / "plan.json").exists()
    assert not (run_dir / "operator-receipt.json").exists()
    assert not (run_dir / "evidence-receipt.json").exists()
    contract = json.loads((run_dir / "task-contract.json").read_text(encoding="utf-8"))
    task0 = contract["tasks"][0]
    match = next(item for item in task0["decision_ledger"] if item["id"] == "Q-LAYER-1")
    assert match["resolved"] is True
    assert match["answer"] == "Implementar no frontend apenas"


def test_sync_source_requeries_github_fixture_for_merge_ready(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    fake_mapper_preflight = json.dumps({
        "version_stdout": "simplicio-mapper 0.19.0",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
        "version_returncode": 0,
        "help_returncode": 0
    })
    fake_devcli_preflight = json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
        "help_returncode": 0
    })
    started = _arm_result(
        repo, task, delivery="merge-ready", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
             "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
             "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    run_id = payload["manifest"]["run_id"]
    fixture = json.dumps({
        "pr": {"url": "https://example/pr/77", "head_sha": "abc123", "base_sha": "def456", "evidence": "github-pr-view"},
        "checks": {"green": True},
        # #290 — a full test-fixture override asserts a genuinely-verified review-thread query
        # (unlike the live gh path, which must fail closed when it never queried threads).
        "reviews": {"approvals": 1, "open_threads": 0, "open_threads_verified": True},
        "branch": {"up_to_date": True}
    })
    synced = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                         "--external-repo", "wesleysimplicio/simplicio-loop", "--pr", "77"], REPO,
                  env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": fixture})
    assert synced.returncode == 0, synced.stdout + synced.stderr
    synced_payload = json.loads(synced.stdout)
    assert synced_payload["state"]["delivery"]["current_state"] == "merge-ready"
    assert synced_payload["state"]["delivery"]["ready"] is True
    assert synced_payload["state"]["phase"] == "delivering"
    receipt = json.loads((Path(payload["run_dir"]) / "delivery-receipt.json").read_text(encoding="utf-8"))
    assert receipt["source_payload"]["source_query"]["provider"] == "github"
    assert receipt["source_payload"]["source_query"]["repo"] == "wesleysimplicio/simplicio-loop"


def test_sync_source_requeries_github_fixture_for_release(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    fake_mapper_preflight = json.dumps({
        "version_stdout": "simplicio-mapper 0.19.0",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
        "version_returncode": 0,
        "help_returncode": 0
    })
    fake_devcli_preflight = json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
        "help_returncode": 0
    })
    started = _arm_result(
        repo, task, delivery="released", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
             "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
             "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    run_id = payload["manifest"]["run_id"]
    fixture = json.dumps({
        "release": {
            "tag": "v1.2.3",
            "assets": ["simplicio-loop.whl"],
            "checksums_verified": True,
            "signatures_verified": True,
            "sbom_present": True
        },
        "install_smoke": {"passed": True}
    })
    synced = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                         "--external-repo", "wesleysimplicio/simplicio-loop", "--tag", "v1.2.3"], REPO,
                  env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": fixture})
    assert synced.returncode == 0, synced.stdout + synced.stderr
    synced_payload = json.loads(synced.stdout)
    assert synced_payload["state"]["delivery"]["current_state"] == "released"
    assert synced_payload["state"]["delivery"]["ready"] is True


def test_sync_source_reopens_delivery_when_merge_ready_regresses(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    fake_mapper_preflight = json.dumps({
        "version_stdout": "simplicio-mapper 0.19.0",
        "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
        "version_returncode": 0,
        "help_returncode": 0
    })
    fake_devcli_preflight = json.dumps({
        "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
        "help_returncode": 0
    })
    started = _arm_result(
        repo, task, delivery="merge-ready", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator,
             "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": fake_mapper_preflight,
             "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": fake_devcli_preflight},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    run_id = json.loads(started.stdout)["manifest"]["run_id"]

    ready_fixture = json.dumps({
        "pr": {"url": "https://example/pr/77", "head_sha": "abc123", "base_sha": "def456", "evidence": "github-pr-view"},
        "checks": {"green": True},
        # #290 — asserts a genuinely-verified review-thread query for this fixture-driven test.
        "reviews": {"approvals": 1, "open_threads": 0, "open_threads_verified": True},
        "branch": {"up_to_date": True}
    })
    ready = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                        "--external-repo", "wesleysimplicio/simplicio-loop", "--pr", "77"], REPO,
                 env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": ready_fixture})
    assert ready.returncode == 0, ready.stdout + ready.stderr
    ready_payload = json.loads(ready.stdout)
    assert ready_payload["state"]["delivery"]["ready"] is True
    assert ready_payload["state"]["phase"] == "delivering"

    regressed_fixture = json.dumps({
        "pr": {"url": "https://example/pr/77", "head_sha": "abc123", "base_sha": "def456", "evidence": "github-pr-view"},
        "checks": {"green": False},
        "reviews": {"approvals": 1, "open_threads": 0},
        "branch": {"up_to_date": True}
    })
    regressed = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                            "--external-repo", "wesleysimplicio/simplicio-loop", "--pr", "77"], REPO,
                     env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": regressed_fixture})
    assert regressed.returncode == 0, regressed.stdout + regressed.stderr
    regressed_payload = json.loads(regressed.stdout)
    assert regressed_payload["state"]["delivery"]["ready"] is False
    assert regressed_payload["state"]["phase"] == "partial"
    assert "not green" in regressed_payload["state"]["blockers"][0].lower()


def test_run_blocks_when_mapper_preflight_version_too_old(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    started = _run(
        CLI + ["run", "--repo", str(repo), "--task", str(task), "--delivery", "verified",
               "--max-iterations", "9", "--quality-provider", "simplicio_loop_quality"],
        REPO,
        env={
            "SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON": json.dumps({
                "version_stdout": "simplicio-mapper 0.13.9",
                "help_stdout": "Usage: simplicio-mapper inspect handoff ask sync drift",
                "version_returncode": 0,
                "help_returncode": 0
            }),
            "SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON": json.dumps({
                "help_stdout": "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json",
                "help_returncode": 0
            })
        },
    )
    assert started.returncode == 20, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    assert payload["schema"] == "simplicio.loop-execution/v1"
    assert payload["status"] == "BLOCKED"
    assert payload["state"]["phase"] == "blocked"
    assert payload["verified"] is False


@pytest.mark.parametrize("missing_capability", ["--dry-run"])
def test_run_blocks_when_devcli_preflight_lacks_required_capability(
    tmp_path, monkeypatch, missing_capability,
):
    surface = (
        "Usage: simplicio-dev-cli edit --plan PLAN --apply --dry-run --json"
    ).replace(missing_capability, "")
    _, task = _setup_deterministic_preflight_fixture(
        monkeypatch,
        tmp_path,
        operator_preflight_surface=surface,
    )
    payload = runner_mod.arm_run(str(tmp_path / "repo"), str(task), "verified", 9)

    assert payload["state"]["phase"] == "blocked"
    assert "required capabilities" in payload["state"]["blockers"][0]
    receipt = json.loads(
        (Path(payload["run_dir"]) / "operator-preflight.json").read_text(encoding="utf-8")
    )
    assert receipt["missing_tokens"] == []
    assert receipt["missing_capabilities"] == [missing_capability]


def test_sync_source_infers_pr_open_when_merge_ready_target_is_not_yet_satisfied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    started = _arm_result(
        repo, task, delivery="merge-ready", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    run_id = payload["manifest"]["run_id"]
    fixture = json.dumps({
        "pr": {"url": "https://example/pr/77", "head_sha": "abc123", "base_sha": "def456", "evidence": "github-pr-view"},
        "checks": {"green": False},
        "reviews": {"approvals": 0, "open_threads": 2},
        "branch": {"up_to_date": False}
    })
    synced = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                         "--external-repo", "wesleysimplicio/simplicio-loop", "--pr", "77"], REPO,
                  env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": fixture})
    assert synced.returncode == 0, synced.stdout + synced.stderr
    synced_payload = json.loads(synced.stdout)
    assert synced_payload["state"]["delivery"]["current_state"] == "pr-open"
    assert synced_payload["state"]["delivery"]["ready"] is False
    assert synced_payload["state"]["phase"] == "partial"
    assert "merge-ready" in synced_payload["state"]["blockers"][0]


def test_sync_source_infers_merged_even_when_target_is_merge_ready(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    task = tmp_path / "task.md"
    task.write_text(TASK, encoding="utf-8")
    fake_operator = json.dumps({
        "execution_state": "dry_run",
        "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True},
        "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"]
    })
    started = _arm_result(
        repo, task, delivery="merge-ready", max_iterations=9,
        env={"SIMPLICIO_LOOP_FAKE_OPERATOR_JSON": fake_operator},
    )
    assert started.returncode == 0, started.stdout + started.stderr
    payload = json.loads(started.stdout)
    run_id = payload["manifest"]["run_id"]
    fixture = json.dumps({
        "pr": {"url": "https://example/pr/77", "head_sha": "abc123", "base_sha": "def456", "evidence": "github-pr-view"},
        "checks": {"green": True},
        "reviews": {"approvals": 1, "open_threads": 0},
        "branch": {"up_to_date": True},
        "merge": {
            "commit_sha": "deadbeef",
            "default_branch": "main",
            "merged_at": "2026-07-10T01:00:00Z",
            "commit_in_default_branch": True
        }
    })
    synced = _run(CLI + ["sync-source", "--repo", str(repo), run_id, "--source", "github",
                         "--external-repo", "wesleysimplicio/simplicio-loop", "--pr", "77"], REPO,
                  env={"SIMPLICIO_LOOP_GITHUB_FIXTURE_JSON": fixture})
    assert synced.returncode == 0, synced.stdout + synced.stderr
    synced_payload = json.loads(synced.stdout)
    assert synced_payload["state"]["delivery"]["current_state"] == "merged"
    assert synced_payload["state"]["delivery"]["ready"] is True


def test_maintenance_deferred_invalidates_ready_completion_receipt(tmp_path, monkeypatch):
    repo, run_id, run_dir = _start_run_for_maintenance_cli(tmp_path, monkeypatch)
    (run_dir / "completion-receipt.json").write_text(json.dumps({"ready": True, "verdict": "COMPLETE", "tag": "MEASURED"}), encoding="utf-8")

    result = runner_mod.defer_maintenance_backlog_only(
        str(repo), run_id, correction_summary="stale receipt",
        deferral_reason="maintenance window", resume_instructions=["resume later"],
    )

    persisted = json.loads((run_dir / "completion-receipt.json").read_text(encoding="utf-8"))
    assert persisted["ready"] is False
    assert persisted["verdict"] == "DELIVERY_PENDING"
    assert persisted["reason_code"] == "maintenance_deferred"
    assert result["state"]["completion"]["ready"] is False


def test_maintenance_deferred_rejects_terminal_run(tmp_path, monkeypatch):
    repo, run_id, _ = _start_run_for_maintenance_cli(tmp_path, monkeypatch)
    runner_mod.change_phase(str(repo), run_id, "done", "test terminal")

    with pytest.raises(ValueError, match="run already terminal"):
        runner_mod.defer_maintenance_backlog_only(
            str(repo), run_id, correction_summary="late",
            deferral_reason="maintenance", resume_instructions=["resume"],
        )


def test_maintenance_deferred_blocks_operator_and_batch(tmp_path, monkeypatch):
    repo, run_id, _ = _start_run_for_maintenance_cli(tmp_path, monkeypatch)
    runner_mod.defer_maintenance_backlog_only(
        str(repo), run_id, correction_summary="freeze",
        deferral_reason="maintenance", resume_instructions=["resume"],
    )

    with pytest.raises(RuntimeError, match="maintenance deferred"):
        runner_mod.execute_operator(str(repo), run_id)
    with pytest.raises(RuntimeError, match="maintenance deferred"):
        runner_mod.execute_operator_batch(str(repo), run_id)


def test_resume_clears_maintenance_backlog_only_transition(tmp_path, monkeypatch):
    repo, run_id, _ = _start_run_for_maintenance_cli(tmp_path, monkeypatch)
    runner_mod.defer_maintenance_backlog_only(
        str(repo), run_id, correction_summary="freeze",
        deferral_reason="maintenance", resume_instructions=["resume"],
    )

    resumed = _run(CLI + ["resume", "--repo", str(repo), run_id], REPO)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    payload = json.loads(resumed.stdout)

    assert payload["state"]["phase"] == "awaiting_decision"
    assert payload["state"]["maintenance"]["mode"] == "active"
    assert payload["state"]["maintenance"]["disposition"] == "operator"
    assert payload["state"]["operator"]["ready"] is False
    assert payload["state"]["operator"]["execution_state"] == "invalidated"
    assert payload["state"]["evidence"]["ready"] is False
    assert payload["state"]["evidence"]["status"] == "INVALIDATED"
    assert payload["state"]["next_action"] == "mapper_scan_required"


def _setup_deterministic_preflight_fixture(
    monkeypatch, tmp_path, *, targets=True, operator=None, task_text=TASK,
    operator_preflight_surface=None,
):
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
        cwd=repo,
        check=True,
    )
    task = tmp_path / "task.md"
    task.write_text(task_text, encoding="utf-8")
    fingerprint = {
        "head": "head-fixed",
        "tree_hash": "tree-fixed",
        "dirty_status_hash": "status-fixed",
    }
    patch_runner(monkeypatch, "_now", lambda: "2026-07-14T00:00:00Z")
    monkeypatch.setattr(runner_mod, "_run_id", lambda: "run-fixed")
    patch_runner(monkeypatch, "_rand_token", lambda size: "token-fixed")
    patch_runner(monkeypatch, "_repo_fingerprint", lambda path: dict(fingerprint))
    patch_runner(monkeypatch, "_changed_paths",
        lambda path: (
            ["src/app.py"]
            if (Path(path) / "src" / "app.py").read_text(encoding="utf-8")
            != "def main():\n    return 'ok'\n"
            else []
        ),
    )

    def fake_mapper(repo_path, run_root, **kwargs):
        runner_mod._write_json(run_root / "mapper-preflight.json", {
            "tool": "simplicio-mapper", "identity_ok": True, "version_ok": True,
            "missing_verbs": [], "repo_state": dict(fingerprint),
        })
        files = [{"path": "src/app.py", "tests": []}] if targets else []
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
                "context_pack": {"pack_hash": "pack-fixed", "files": files},
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

    patch_runner(monkeypatch, "_run_mapper", fake_mapper)
    if operator_preflight_surface is None:
        patch_runner(monkeypatch, "_preflight_operator", fake_operator_preflight)
    else:
        monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON", json.dumps({
            "help_stdout": operator_preflight_surface,
            "help_returncode": 0,
            "version_stdout": "simplicio-py 0.14.0",
            "version_returncode": 0,
        }))
    if not targets:
        patch_runner(monkeypatch, "_fallback_targets", lambda path: [])
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps(operator or {
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    return repo, task


def _arm_deterministic_preflight_fixture(monkeypatch, tmp_path, **kwargs):
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path, **kwargs)
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    return repo, task, armed, Path(armed["run_dir"])


def test_arm_run_blocks_when_plan_has_no_authorized_target(tmp_path, monkeypatch):
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path, targets=False)
    patch_runner(monkeypatch, "validate_plan", lambda *args, **kwargs: {
        "valid": True, "errors": [], "warnings": [],
    })
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    run_dir = Path(armed["run_dir"])

    assert armed["state"]["phase"] == "blocked"
    assert "no authorized operator target" in armed["state"]["history"][-1]["extra"]["error"]
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "plan.json").exists()
    assert not (run_dir / "operator-receipt.json").exists()


def test_arm_run_blocks_when_operator_dry_run_fails(tmp_path, monkeypatch):
    _, _, armed, run_dir = _arm_deterministic_preflight_fixture(
        monkeypatch, tmp_path,
        operator={"execution_state": "blocked", "returncode": 1,
                   "stdout": {}, "stderr": "dry run failed"},
    )

    assert armed["state"]["phase"] == "blocked"
    assert "dry run failed" in armed["state"]["history"][-1]["extra"]["error"]
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "operator-receipt.json").exists()


def test_execute_operator_batch_blocks_before_dispatch_when_receipt_missing_or_stale(tmp_path, monkeypatch):
    for case in ("missing", "stale"):
        case_dir = tmp_path / case
        repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, case_dir)
        operator_receipt = run_dir / "operator-receipt.json"
        if case == "missing":
            operator_receipt.unlink()
        else:
            payload = json.loads(operator_receipt.read_text(encoding="utf-8"))
            payload["plan_hash"] = "stale-plan"
            operator_receipt.write_text(json.dumps(payload), encoding="utf-8")
        dispatched = []
        monkeypatch.setattr(
            runner_mod, "dispatch_operator_batch",
            lambda *args, **kwargs: dispatched.append((args, kwargs)),
        )

        with pytest.raises(RuntimeError):
            runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

        diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
        assert diagnostic["schema"] == "simplicio.operator-batch-preflight/v1"
        assert diagnostic["status"] == "BLOCKED"
        assert json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["phase"] == "blocked"
        assert dispatched == []
        assert not (run_dir / "operator-batch.jsonl").exists()
        assert not list(run_dir.glob("*dead*letter*"))


def test_conduct_run_blocked_preflight_creates_no_batch_dead_letters(tmp_path, monkeypatch):
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path, targets=False)

    result = runner_mod.conduct_run(str(repo), str(task))
    run_dir = Path(result["run_dir"])

    assert result["state"]["phase"] == "blocked"
    assert not (run_dir / "operator-batch.jsonl").exists()
    assert not list(run_dir.glob("*dead*letter*"))


def test_conduct_run_fails_explicitly_blocked_when_batch_preflight_raises(tmp_path, monkeypatch):
    """Issue #279 regression: a fully armed run whose batch boundary rejects a stale or
    unbound receipt chain must surface as an explicit ``blocked`` result from `run` -- never
    as an uncaught exception that leaves the run in an undiagnosed, partially armed state.
    """
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path)

    def fail_batch(repo_arg, run_id, **kwargs):
        run_dir = Path(repo_arg) / ".simplicio-loop" / "loop-runs" / run_id
        state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        runner_mod._persist_batch_preflight_block(
            run_dir, state, Path(repo_arg), "stale operator receipt: repository changed",
        )
        raise RuntimeError("stale operator receipt: repository changed")

    monkeypatch.setattr(runner_mod, "execute_operator_batch", fail_batch)

    result = runner_mod.conduct_run(str(repo), str(task))
    run_dir = Path(result["run_dir"])

    assert result["state"]["phase"] == "blocked"
    assert "stale operator receipt" in json.dumps(result["state"]["history"][-1])
    assert (run_dir / "operator-batch-preflight.json").exists()
    assert not (run_dir / "operator-batch.jsonl").exists()
    assert not list(run_dir.glob("*dead*letter*"))


def test_conduct_run_force_blocks_when_batch_boundary_raises_without_diagnostic(tmp_path, monkeypatch):
    """Defensive fallback: even if the batch boundary somehow raises without persisting its
    own blocked diagnostic, `run` must still surface an explicit blocked result rather than
    propagating the exception or leaving the run's phase ambiguous.
    """
    repo, task = _setup_deterministic_preflight_fixture(monkeypatch, tmp_path)

    def fail_batch_no_diagnostic(repo_arg, run_id, **kwargs):
        raise RuntimeError("unexpected batch boundary failure")

    monkeypatch.setattr(runner_mod, "execute_operator_batch", fail_batch_no_diagnostic)

    result = runner_mod.conduct_run(str(repo), str(task))

    assert result["state"]["phase"] == "blocked"
    assert "unexpected batch boundary failure" in json.dumps(result["state"]["history"][-1])


def test_execute_operator_batch_accepts_fresh_run_receipt_chain(tmp_path, monkeypatch):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    stage_valid_planning_receipt(repo=repo, run_dir=run_dir, armed_payload=armed,
                                 run_id=armed["manifest"]["run_id"])
    dispatched = []

    def fake_dispatch(items, **kwargs):
        dispatched.extend(list(items))
        return {"failed_task_indices": [], "dead_letter_task_indices": []}

    monkeypatch.setattr(runner_mod, "dispatch_operator_batch", fake_dispatch)
    result = runner_mod.execute_operator_batch(
        str(repo), armed["manifest"]["run_id"], max_workers=1,
        isolated_contexts={1: {"isolation": "shared"}}, auto_fan_out=False,
    )

    assert result["failed_task_indices"] == []
    assert len(dispatched) == 1
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "mapper-context.json").exists()
    assert (run_dir / "operator-preflight.json").exists()
    assert (run_dir / "operator-receipt.json").exists()
    operator_preflight = json.loads(
        (run_dir / "operator-preflight.json").read_text(encoding="utf-8")
    )
    assert operator_preflight["required_tokens"] == list(runner_mod.DEVCLI_REQUIRED_TOKENS)
    assert operator_preflight["required_capabilities"] == list(runner_mod.DEVCLI_REQUIRED_CAPABILITIES)
    assert operator_preflight["missing_tokens"] == []
    assert operator_preflight["missing_capabilities"] == []


@pytest.mark.parametrize(
    ("receipt_name", "field", "value", "message"),
    [
        ("mapper-context.json", "run_id", "run-other", "not bound to the current run"),
        ("plan.json", "run_id", "run-other", "not bound to the current run"),
        ("plan.json", "mapper_context_hash", "", "no mapper context hash"),
        ("operator-receipt.json", "run_id", "run-other", "not bound to the current run"),
        ("operator-receipt.json", "mapper_context_hash", "tampered", "mapper receipt"),
        ("operator-receipt.json", "returncode", 1, "successful dry-run"),
        ("operator-receipt.json", "target", "../outside.py", "authorized repository"),
    ],
)
def test_batch_rejects_cross_run_and_tampered_receipt_bindings(
    tmp_path, monkeypatch, receipt_name, field, value, message,
):
    case_dir = tmp_path / (receipt_name.replace(".json", "") + "-" + field)
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, case_dir)
    receipt_path = run_dir / receipt_name
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload[field] = value
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"
    assert diagnostic["blocker"]["reason_code"] == "operator_batch_preflight_failed"
    assert not (run_dir / "operator-batch.jsonl").exists()
    assert not list(run_dir.glob("*dead*letter*"))


def test_batch_preflight_failure_is_typed_deterministic_no_wasted_retries(tmp_path, monkeypatch):
    """#NOWASTE: a batch-wide receipt-chain rejection ("operator receipt does
    not match the mapper receipt") is the exact same failure on every
    immediate re-invocation -- it must raise a typed, deterministic
    reason_code a retrying caller (e.g. an outer re-feed loop) can recognize,
    not a bare RuntimeError indistinguishable from a transient one.
    """
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    receipt_path = run_dir / "operator-receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["mapper_context_hash"] = "tampered"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(runner_mod.BatchPreflightError) as excinfo:
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    assert excinfo.value.reason_code == "operator_batch_preflight_failed"
    assert "mapper receipt" in str(excinfo.value)
    assert (
        runner_mod._classify_operator_exception_reason_code(excinfo.value)
        == "operator_batch_preflight_failed"
    )
    assert "operator_batch_preflight_failed" in runner_mod.DETERMINISTIC_OPERATOR_REASON_CODES


def test_batch_rejects_mapper_context_byte_tamper(tmp_path, monkeypatch):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    mapper_path = run_dir / "mapper-context.json"
    mapper = json.loads(mapper_path.read_text(encoding="utf-8"))
    mapper["generated_at"] = "2026-07-14T00:00:01Z"
    mapper_path.write_text(json.dumps(mapper), encoding="utf-8")

    with pytest.raises(RuntimeError, match="current mapper context bytes"):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"
    assert not (run_dir / "operator-batch.jsonl").exists()


@pytest.mark.parametrize("missing_capability", ["--dry-run"])
def test_batch_rejects_operator_preflight_missing_capability(
    tmp_path, monkeypatch, missing_capability,
):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    preflight_path = run_dir / "operator-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["help_stdout"] = preflight["help_stdout"].replace(missing_capability, "")
    preflight["task_help_stdout"] = preflight["task_help_stdout"].replace(missing_capability, "")
    preflight["missing_capabilities"] = [missing_capability]
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required capabilities"):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"
    assert not (run_dir / "operator-batch.jsonl").exists()


@pytest.mark.parametrize(
    "missing_field",
    [
        "required_tokens", "missing_tokens", "required_capabilities", "missing_capabilities",
        "help_stdout", "task_help_stdout", "__all__",
    ],
)
def test_batch_rejects_operator_preflight_missing_contract_field(
    tmp_path, monkeypatch, missing_field,
):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    preflight_path = run_dir / "operator-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    fields = (
        "required_tokens", "missing_tokens", "required_capabilities", "missing_capabilities",
        "help_stdout", "task_help_stdout",
    )
    for field in fields if missing_field == "__all__" else (missing_field,):
        preflight.pop(field)
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required field"):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"
    assert not (run_dir / "operator-batch.jsonl").exists()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("required_tokens", "not-a-list"),
        ("missing_tokens", None),
        ("required_capabilities", {}),
        ("missing_capabilities", [1]),
        ("help_stdout", []),
        ("task_help_stdout", None),
    ],
)
def test_batch_rejects_operator_preflight_invalid_contract_field_type(
    tmp_path, monkeypatch, field, invalid_value,
):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    preflight_path = run_dir / "operator-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight[field] = invalid_value
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid field type"):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"


@pytest.mark.parametrize(
    ("missing_surface", "message"),
    [
        ("--json", "missing_tokens do not match persisted help"),
        ("--dry-run", "missing_capabilities do not match persisted help"),
    ],
)
def test_batch_rejects_forged_empty_capability_gaps_against_deficient_help(
    tmp_path, monkeypatch, missing_surface, message,
):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    preflight_path = run_dir / "operator-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["help_stdout"] = preflight["help_stdout"].replace(missing_surface, "")
    preflight["task_help_stdout"] = preflight["task_help_stdout"].replace(missing_surface, "")
    preflight["missing_tokens"] = []
    preflight["missing_capabilities"] = []
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"


@pytest.mark.parametrize("field", ["required_tokens", "required_capabilities"])
def test_batch_rejects_altered_operator_preflight_required_contract(
    tmp_path, monkeypatch, field,
):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    preflight_path = run_dir / "operator-preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight[field] = [*preflight[field], "--forged-capability"]
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(RuntimeError, match="canonical contract"):
        runner_mod.execute_operator_batch(str(repo), armed["manifest"]["run_id"])

    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "BLOCKED"
    assert diagnostic["blocker"]["scope"] == "global"


def test_direct_dispatch_cannot_bypass_run_global_preflight(tmp_path, monkeypatch):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    operator_path = run_dir / "operator-receipt.json"
    operator = json.loads(operator_path.read_text(encoding="utf-8"))
    operator["plan_hash"] = "tampered"
    operator_path.write_text(json.dumps(operator), encoding="utf-8")
    prepared = []
    monkeypatch.setattr(
        runner_mod, "_prepare_worktree_contexts",
        lambda *args, **kwargs: prepared.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="current plan"):
        runner_mod.dispatch_operator_batch(
            [{"repo": str(repo), "run_id": armed["manifest"]["run_id"], "task_index": 1}],
            journal_dir=str(run_dir),
        )

    assert prepared == []
    diagnostic = json.loads((run_dir / "operator-batch-preflight.json").read_text(encoding="utf-8"))
    assert diagnostic["blocker"]["scope"] == "global"
    assert json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["phase"] == "blocked"
    assert not (run_dir / "operator-batch.jsonl").exists()
    assert not list(run_dir.glob("*dead*letter*"))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_runner_cli")


def test_run_mapper_recovers_with_goal_and_target_when_task_pack_is_too_broad(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    task = tmp_path / "task.md"
    task.write_text("Cenário 1: alvo\nAcesso: src/app.py\n", encoding="utf-8")
    calls = []

    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {"task_aware_supported": True})
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        if argv[1] == "handoff":
            if "--task-file" in argv:
                payload = {
                    "ready": False,
                    "context_pack": {"needs_broader_context": True, "fidelity": {"gate": "needs_broader_context"}},
                }
            else:
                payload = {
                    "ready": True,
                    "context_pack": {"needs_broader_context": False, "fidelity": {"gate": "ready"}, "files": [{"path": "src/app.py"}]},
                }
        else:
            payload = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(
        repo, run_root, task_path=str(task), goal="app target",
        task_fingerprint="a" * 64, target_hint="src/app.py",
    )

    handoffs = [argv for argv in calls if argv[1] == "handoff"]
    assert len(handoffs) == 2
    assert "--task-file" in handoffs[0]
    assert "--task-file" not in handoffs[1]
    assert result["handoff_recovery"]["strategy"] == "goal-target-without-task-file"
    assert result["handoff"]["stdout"]["ready"] is True


def test_run_mapper_recovers_when_estimated_tokens_exceed_budget(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    task = tmp_path / "task.md"
    task.write_text("Cenário 1: alvo\nAcesso: src/app.py\n", encoding="utf-8")
    calls = []
    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_TOKEN_BUDGET", "8000")
    patch_runner(monkeypatch, "_preflight_mapper", lambda *args: {"task_aware_supported": True})
    patch_runner(monkeypatch, "_validate_mapper_receipt", lambda *args: None)

    def fake_run(argv, cwd):
        calls.append(list(argv))
        if argv[1] == "handoff":
            if "--task-file" in argv:
                payload = {"ready": False, "context_pack": {"estimated_tokens": 8905}}
            else:
                payload = {"ready": True, "context_pack": {"estimated_tokens": 8905, "files": [{"path": "src/app.py"}]}}
        else:
            payload = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    patch_runner(monkeypatch, "_run_cmd", fake_run)
    result = runner_mod._run_mapper(
        repo, run_root, task_path=str(task), goal="app target",
        task_fingerprint="a" * 64, target_hint="src/app.py",
    )
    handoffs = [argv for argv in calls if argv[1] == "handoff"]
    assert len(handoffs) == 2
    assert "--task-file" in handoffs[0]
    assert "--task-file" not in handoffs[1]
    assert handoffs[1][handoffs[1].index("--token-budget") + 1] == "8905"
    assert result["handoff_recovery"]["strategy"] == "goal-target-without-task-file"


def test_operator_dry_run_receipt_marks_ephemeral_identity(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "worker.py").write_text("pass\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    handle = "sha256:" + "a" * 64
    (run_root / "mapper-context.json").write_text(json.dumps({
        "handoff": {"stdout": {
            "context_snapshot": {"schema": "simplicio.context-snapshot/v1", "snapshot_id": "snap-1"},
            "context_pack": {"schema": "simplicio.context-pack/v1", "pack_hash": "pack-1"},
            "execution_context": {"schema": "simplicio.execution-context/v1", "snapshot_id": "snap-1"},
            "context_handle": handle,
        }}
    }), encoding="utf-8")
    task = runner_mod.compile_many(TASK)["tasks"][0]
    captured = {}

    patch_runner(monkeypatch, "_preflight_operator", lambda *args: {})
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", raising=False)

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)
    receipt = runner_mod._prepare_operator_receipt(repo, run_root, task, "src/worker.py")

    assert receipt["context_handoff"]["purpose"] == "read_only_preflight"
    # The read-only dry run only probes the plan surface; no lease identity is sent.
    assert receipt["argv"][-2:] == ["edit", "--help"]
    assert "--attempt-id" not in receipt["argv"]
