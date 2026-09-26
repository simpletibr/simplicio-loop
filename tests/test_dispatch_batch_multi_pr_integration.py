"""Multi-PR fan-in coverage for issue #288's remaining "dispatch_operator_batch()-level"
gap: PR #364 wired ``AttemptCoordinator.run_guarded`` + ``MergeExecutor`` into a *single*
dispatch attempt (``_operator_dispatch_attempt`` / ``tests/test_dispatch_merge_wiring.py``).
This file proves the same chain holds when ``dispatch_operator_batch`` fans out N
independent, already-claimed tasks concurrently: each gets its own guarded dispatch, its own
VERIFIED receipt pair, and its own merged PR -- with no cross-contamination between lanes
(no lane observing another lane's branch, PR number, or receipt).

Real ``SQLiteRemoteQueue`` (file-backed, shared across all lanes -- the same "one queue,
many independent claims" shape a real batch would use), real ``AttemptCoordinator.claim``,
real ``execute_operator``/receipt persistence, real ``MergeExecutor.ensure_pr/merge/reconcile``
logic -- only the `gh` transport is swapped for a deterministic, thread-safe, branch/PR-routed
double (no live network, no live dev-cli).
"""
import json
import subprocess
import threading
from collections import deque

from simplicio_loop import runner as runner_mod
from simplicio_loop.agent_contract import build_context_pack
from simplicio_loop.remote_queue import SQLiteRemoteQueue
from simplicio_loop.work_item_claims import AttemptCoordinator

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


def _identity(n):
    return {
        "agent_id": f"codex@device-{n}", "runtime": "codex", "device_id": f"device-{n}",
        "session_id": f"session-e2e-{n}",
        "capabilities": ["claim", "heartbeat", "fencing", "receipts", "events"],
    }


def _built_context_pack(task_id, goal, acs, identity):
    return build_context_pack(task_id=task_id, goal=goal, identity=identity, acs=acs)


def _write_host_edit_plan(repo, run_id, task_index=1):
    """Loop does not generate an edit plan -- the host must write one (see SKILL.md's
    per-task ``edit-plan-<N>.json`` protocol). A tagged schema skips the real dev-cli
    compile step, so this fixture needs no real dev-cli binary; the actual mutation in
    this test comes from the faked ``run_guarded``, not from this plan's content."""
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"edit-plan-{task_index}.json").write_text(json.dumps({
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["src/app.py"],
        "operations": [{"path": "src/app.py", "find": "return 'ok'", "replace": "return 'ok-merged'"}],
    }), encoding="utf-8")


def _arm_fixture(tmp_path, monkeypatch, name):
    from tests._contract_only_hookwall import ContractOnlyHookwallLedger

    monkeypatch.setattr(
        runner_mod,
        "_hookwall_ledger",
        lambda *_args, **_kwargs: ContractOnlyHookwallLedger(),
    )
    """Arm one deterministic run in its own repo (mirrors
    ``tests/test_dispatch_merge_wiring.py``'s fixture, but callable N times so each lane gets
    an independent repo/run_id -- the fan-in path's realistic shape)."""
    repo = tmp_path / f"repo-{name}"
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
    task = tmp_path / f"task-{name}.md"
    task.write_text(TASK, encoding="utf-8")

    fingerprint = {"head": "head-fixed", "tree_hash": "tree-fixed", "dirty_status_hash": "status-fixed"}
    # These mocks are deliberately generic over ``path`` -- called once per lane's own repo,
    # they must not close over a single fixed repo.
    monkeypatch.setattr(runner_mod, "_repo_fingerprint", lambda path: dict(fingerprint))
    monkeypatch.setattr(
        runner_mod, "_changed_paths",
        lambda path: (["src/app.py"]
                      if (path / "src" / "app.py").read_text(encoding="utf-8")
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
    monkeypatch.setenv("SIMPLICIO_REQUIRE_MUTATION_AUTHORITY", "0")
    monkeypatch.setenv("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", json.dumps({
        "execution_state": "dry_run", "returncode": 0,
        "stdout": {"kind": "operator-proposal", "ok": True}, "stderr": "",
        "argv": ["simplicio-dev-cli", "task", "demo"],
    }))
    armed = runner_mod.arm_run(str(repo), str(task), "verified", 12)
    assert armed["state"]["phase"] == "awaiting_decision", armed["state"]
    return repo, armed["manifest"]["run_id"]


class MultiScriptedGhRunner:
    """A thread-safe, per-lane routed double for the ``gh`` CLI.

    Unlike ``tests/test_dispatch_merge_wiring.py``'s single-lane ``ScriptedGhRunner`` (one
    flat response queue), this routes by the branch present in ``pr list``/``pr create``
    (``--head <branch>``) and by the PR number present in ``pr view``/``pr merge`` -- so N
    lanes running concurrently in the batch's thread pool each only ever see *their own*
    scripted responses, proving no lane's merge steps leak into another's.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_branch = {}
        self._by_number = {}
        self.calls = []

    def register(self, *, branch, pr_number, list_resp, create_resp, poll_resp, merge_resp, reconcile_resp):
        self._by_branch[branch] = deque([list_resp, create_resp])
        self._by_number[pr_number] = deque([poll_resp, merge_resp, reconcile_resp])

    def __call__(self, argv, **kwargs):
        with self._lock:
            self.calls.append(list(argv))
        # MergeExecutor performs a read-only post-merge patrol of the remaining open PRs.
        # This typed fake must implement that current surface too; omitting it makes a
        # successful queue task fail only after completion and every retry correctly sees
        # ``task already completed``.
        if "--state" in argv and argv[argv.index("--state") + 1] == "open" and "--head" not in argv:
            return subprocess.CompletedProcess(argv, 0, "[]", "")
        if "--head" in argv:
            branch = argv[argv.index("--head") + 1]
            queue = self._by_branch[branch]
        else:
            # ``pr view <number> ...`` / ``pr merge <number> ...`` -- find the numeric PR-id
            # token rather than assuming a fixed index (argv may or may not be prefixed with
            # the ``gh`` binary name itself, depending on the caller).
            number = next(int(tok) for tok in argv if tok.isdigit())
            queue = self._by_number[number]
        if not queue:
            raise AssertionError("MultiScriptedGhRunner ran out of scripted responses for %r" % argv)
        returncode, stdout, stderr = queue.popleft()
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _pr_view_json(**fields):
    return json.dumps(fields)


def test_multi_pr_fan_in_batch_dispatch_independent_receipts_and_merges(tmp_path, monkeypatch):
    """N independent claimed tasks, dispatched concurrently through
    ``dispatch_operator_batch``, each produce their own verified receipt and their own merged
    PR -- and no lane observes another lane's branch/PR/receipt."""
    monkeypatch.setenv("SIMPLICIO_GUARDED_DISPATCH", "1")
    monkeypatch.setenv("SIMPLICIO_AUTO_MERGE_PR", "1")
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    monkeypatch.setenv("SIMPLICIO_REMOTE_REPO", "acme/widgets")
    monkeypatch.setenv("SIMPLICIO_MERGE_BASE", "main")

    lane_count = 3
    ghrunner = MultiScriptedGhRunner()
    queue = SQLiteRemoteQueue(str(tmp_path / "queue.db"))
    items = []
    expected = {}
    for lane in range(lane_count):
        repo, run_id = _arm_fixture(tmp_path, monkeypatch, lane)
        _write_host_edit_plan(repo, run_id)
        identity = _identity(lane)
        branch = f"feat/e2e-merge-{lane}"
        pr_number = 900 + lane
        task_id = f"task-e2e-batch-{lane}"
        ghrunner.register(
            branch=branch, pr_number=pr_number,
            list_resp=(0, "[]", ""),
            create_resp=(0, f"https://github.com/acme/widgets/pull/{pr_number}\n", ""),
            poll_resp=(0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
            merge_resp=(0, "", ""),
            reconcile_resp=(0, _pr_view_json(
                state="MERGED", mergeCommit={"oid": f"sha-{lane}"}, baseRefName="main",
            ), ""),
        )
        items.append({
            "repo": str(repo), "run_id": run_id, "task_index": 1,
            "worker_id": identity["agent_id"], "task_id": task_id,
            "distributed_queue": queue,
            "agent_identity": identity,
            "context_pack": _built_context_pack(task_id, f"converge PLANES ordering lane {lane}", ["RN01"], identity),
            # Distinct paths -> distinct isolation_key -> allowed to run concurrently.
            "worktree_context": {"mode": "worktree", "path": str(repo), "branch": branch},
            "isolation_key": str(repo),
        })
        expected[task_id] = {"repo": str(repo), "run_id": run_id, "branch": branch, "pr_number": pr_number,
                             "sha": f"sha-{lane}"}

    def guarded_write(self, attempt, argv, **kwargs):
        # Generic over ``cwd`` (each lane's own repo) -- proves the mutation actually landed
        # in *this* lane's checkout, not a fixture shared across lanes.
        self.assert_active(attempt)
        from pathlib import Path as _P
        (_P(kwargs["cwd"]) / "src" / "app.py").write_text("def main():\n    return 'ok-merged'\n", encoding="utf-8")
        stdout = json.dumps({"kind": "operator-result", "ok": True})
        return subprocess.CompletedProcess(list(argv), 0, stdout, "")

    monkeypatch.setattr(AttemptCoordinator, "run_guarded", guarded_write)

    real_merge_executor = runner_mod.MergeExecutor

    def fake_merge_executor(*, repo, runner=None, timeout=30):
        return real_merge_executor(repo=repo, runner=ghrunner, timeout=timeout)

    monkeypatch.setattr(runner_mod, "MergeExecutor", fake_merge_executor)

    result = runner_mod.dispatch_operator_batch(items, max_workers=lane_count)

    # --- genuine concurrency, not a serial fallback: distinct isolation keys let all 3 lanes
    # into the pool together ---
    assert result["max_workers"] == lane_count, result
    assert result["serial_fallback_reason"] == "", result

    workers = {w["task_id"]: w for w in result["workers"]}
    assert set(workers) == set(expected)

    seen_branches = set()
    seen_prs = set()
    for task_id, exp in expected.items():
        record = workers[task_id]
        # --- this lane's own claim/receipt/merge, not shared/borrowed state ---
        assert record["repo"] == exp["repo"], record
        assert record["run_id"] == exp["run_id"], record
        assert record["status"] == "succeeded", json.dumps(record, sort_keys=True)
        assert record["execution_state"] == "applied", record
        assert record["receipt_status"] == "VERIFIED", record.get("receipt_verdict_reason")
        merge = record["merge"]
        assert merge["attempted"] is True, record
        assert merge["pr"]["number"] == exp["pr_number"], record
        assert merge["merged"] is True, record
        assert merge["reconciled"] is True, record
        assert merge["merge_commit_sha"] == exp["sha"], record
        assert merge["base_ref"] == "main", record
        seen_branches.add(exp["branch"])
        seen_prs.add(exp["pr_number"])

    # --- no cross-contamination: every scripted lane's branch/PR number was independently
    # exercised (a broken router would have collapsed lanes onto one branch/PR) ---
    assert seen_branches == {f"feat/e2e-merge-{i}" for i in range(lane_count)}
    assert seen_prs == {900 + i for i in range(lane_count)}
    for branch in seen_branches:
        assert not ghrunner._by_branch[branch], "leftover unscripted response: lane starved another lane's queue"
    for number in seen_prs:
        assert not ghrunner._by_number[number], "leftover unscripted response: lane starved another lane's queue"

    # --- each lane's operator/evidence receipts are its own files under its own run_dir,
    # never a path collision ---
    receipt_paths = {workers[t]["operator_receipt"] for t in expected}
    assert len(receipt_paths) == lane_count, receipt_paths


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_dispatch_batch_multi_pr")
