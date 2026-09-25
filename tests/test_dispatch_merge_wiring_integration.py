"""Real end-to-end coverage for issue #288's "biggest remaining gap": prove
``AttemptCoordinator.run_guarded`` and ``MergeExecutor`` are actually wired into the real
dispatch path in ``simplicio_loop/runner.py`` -- not merely available as tested, standalone
primitives.

Chain proven here, in-process and deterministic (no real network, no real dev-cli/gh
binaries, no sleeping on wall-clock timeouts): claim (``AttemptCoordinator.claim`` via a real
``SQLiteRemoteQueue``) -> worktree (a ``worktree_context`` with a real branch name) ->
simulated runtime work (``SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON``, the existing fake-operator
hook, executed through ``AttemptCoordinator.run_guarded`` because
``SIMPLICIO_GUARDED_DISPATCH=1``) -> receipt verify (``_verify_worker_receipt_pair`` against
the real receipts ``execute_operator`` writes) -> ``MergeExecutor`` creates+merges a PR against
a scripted ``gh`` runner (a real PR against this repo would be too heavy for a single test;
the executor itself already has a live e2e in ``tests/test_merge_executor_live_e2e.py``) ->
``reconcile()`` confirms the merge before this dispatch attempt reports success.

Both new behaviors are opt-in (``SIMPLICIO_GUARDED_DISPATCH`` / ``SIMPLICIO_AUTO_MERGE_PR``),
mirroring the ``SIMPLICIO_REQUIRE_MUTATION_AUTHORITY`` pattern from #284's
``planning_gate.py`` wiring, so existing callers that never set them see no behavior change --
covered by the last test in this file.
"""
import json
import subprocess

from simplicio_loop import runner as runner_mod
from simplicio_loop.agent_contract import build_context_pack
from simplicio_loop.remote_queue import SQLiteRemoteQueue

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

IDENTITY = {
    "agent_id": "codex@device-a", "runtime": "codex", "device_id": "device-a",
    "session_id": "session-e2e", "capabilities": ["claim", "heartbeat", "fencing", "receipts", "events"],
}


class ScriptedGhRunner:
    """Replays canned ``gh`` responses -- the same fake shape used by
    ``tests/test_merge_executor.py`` -- so ``MergeExecutor`` runs for real against a
    deterministic, offline double instead of a live GitHub API."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if not self._responses:
            raise AssertionError("ScriptedGhRunner ran out of scripted responses for %r" % argv)
        returncode, stdout, stderr = self._responses.pop(0)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _pr_view_json(**fields):
    return json.dumps(fields)


def _write_host_edit_plan(repo, run_id, task_index=1):
    """Loop does not generate an edit plan -- the host must write one (see SKILL.md's
    per-task ``edit-plan-<N>.json`` protocol). A tagged schema skips the real dev-cli
    compile step (``_compile_minimal_host_plan`` passes a schema-tagged plan through
    unchanged), so this fixture needs no real dev-cli binary; the actual mutation in
    these tests comes from the faked ``run_guarded``/exec seam, not from this plan's
    content."""
    run_dir = repo / ".simplicio" / "loop-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"edit-plan-{task_index}.json").write_text(json.dumps({
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["src/app.py"],
        "operations": [{"path": "src/app.py", "find": "return 'ok'", "replace": "return 'ok-merged'"}],
    }), encoding="utf-8")


def _built_context_pack(task_id, goal, acs):
    """A real, conforming context pack (schema, assigned_to, capabilities all consistent
    with IDENTITY) -- ``bind_receipt`` rejects a raw ad-hoc dict here, so the item's
    ``context_pack`` field must be built the same way production code builds it."""
    return build_context_pack(task_id=task_id, goal=goal, identity=IDENTITY, acs=acs)


def _arm_fixture(tmp_path, monkeypatch):
    from tests._contract_only_hookwall import ContractOnlyHookwallLedger

    monkeypatch.setattr(
        runner_mod,
        "_hookwall_ledger",
        lambda *_args, **_kwargs: ContractOnlyHookwallLedger(),
    )
    """Arm one deterministic run without any real mapper/dev-cli/network calls (mirrors the
    harness in ``tests/test_runner_state_machine_unit.py``)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".simplicio/\n", encoding="utf-8")
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
                      if (repo / "src" / "app.py").read_text(encoding="utf-8")
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
    # #284's mutation-authority gate is mandatory-by-default in execute_operator(); this
    # file is testing #288's guarded-dispatch/merge wiring, not #284's gate (already covered
    # by tests/test_planning_gate_execute_operator_integration.py), so opt out explicitly.
    monkeypatch.setenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "0")
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps({
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    assert armed["state"]["phase"] == "awaiting_decision", armed["state"]
    return repo, armed["manifest"]["run_id"]


def _simulate_runtime_work_via_env_override(monkeypatch):
    """The ``execute`` tick's dev-cli invocation, faked deterministically through the
    existing ``SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON`` hook -- this bypasses both
    ``subprocess.run`` and ``run_guarded`` (it short-circuits before either), so it is only
    appropriate for the *unguarded* path where the real subprocess call is not itself under
    test."""
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", json.dumps({
        "returncode": 0,
        "stdout": {"kind": "operator-result", "ok": True},
        "stderr": "",
        "write_files": {"src/app.py": "def main():\n    return 'ok-merged'\n"},
    }))


def _simulate_runtime_work_via_run_guarded(monkeypatch, repo):
    """Simulate real runtime work happening *through* ``AttemptCoordinator.run_guarded``
    itself (not the env-override bypass): writes the file the fixture's changed-paths fake
    looks for and returns a real ``subprocess.CompletedProcess`` with valid dev-cli-shaped
    JSON stdout, proving the guarded path is what actually produced the mutation."""
    from simplicio_loop.work_item_claims import AttemptCoordinator

    def guarded_write(self, attempt, argv, **kwargs):
        self.assert_active(attempt)
        (repo / "src" / "app.py").write_text("def main():\n    return 'ok-merged'\n", encoding="utf-8")
        stdout = json.dumps({"kind": "operator-result", "ok": True})
        return subprocess.CompletedProcess(list(argv), 0, stdout, "")

    monkeypatch.setattr(AttemptCoordinator, "run_guarded", guarded_write)


def test_guarded_dispatch_and_auto_merge_are_wired_end_to_end(tmp_path, monkeypatch):
    """The full chain, both opt-in flags on: claim goes through AttemptCoordinator (not a
    bare queue.claim), the dev-cli mutation runs through run_guarded, the receipt pair comes
    back VERIFIED, and MergeExecutor actually creates+polls+merges+reconciles a PR."""
    repo, run_id = _arm_fixture(tmp_path, monkeypatch)
    _write_host_edit_plan(repo, run_id)
    _simulate_runtime_work_via_run_guarded(monkeypatch, repo)

    monkeypatch.setenv("SIMPLICIO_GUARDED_DISPATCH", "1")
    monkeypatch.setenv("SIMPLICIO_AUTO_MERGE_PR", "1")
    monkeypatch.setenv("SIMPLICIO_REMOTE_REPO", "acme/widgets")
    monkeypatch.setenv("SIMPLICIO_MERGE_BASE", "main")

    ghrunner = ScriptedGhRunner([
        (0, "[]", ""),  # pr list --head <branch> -> none exists yet
        (0, "https://github.com/acme/widgets/pull/99\n", ""),  # pr create
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),  # poll
        (0, "", ""),  # pr merge
        (0, _pr_view_json(state="MERGED", mergeCommit={"oid": "deadbeef"}, baseRefName="main"), ""),  # reconcile
        (0, "[]", ""),  # post-merge open-PR reconciliation finds no survivor
    ])

    real_merge_executor = runner_mod.MergeExecutor

    def fake_merge_executor(*, repo, runner=None, timeout=30):
        # Real MergeExecutor, real create/poll/merge/reconcile logic -- only the `gh`
        # transport itself is swapped for the deterministic scripted double.
        return real_merge_executor(repo=repo, runner=ghrunner, timeout=timeout)

    monkeypatch.setattr(runner_mod, "MergeExecutor", fake_merge_executor)

    queue = SQLiteRemoteQueue(str(tmp_path / "queue.db"))
    item = {
        "repo": str(repo), "run_id": run_id, "task_index": 1, "worker_id": IDENTITY["agent_id"],
        "task_id": "task-e2e-1",
        "distributed_queue": queue,
        "agent_identity": IDENTITY,
        "context_pack": _built_context_pack("task-e2e-1", "converge PLANES ordering", ["RN01"]),
        "worktree_context": {"mode": "worktree", "path": str(repo), "branch": "feat/e2e-merge"},
    }

    record = runner_mod._operator_dispatch_attempt(item)

    # --- claim went through the guarded AttemptCoordinator path, not a bare queue.claim ---
    assert record["guarded_dispatch"] is True
    assert isinstance(record["lease"]["fencing_token"], str)

    # --- simulated runtime work actually ran and produced a genuinely VERIFIED receipt pair ---
    assert record["status"] == "succeeded", json.dumps(record, sort_keys=True)
    assert record["execution_state"] == "applied"
    assert record["receipt_status"] == "VERIFIED", record.get("receipt_verdict_reason")

    # --- MergeExecutor created, polled, merged, and reconciled the PR for real ---
    merge = record["merge"]
    assert merge["attempted"] is True
    assert merge["pr"]["number"] == 99
    assert merge["merged"] is True
    assert merge["reconciled"] is True
    assert merge["merge_commit_sha"] == "deadbeef"
    assert merge["base_ref"] == "main"

    # The scripted `gh` transport actually ran the full sequence -- proves this is the real
    # MergeExecutor.merge()/reconcile() call path, not a stub returning canned success.
    kinds = [call[1] if len(call) > 1 else "" for call in ghrunner.calls]
    assert kinds == ["pr", "pr", "pr", "pr", "pr", "pr"]
    assert any("create" in call for call in ghrunner.calls)
    assert any("merge" in call for call in ghrunner.calls if "view" not in call)


def test_lease_lost_during_guarded_execution_is_reported_distinctly(tmp_path, monkeypatch):
    """A worker whose lease is stolen mid-mutation must be killed and reported as
    ``lease_lost_during_execution`` -- not left to finish unguarded, and not confused with a
    generic operator exception."""
    repo, run_id = _arm_fixture(tmp_path, monkeypatch)
    _write_host_edit_plan(repo, run_id)
    monkeypatch.setenv("SIMPLICIO_GUARDED_DISPATCH", "1")

    queue = SQLiteRemoteQueue(str(tmp_path / "queue.db"))
    item = {
        "repo": str(repo), "run_id": run_id, "task_index": 1, "worker_id": IDENTITY["agent_id"],
        "task_id": "task-e2e-2",
        "distributed_queue": queue,
        "agent_identity": IDENTITY,
        "context_pack": _built_context_pack("task-e2e-2", "converge PLANES ordering", ["RN01"]),
    }

    from simplicio_loop.work_item_claims import AttemptCoordinator, LeaseLostDuringExecution

    def stolen_run_guarded(self, attempt, argv, **kwargs):
        # Simulate another worker winning the fence the instant before the guard's
        # pre-flight check -- deterministic, no thread races, no real subprocess launched.
        self.queue.release(attempt.lease, reason="handoff")
        other = dict(IDENTITY, agent_id="claude@device-b", runtime="claude", device_id="device-b",
                     session_id="session-b")
        AttemptCoordinator(self.queue, run_id=self.run_id).claim(
            work_item_id=attempt.work_item_id,
            identity=other,
            goal="converge PLANES ordering",
            acs=["RN01"],
        )
        raise LeaseLostDuringExecution(attempt.work_item_id, attempt.attempt_id,
                                       RuntimeError("fence lost"))

    monkeypatch.setattr(AttemptCoordinator, "run_guarded", stolen_run_guarded)

    record = runner_mod._operator_dispatch_attempt(item)

    assert record["status"] == "failed"
    assert record["reason_code"] == "lease_lost_during_execution"
    assert record["dead_letter"] is True
    assert record["receipt_status"] == "UNVERIFIED"


def test_unguarded_dispatch_is_unchanged_when_opt_ins_are_off(tmp_path, monkeypatch):
    """Backward compatibility: with neither env var set, dispatch behaves exactly as before
    -- a bare queue.claim, a plain subprocess.run, and no merge attempt at all."""
    repo, run_id = _arm_fixture(tmp_path, monkeypatch)
    _simulate_runtime_work_via_env_override(monkeypatch)
    monkeypatch.delenv("SIMPLICIO_GUARDED_DISPATCH", raising=False)
    monkeypatch.delenv("SIMPLICIO_AUTO_MERGE_PR", raising=False)

    queue = SQLiteRemoteQueue(str(tmp_path / "queue.db"))
    # The raw (unguarded) claim path never enqueues on the caller's behalf -- unlike
    # AttemptCoordinator.claim, which does this automatically -- so the task must already be
    # registered, exactly as a real distributed-queue caller would do upstream.
    queue.enqueue("task-legacy-1", {"run_id": run_id, "goal": "legacy dispatch"})
    item = {
        "repo": str(repo), "run_id": run_id, "task_index": 1, "worker_id": IDENTITY["agent_id"],
        "task_id": "task-legacy-1",
        "distributed_queue": queue,
        "agent_identity": IDENTITY,
    }

    record = runner_mod._operator_dispatch_attempt(item)

    assert record["status"] == "succeeded", json.dumps(record, sort_keys=True)
    assert record["receipt_status"] == "VERIFIED"
    assert record.get("guarded_dispatch") is False
    assert record["merge"] is None


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_dispatch_merge_wiring")
