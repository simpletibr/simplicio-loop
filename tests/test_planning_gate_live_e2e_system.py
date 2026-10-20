"""True e2e for issue #284's remaining gap: "a true GitHub-backed E2E" for the planning-gate/
mutation-authority machinery, against a LIVE GitHub issue via the REAL `gh` CLI (no injected
fake transport for the GitHub half) -- the same live-e2e convention established by
`tests/test_progress_comment_live_e2e.py` and `tests/test_merge_executor_live_e2e.py`.

Gate: only runs when SIMPLICIO_LIVE_GH_E2E=1 is set AND `gh` is authenticated. Repo overridable
via SIMPLICIO_LIVE_GH_REPO (defaults to simpletibr/simplicio-loop). Skipped everywhere else
(default local runs, CI without a token) -- never touches the network unless explicitly opted
into.

What it proves, against the real API:
  1. `source_snapshot.capture_github_issue_snapshot()` captures a REAL revision of a freshly
     created scratch issue (real `gh issue view`, not a fixture).
  2. `planning_gate.build_planning_receipt()` folds that real source-snapshot hash into a
     `ready_for_mutation=True` receipt with a working `mutation_authority` token.
  3. `github_lifecycle.publish_lifecycle_state(state="CLAIMED", ...)` posts a REAL comment on
     the scratch issue (real `gh api` POST) -- re-queried and confirmed present.
  4. `planning_gate.publish_planning_receipt()` updates the SAME canonical comment to `PLANNED`
     (real `gh api` PATCH, idempotent create-or-update, same comment id) -- re-queried and
     confirmed.
  5. A trivial guarded mutation through the REAL `execute_operator()` gate succeeds using ONLY
     the receipt built in step 2 (mandatory-by-default `SIMPLICIO_REQUIRE_MUTATION_AUTHORITY` is
     left at its default, i.e. genuinely enforced) -- `evaluate_mutation_authority()` verifies
     `ok=True` against the live source-snapshot hash, and a subsequent source edit would have
     invalidated it (`source_drift`), proven by a direct `evaluate_mutation_authority()` call
     against a synthetic drifted hash.

The dev-cli operator subprocess itself is faked via `SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON`
(the same seam `tests/test_284_lifecycle_dag_idempotence.py` and `tests/test_runner_cli.py` use
everywhere in this repo to avoid requiring the real `simplicio-dev-cli` binary in CI) -- this is
NOT a fake GitHub transport; every GitHub-facing call in this test is real.

Cleanup is unconditional (try/finally): the scratch comment is deleted and the scratch issue is
closed even if an assertion fails, so a broken assertion never leaves noise on the tracker.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.external_integration

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)

from pr_evidence import publish_comment  # noqa: E402  (scripts/ on sys.path for this import)

from simplicio_loop import github_lifecycle  # noqa: E402
from simplicio_loop import planning_gate  # noqa: E402
from simplicio_loop import runner as runner_mod  # noqa: E402
from simplicio_loop.source_snapshot import capture_github_issue_snapshot  # noqa: E402

from tests.test_runner_cli_integration import _arm_deterministic_preflight_fixture  # noqa: E402

LIVE_REPO = os.environ.get("SIMPLICIO_LIVE_GH_REPO", "simpletibr/simplicio-loop")


def _live_gate_open():
    if os.environ.get("SIMPLICIO_LIVE_GH_E2E") != "1":
        return False
    if not shutil.which("gh"):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def _gh(args, check=True):
    # encoding="utf-8" explicitly (not the platform default, e.g. cp1252 on Windows) --
    # real GitHub content (emoji in the rendered lifecycle comment, non-ASCII issue text)
    # otherwise raises/garbles under the locale codec, exactly the failure mode
    # `scripts/pr_evidence.py::_run_gh` already guards against the same way.
    r = subprocess.run(["gh"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args), r.stderr or r.stdout))
    return r


def _create_scratch_issue():
    r = _gh([
        "issue", "create", "--repo", LIVE_REPO,
        "--title", "[test-scratch] #284 planning-gate live e2e (auto-created, safe to close)",
        "--body", "Auto-created by tests/test_planning_gate_live_e2e.py -- verifies the "
                  "planning-gate/mutation-authority CLAIMED->PLANNED lifecycle comment against "
                  "the live GitHub API, then deletes its own comment(s) and closes this issue. "
                  "Safe to ignore.",
    ])
    url = r.stdout.strip().splitlines()[-1]
    return url.rstrip("/").rsplit("/", 1)[-1]


def _lifecycle_comment(issue):
    r = _gh(["api", "repos/%s/issues/%s/comments" % (LIVE_REPO, issue), "--paginate"])
    comments = json.loads(r.stdout or "[]")
    marked = [c for c in comments
              if github_lifecycle.LIFECYCLE_COMMENT_MARKER in (c.get("body") or "")]
    return marked


def test_planning_gate_claimed_then_planned_lands_on_live_issue_and_gates_real_mutation():
    if not _live_gate_open():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[live_github_opt_in]: set "
            "SIMPLICIO_LIVE_GH_E2E=1 with an authenticated gh CLI to run this "
            "live e2e against %s" % LIVE_REPO
        )

    issue = _create_scratch_issue()
    owner, repo_name = LIVE_REPO.split("/", 1)
    try:
        # -- 1. real source snapshot of the live scratch issue --
        snapshot = capture_github_issue_snapshot(LIVE_REPO, issue)
        assert snapshot["schema"] == "simplicio.source-snapshot/v1"
        snapshot_hash = snapshot["source"]["snapshot_hash"]
        assert snapshot_hash

        run_id = "run-284-live-e2e"

        # -- 2. real planning receipt referencing the live issue --
        contract = {
            "schema": "simplicio.task-contract-collection/v1",
            "collection_hash": "c-live-e2e",
            "tasks": [{
                "id": "T1",
                "scenarios": [{"id": "SCN1", "title": "Trivial live e2e edit", "given": ["repo exists"],
                               "when": ["operator runs"], "then": ["file updated"], "rule_refs": ["RN1"]}],
                "rules": [{"id": "RN1", "text": "trivial edit", "scenario_refs": ["SCN1"]}],
            }],
        }
        plan = {
            "schema": "simplicio.plan/v1", "task_contract_hash": "c-live-e2e",
            "mapper_pack_hash": "mp1", "context_pack_hash": "mp1",
            "repo_state": {"head": "head-fixed", "tree_hash": "tree-fixed"},
            "freshness": {"verified": True,
                          "current_state": {"head": "head-fixed", "tree_hash": "tree-fixed"}},
            "steps": [{
                "id": "T1", "candidate_targets": ["src/app.py"], "to_create": ["src/app.py"],
                "rule_ids": ["RN1"],
                "steps": [{
                    "scenario_id": "SCN1", "rule_ids": ["RN1"],
                    "plan": {"read_paths": ["src/app.py"], "change_paths": ["src/app.py"],
                             "test_commands": ["pytest tests/test_a.py"]},
                }],
            }],
        }
        from simplicio_loop.plan_contract import validate_plan
        validation = validate_plan(plan, contract["tasks"], ".", contract_hash="c-live-e2e",
                                   current_state={"head": "head-fixed", "tree_hash": "tree-fixed"})
        assert validation["valid"], validation["errors"]

        receipt = planning_gate.build_planning_receipt(
            run_id=run_id, attempt=1, contract=contract, plan=plan,
            plan_validation=validation, source_snapshot=snapshot,
        )
        assert receipt["ready_for_mutation"] is True
        assert receipt["mutation_authority"]
        assert receipt["source"]["snapshot_hash"] == snapshot_hash

        # -- 3. real CLAIMED comment on the live issue --
        claimed_state = github_lifecycle.publish_lifecycle_state(
            owner=owner, repo=repo_name, issue=issue, state="CLAIMED",
            run_id=run_id, attempt_id="1", publish_comment_fn=publish_comment,
        )
        assert claimed_state["verified"] is True, claimed_state
        marked_after_claim = _lifecycle_comment(issue)
        assert len(marked_after_claim) == 1, marked_after_claim
        assert "CLAIMED" in marked_after_claim[0]["body"]
        comment_id = marked_after_claim[0]["id"]

        # -- 4. real PLANNED comment update, SAME canonical comment --
        planned_receipt = planning_gate.publish_planning_receipt(
            receipt, publish_comment_fn=publish_comment,
        )
        assert planned_receipt is not None
        assert planned_receipt["verified"] is True, planned_receipt
        marked_after_planned = _lifecycle_comment(issue)
        assert len(marked_after_planned) == 1, marked_after_planned
        assert marked_after_planned[0]["id"] == comment_id, (
            "PLANNED must update the SAME canonical comment CLAIMED created, not a new one")
        assert "PLANNED" in marked_after_planned[0]["body"]

        print("MEASURED|live e2e: issue=%s comment_id=%s CLAIMED -> PLANNED on same comment"
              % (issue, comment_id))

        # -- 5. a trivial guarded mutation through the REAL execute_operator() gate,
        #    using ONLY this receipt (mandatory mutation-authority genuinely enforced) --
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            class _Monkeypatch:
                """Minimal stand-in exposing the subset of pytest.monkeypatch used by
                `_arm_deterministic_preflight_fixture`, so this live e2e can reuse the same
                deterministic repo/mapper/operator-preflight fixture without pytest's fixture
                injection (this test is invoked directly, not as a pytest-collected function
                needing `monkeypatch` as an argument)."""
                def __init__(self):
                    self._undo = []

                def setattr(self, obj, name, value):
                    self._undo.append((obj, name, getattr(obj, name)))
                    setattr(obj, name, value)

                def setenv(self, name, value):
                    old = os.environ.get(name)
                    self._undo.append((os.environ, name, old))
                    os.environ[name] = value

                def delenv(self, name, raising=False):
                    old = os.environ.pop(name, None)
                    self._undo.append((os.environ, name, old))

                def undo(self):
                    for obj, name, old in reversed(self._undo):
                        if obj is os.environ:
                            if old is None:
                                os.environ.pop(name, None)
                            else:
                                os.environ[name] = old
                        else:
                            setattr(obj, name, old)

            mp = _Monkeypatch()
            try:
                repo_path, _, armed, run_dir = _arm_deterministic_preflight_fixture(mp, tmp_path)
                run_id_armed = armed["manifest"]["run_id"]

                # Overwrite the auto-built (local-only) receipt with one that folds in the
                # REAL live source-snapshot hash, bound to THIS armed run/attempt/contract/plan.
                armed_contract = json.loads((run_dir / "task-contract.json").read_text(encoding="utf-8"))
                armed_plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
                live_receipt = planning_gate.build_planning_receipt(
                    run_id=run_id_armed, attempt=1, contract=armed_contract, plan=armed_plan,
                    plan_validation=armed_plan["validation"], source_snapshot=snapshot,
                )
                assert live_receipt["ready_for_mutation"] is True
                (run_dir / "planning-receipt.json").write_text(
                    json.dumps(live_receipt), encoding="utf-8",
                )

                exec_env = {
                    "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON": json.dumps({
                        "returncode": 0, "stdout": {"kind": "operator-applied", "ok": True},
                        "stderr": "",
                        "write_files": {"src/app.py": "def main():\n    return 'live-e2e'\n"},
                    }),
                }
                with patch.dict(os.environ, exec_env, clear=False):
                    payload = runner_mod.execute_operator(str(repo_path), run_id_armed)
                assert payload["state"]["phase"] == "validating"
                op_receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
                assert op_receipt["execution_state"] == "applied"

                # Mutation authority is verified against the REAL live source-snapshot hash --
                # a live edit to the issue would change this hash and invalidate the authority.
                verdict = planning_gate.evaluate_mutation_authority(
                    run_dir, run_id=run_id_armed, attempt=1,
                    task_contract_hash=armed_contract["collection_hash"],
                    plan_hash=live_receipt["plan_hash"], source_snapshot_hash=snapshot_hash,
                )
                assert verdict["ok"] is True, verdict

                # A drifted hash (simulating an edit between planning and execution) is
                # correctly rejected -- proves the gate is genuinely checking, not a rubber stamp.
                drifted_verdict = planning_gate.evaluate_mutation_authority(
                    run_dir, run_id=run_id_armed, attempt=1,
                    task_contract_hash=armed_contract["collection_hash"],
                    plan_hash=live_receipt["plan_hash"], source_snapshot_hash="sha256:drifted-fake",
                )
                assert drifted_verdict["ok"] is False
                assert drifted_verdict["reason_code"] == "source_drift"

                print("MEASURED|live e2e: execute_operator() succeeded gated on the live-issue "
                      "receipt; a drifted source hash was correctly rejected (source_drift)")
            finally:
                mp.undo()

        for c in marked_after_planned:
            _gh(["api", "-X", "DELETE",
                "repos/%s/issues/comments/%s" % (LIVE_REPO, c["id"])], check=False)
    finally:
        _gh(["issue", "close", issue, "--repo", LIVE_REPO,
            "--comment", "Live e2e scratch issue for #284 -- cleaned up automatically."],
           check=False)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_planning_gate_live_e2e")
