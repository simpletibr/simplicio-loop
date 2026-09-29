"""End-to-end test of the loop driver (`hooks/loop_stop.py`) — the contract that matters:

the loop stops on **evidence**, not on a bare promise, and not by accident. We drive the real hook
(no mocks) with the Cursor `text` schema and a real scratchpad on disk, and assert each exit path:

  • promise + evidence            → STOP (state cleaned up)        ← the success exit
  • promise WITHOUT evidence       → CONTINUE (re-feed, ignored)   ← the anti-false-done guard
  • promise + evidence, AC pending → CONTINUE (re-feed, ignored)   ← the anti-DRIFT anchor gate
  • promise + evidence, ACs done   → STOP                          ← anchor satisfied
  • no promise, under cap          → CONTINUE (iteration bumped)
  • iteration >= max_iterations    → STOP by cap                   ← distinct from the evidence exit
  • .simplicio-loop/orchestrator/STOP signal      → STOP immediately

This is the "stopped by evidence, not by cap" proof: cases 1 and 4 stop for *different* reasons,
and case 2 proves a promise alone never escapes the loop.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "hooks", "loop_stop.py")
JOURNAL = os.path.join(".simplicio-loop/orchestrator", "loop", "journal.jsonl")
HANDOFF = os.path.join(".simplicio-loop/orchestrator", "loop", "HANDOFF.md")

SCRATCHPAD = """---
iteration: {iteration}
max_iterations: {max_iter}
completion_promise: "SIMPLICIO_DONE"
evidence_required: true
started_at: "2026-06-24T00:00:00Z"
---
Implement the thing and prove it works.
"""


def _arm(root, iteration=1, max_iter=5):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write(SCRATCHPAD.format(iteration=iteration, max_iter=max_iter))
    return loop


def _tick(root, response_text, env=None):
    """Run loop_stop.py exactly as the host would: cwd=root, stdin = {text:...}."""
    return subprocess.run([sys.executable, HOOK], input=json.dumps({"text": response_text}),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=root, env=env)


def _scratchpad(root):
    return os.path.join(root, ".simplicio-loop/orchestrator", "loop", "scratchpad.md")


def _iteration(root):
    with open(_scratchpad(root), encoding="utf-8") as f:
        for line in f:
            if line.startswith("iteration:"):
                return int(line.split(":", 1)[1])
    return None


def _append_attempt(root, record):
    with open(os.path.join(root, JOURNAL), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _install_runtime_scripts(root):
    scripts_dir = os.path.join(root, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for name in ("cross_agent_wiki.py", "hierarchical_planner.py", "completion_oracle.py"):
        shutil.copy2(os.path.join(REPO, "scripts", name), os.path.join(scripts_dir, name))


def _tick_hook(root, hook_path, response_text, mode="cursor", env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    current_py = full_env.get("PYTHONPATH", "").strip()
    full_env["PYTHONPATH"] = REPO if not current_py else f"{REPO}{os.pathsep}{current_py}"
    if mode == "cursor":
        return subprocess.run([sys.executable, hook_path], input=json.dumps({"text": response_text}),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=root, env=full_env)
    transcript = Path(root) / "transcript.jsonl"
    transcript.write_text(json.dumps({
        "role": "assistant",
        "message": {"content": [{"text": response_text}]}
    }) + "\n", encoding="utf-8")
    return subprocess.run([sys.executable, hook_path],
                          input=json.dumps({"transcript_path": str(transcript)}),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=root, env=full_env)


def _write_watcher_challenge(root, challenge="chal-1", goal_fp="", written_at="2026-07-01T00:00:00Z"):
    """Simulate a challenge already issued by a prior turn's re-feed (#82)."""
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "watcher_challenge.json"), "w", encoding="utf-8") as f:
        json.dump({"challenge": challenge, "goal_fp": goal_fp, "written_at": written_at}, f)


def _write_watcher_pass(root, challenge="chal-1", goal_fp="", checked_at="2026-07-01T00:00:01Z"):
    """Write a passing watcher state (Asolaria N-Nest Corrective Gate) that echoes the current
    per-iteration challenge (#82) — a receipt written without a matching challenge on disk must
    NOT satisfy the gate; see test_watcher_receipt_without_challenge_does_not_stop."""
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    _write_watcher_challenge(root, challenge=challenge, goal_fp=goal_fp, written_at="2026-07-01T00:00:00Z")
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": checked_at,
                    "challenge": challenge, "goal_fp": goal_fp}, f)


def _write_phase(root, phase="implement", strategy="Ship the smallest verified increment", guard="Do not refactor unrelated code"):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "phase.json"), "w", encoding="utf-8") as f:
        json.dump({
            "phase": phase,
            "strategy": strategy,
            "tactical_guard": guard,
            "iteration": 2,
        }, f)


def test_promise_with_evidence_stops(tmp_path):
    root = str(tmp_path)
    _arm(root)
    _write_watcher_pass(root)  # watcher-gate must pass before promise is honored
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(root)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.returncode == 0
    assert r.stdout.strip() == "", "expected STOP (no re-feed), got: %s" % r.stdout
    assert not os.path.exists(_scratchpad(root)), "state should be cleaned up on a verified stop"


def test_promise_without_run_receipt_never_uses_legacy_fallback(tmp_path):
    root = str(tmp_path)
    _arm(root)
    _write_watcher_pass(root)
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓")
    assert r.returncode == 0
    assert "followup_message" in r.stdout or "block" in r.stdout
    assert os.path.exists(_scratchpad(root)), "missing run receipt must not bypass the oracle"
    assert not os.path.exists(os.path.join(root, ".simplicio-loop/orchestrator", "runs")), "no run receipt was created"


def test_bare_promise_without_evidence_continues(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    r = _tick(root, "I think I'm done. <promise>SIMPLICIO_DONE</promise>")  # no evidence token
    assert r.returncode == 0
    # the loop must NOT stop on a bare promise — it re-feeds and bumps the iteration
    assert "followup_message" in r.stdout or "block" in r.stdout, \
        "a bare promise must be ignored, not honored:\n%s" % r.stdout
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped on a bare promise"
    assert _iteration(root) == 2


def _write_anchor(root, criteria):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "anchor.json"), "w", encoding="utf-8") as f:
        json.dump({"item": "1", "goal": "g", "goal_fp": "x", "criteria": criteria}, f)


def _seed_verified_run(root, run_id="r1"):
    run_dir = os.path.join(root, ".simplicio-loop/orchestrator", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "simplicio.run-manifest/v1", "run_id": run_id,
                   "delivery_target": "verified"}, f)
    with open(os.path.join(run_dir, "task-contract.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "simplicio.task-contract-collection/v1", "task_count": 1}, f)
    with open(os.path.join(run_dir, "mapper-context.json"), "w", encoding="utf-8") as f:
        json.dump({"handoff": {"stdout": {"context_pack": {"files": []}}}}, f)
    with open(os.path.join(run_dir, "operator-receipt.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "simplicio.operator-receipt/v0", "execution_state": "verified"}, f)
    with open(os.path.join(run_dir, "evidence-receipt.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "simplicio.evidence-receipt/v1", "status": "VERIFIED",
                   "criteria": [{"id": "AC1", "verification_state": "verified"}],
                   "summary": {"criteria_total": 1, "criteria_verified": 1,
                               "scenario_total": 1, "scenario_verified": 1,
                               "rule_total": 1, "rule_verified": 1}}, f)
    with open(os.path.join(run_dir, "delivery-receipt.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": "simplicio.delivery-receipt/v1", "target": "verified",
                   "current_state": "verified", "ready": True,
                   "source_kind": "local",
                   "source_payload": {
                       "evidence_receipt": "evidence-receipt.json",
                       "criteria_verified": 1,
                   }}, f)
    with open(os.path.join(run_dir, "quality-matrix.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": "simplicio.quality-matrix/v1",
            "coverage_threshold": 85,
            "requirements": {
                name: {"status": "pass", "proof_ref": f"tests/{name}"}
                for name in ("implementation", "unit", "integration", "system", "regression", "benchmark")
            },
            "coverage": {"measured": 91.2},
        }, f)
    return run_dir


def test_promise_with_evidence_but_pending_anchor_continues(tmp_path):
    # The mechanical anti-drift gate: even WITH evidence, a promise must NOT stop the loop while the
    # task anchor still has an unverified acceptance criterion — it re-feeds instead, naming the gap.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _write_anchor(root, [{"id": "AC1", "status": "done"}, {"id": "AC2", "status": "pending"}])
    r = _tick(root, "Looks done. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.returncode == 0
    assert "followup_message" in r.stdout or "block" in r.stdout, \
        "a promise with an open AC must be ignored, not honored:\n%s" % r.stdout
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped with an open AC"
    assert "AC2" in r.stdout, "re-feed should name the open acceptance criterion:\n%s" % r.stdout


def test_promise_with_evidence_all_acs_done_stops(tmp_path):
    # Once every anchored AC is verified, the evidence-backed promise stops the loop as before.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _write_watcher_pass(root)  # watcher-gate must pass
    _write_anchor(root, [{"id": "AC1", "status": "done"}, {"id": "AC2", "status": "done"}])
    _seed_verified_run(root)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.returncode == 0
    assert r.stdout.strip() == "", "expected STOP (every AC verified), got: %s" % r.stdout
    assert not os.path.exists(_scratchpad(root)), "state should be cleaned up on a verified stop"


def test_no_promise_continues_and_bumps_iteration(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=2, max_iter=5)
    r = _tick(root, "Made progress; still working on the failing test.")
    assert "followup_message" in r.stdout
    assert _iteration(root) == 3


def test_continue_surfaces_phase_hint(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=2, max_iter=5)
    _write_phase(root, phase="implement", strategy="Ship the smallest verified increment", guard="Do not refactor unrelated code")
    r = _tick(root, "Still implementing; no promise yet.")
    assert r.returncode == 0
    assert "phase=implement" in r.stdout
    assert "guard=Do not refactor unrelated code" in r.stdout


def test_continue_runs_planner_and_refreshes_wiki(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=2, max_iter=5)
    _install_runtime_scripts(root)
    r = _tick(root, "Still implementing; no promise yet.")
    assert r.returncode == 0
    assert "phase=implement" in r.stdout, r.stdout
    phase = os.path.join(root, ".simplicio-loop/orchestrator", "loop", "phase.json")
    summary = os.path.join(root, ".simplicio-loop/orchestrator", "wiki", "SUMMARY.md")
    journal_dir = os.path.join(root, ".simplicio-loop/orchestrator", "wiki", "journal")
    assert os.path.exists(phase), "planner should materialize phase.json on first active turn"
    assert os.path.exists(summary), "continue path should refresh the cross-agent wiki summary"
    assert os.listdir(journal_dir), "continue path should capture at least one wiki journal entry"


def test_refeed_injects_canonical_startup_orientation_once(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    r = _tick(root, "Still implementing; no promise yet.")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    followup = payload["followup_message"]
    assert "[simplicio-loop startup orientation]" in followup
    assert "No Runtime" in followup
    assert 'simplicio-loop turbo --repo <path> --task "<task>"' in followup
    assert "OPENROUTER_API_KEY" in followup
    assert "edit-plan" not in followup
    assert followup.count("[simplicio-loop startup orientation]") == 1
    assert followup.count("No Runtime") == 1


def test_startup_orientation_has_one_canonical_marker_pair():
    skill = Path(REPO) / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.count("<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->") == 1
    assert text.count("<!-- SIMPLICIO-LLM-ORIENTATION:END -->") == 1


def test_iteration_cap_stops(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=5, max_iter=5)  # at the cap
    r = _tick(root, "still going, no promise here")
    assert r.stdout.strip() == "", "cap reached must STOP, not re-feed:\n%s" % r.stdout
    assert not os.path.exists(_scratchpad(root)), "cap stop should clean up state"


def test_iteration_cap_handoff_carries_attempt_lineage(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=5, max_iter=5)
    _append_attempt(root, {
        "iteration": 4,
        "action": "split provider adapter",
        "gate": "blocked",
        "fingerprint": "deadbeef0001",
        "note": "needs a fixture",
        "execution_state": "authorized",
        "stage_id": "validate",
        "decision": "retry",
        "validator": "pytest",
        "retry_count": 2,
        "chunk_id": "audit:2",
        "source_artifact": "audit.md",
        "blocked_reason": "fixture missing",
        "next_action": "add fixture",
    })
    r = _tick(root, "still going, no promise here")
    assert r.stdout.strip() == "", "cap reached must STOP, not re-feed:\n%s" % r.stdout
    handoff = os.path.join(root, HANDOFF)
    assert os.path.exists(handoff), "cap stop should write HANDOFF.md"
    body = open(handoff, encoding="utf-8").read()
    assert "state=authorized" in body
    assert "stage=validate" in body
    assert "validator=pytest" in body
    assert "next=add fixture" in body
    assert "blocked=fixture missing" in body


def test_stop_signal_halts(tmp_path):
    root = str(tmp_path)
    _arm(root)
    open(os.path.join(root, ".simplicio-loop/orchestrator", "STOP"), "w").close()
    r = _tick(root, "anything")
    assert r.stdout.strip() == ""
    assert not os.path.exists(_scratchpad(root))


def test_done_flag_halts(tmp_path):
    root = str(tmp_path)
    loop = _arm(root)
    open(os.path.join(loop, "done.flag"), "w").close()
    r = _tick(root, "anything")
    assert "followup_message" in r.stdout
    assert os.path.exists(_scratchpad(root)), "done.flag alone must not bypass the oracle"


def test_legacy_done_file_halts(tmp_path):
    root = str(tmp_path)
    loop = _arm(root)
    open(os.path.join(loop, "done"), "w").close()
    r = _tick(root, "anything")
    assert "followup_message" in r.stdout
    assert os.path.exists(_scratchpad(root)), "legacy done file alone must not bypass the oracle"


def test_done_flag_with_valid_oracle_halts(tmp_path):
    root = str(tmp_path)
    loop = _arm(root)
    open(os.path.join(loop, "done.flag"), "w").close()
    _write_watcher_challenge(root, challenge="done-ok", written_at="2026-07-10T00:00:00Z")
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": "2026-07-10T00:00:01Z",
                   "challenge": "done-ok", "goal_fp": ""}, f)
    run_dir = _seed_verified_run(root)
    with open(os.path.join(loop, "last_response.txt"), "w", encoding="utf-8") as f:
        f.write("<promise>SIMPLICIO_DONE</promise>")
    r = _tick(root, "anything")
    assert r.stdout.strip() == ""
    assert not os.path.exists(_scratchpad(root)), "done.flag should stop only when oracle is green"
    receipt = os.path.join(run_dir, "completion-receipt.json")
    assert os.path.exists(receipt), "cleanup must happen only after the completion receipt is persisted"


def test_gate_lock_fresh_allows_stop_without_consuming_iteration(tmp_path):
    root = str(tmp_path)
    loop = _arm(root, iteration=2, max_iter=5)
    open(os.path.join(loop, "gate.lock"), "w").close()
    r = _tick(root, "waiting on background verification")
    assert r.stdout.strip() == ""
    assert os.path.exists(_scratchpad(root)), "fresh gate lock should preserve loop state"
    assert _iteration(root) == 2, "fresh gate lock should not consume an iteration"


def test_gate_lock_stale_refeeds_again(tmp_path):
    root = str(tmp_path)
    loop = _arm(root, iteration=2, max_iter=5)
    lock = os.path.join(loop, "gate.lock")
    open(lock, "w").close()
    stale = __import__("time").time() - 1900
    os.utime(lock, (stale, stale))
    r = _tick(root, "background gate appears stale")
    assert "followup_message" in r.stdout or "block" in r.stdout
    assert _iteration(root) == 3, "stale gate lock should stop blocking and re-feed"


def test_spindle_latched_writes_handoff_and_stops(tmp_path):
    root = str(tmp_path)
    loop = _arm(root, iteration=2, max_iter=5)
    with open(os.path.join(loop, "spindle_state.json"), "w", encoding="utf-8") as f:
        json.dump({"latch": True, "next_agent": "codex"}, f)
    r = _tick(root, "handoff in progress")
    assert r.stdout.strip() == ""
    assert not os.path.exists(_scratchpad(root))
    handoff = os.path.join(root, HANDOFF)
    assert os.path.exists(handoff), "latched spindle should write HANDOFF.md"
    assert "codex" in open(handoff, encoding="utf-8").read()


def test_handoff_includes_completion_oracle_reason_when_present(tmp_path):
    root = str(tmp_path)
    _arm(root, iteration=5, max_iter=5)
    run_dir = _seed_verified_run(root)
    with open(os.path.join(run_dir, "completion-receipt.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": "simplicio.completion-receipt/v1",
            "ready": False,
            "verdict": "DELIVERY_PENDING",
            "reason_code": "watcher_mismatch",
            "tag": "UNVERIFIED",
        }, f)
    r = _tick(root, "still going, no promise here")
    assert r.stdout.strip() == ""
    handoff = os.path.join(root, HANDOFF)
    body = open(handoff, encoding="utf-8").read()
    assert "## Completion oracle" in body
    assert "reason_code: promise_not_exact" in body


def test_completion_parity_between_source_bundle_and_cursor_claude_success(tmp_path):
    hook_paths = [
        os.path.join(REPO, "hooks", "loop_stop.py"),
        os.path.join(REPO, "simplicio_loop", "_bundle", "hooks", "loop_stop.py"),
    ]
    results = []
    for idx, hook_path in enumerate(hook_paths):
        for mode in ("cursor", "claude"):
            root = str(tmp_path / f"case-{idx}-{mode}")
            os.makedirs(root, exist_ok=True)
            _install_runtime_scripts(root)
            _arm(root)
            _write_watcher_pass(root, challenge="same-fixture")
            _write_anchor(root, [{"id": "AC1", "status": "done"}])
            run_dir = _seed_verified_run(root)
            result = _tick_hook(
                root,
                hook_path,
                "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ https://github.com/o/r/pull/9",
                mode=mode,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            results.append({
                "stdout": result.stdout.strip(),
                "scratchpad_exists": os.path.exists(_scratchpad(root)),
                "completion_receipt": os.path.exists(os.path.join(run_dir, "completion-receipt.json")),
            })
    assert all(item["stdout"] == "" for item in results)
    assert all(item["scratchpad_exists"] is False for item in results)
    assert all(item["completion_receipt"] is True for item in results)


def test_completion_parity_between_source_bundle_and_cursor_claude_rejects_bare_done_flag(tmp_path):
    hook_paths = [
        os.path.join(REPO, "hooks", "loop_stop.py"),
        os.path.join(REPO, "simplicio_loop", "_bundle", "hooks", "loop_stop.py"),
    ]
    results = []
    for idx, hook_path in enumerate(hook_paths):
        for mode in ("cursor", "claude"):
            root = str(tmp_path / f"reject-{idx}-{mode}")
            os.makedirs(root, exist_ok=True)
            _install_runtime_scripts(root)
            loop = _arm(root)
            open(os.path.join(loop, "done.flag"), "w").close()
            result = _tick_hook(root, hook_path, "anything", mode=mode)
            assert result.returncode == 0, result.stdout + result.stderr
            results.append({
                "scratchpad_exists": os.path.exists(_scratchpad(root)),
                "followup": "followup_message" in result.stdout,
                "block": '"decision": "block"' in result.stdout or '"decision":"block"' in result.stdout,
            })
    assert all(item["scratchpad_exists"] is True for item in results)
    assert all(item["followup"] or item["block"] for item in results)


def test_watcher_receipt_without_challenge_does_not_stop(tmp_path):
    # #82: a plain, unauthenticated watcher_state.json (no challenge on disk at all) must NOT
    # satisfy the gate — this is exactly the one-Write-call spoof the challenge binding closes.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": "2026-07-01T00:00:00Z"}, f)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert "followup_message" in r.stdout or "block" in r.stdout, \
        "an unchallenged watcher receipt must not honor the promise:\n%s" % r.stdout
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped on an unchallenged receipt"


def test_watcher_receipt_wrong_challenge_does_not_stop(tmp_path):
    # A receipt that echoes the WRONG (stale/foreign) challenge must not satisfy the gate either.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _write_watcher_challenge(root, challenge="real-challenge")
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": "2026-07-01T00:00:01Z",
                    "challenge": "guessed-or-stale-challenge"}, f)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert "followup_message" in r.stdout or "block" in r.stdout, \
        "a receipt echoing the wrong challenge must not honor the promise:\n%s" % r.stdout
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped on a mismatched challenge"


def test_watcher_receipt_matching_challenge_stops(tmp_path):
    # The positive path: a receipt that correctly echoes the CURRENT challenge still stops the loop.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _write_watcher_pass(root, challenge="issued-this-turn")
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(root)
    with open(os.path.join(root, ".simplicio-loop/orchestrator", "loop", "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": "2026-07-01T00:00:01Z",
                    "challenge": "issued-this-turn", "goal_fp": ""}, f)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.stdout.strip() == "", "a correctly-challenged receipt should stop the loop:\n%s" % r.stdout
    assert not os.path.exists(_scratchpad(root))


def test_maintenance_deferred_receipt_hands_off_without_honoring_promise(tmp_path):
    """Root hook parity: backlog-only maintenance is incomplete and must hand off."""
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    run_dir = _seed_verified_run(root)
    with open(os.path.join(run_dir, "completion-receipt.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": "simplicio.completion-receipt/v1",
            "ready": False,
            "reason_code": "maintenance_deferred",
            "tag": "UNVERIFIED",
        }, f)

    result = _tick(root, "Looks done. <promise>SIMPLICIO_DONE</promise> tests pass")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert not os.path.exists(_scratchpad(root))
    handoff = os.path.join(root, HANDOFF)
    assert os.path.exists(handoff)
    assert "maintenance deferred" in open(handoff, encoding="utf-8").read()


def test_bound_operator_missing_blocks_when_simplicio_loop_shipped(tmp_path):
    # #83: when the repo ships the simplicio-loop companion skill, a missing bound operator
    # (simplicio-mapper / simplicio-dev-cli) must BLOCK the loop (handoff + stop), not silently
    # continue with LLM hand-survey/hand-edit. PATH is scrubbed to an empty dir so the assertion
    # holds even on a machine that has the operators installed globally (they bind via PATH
    # lookup — `shutil.which`), not just in a sandbox that happens to lack them.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    skill_dir = os.path.join(root, ".claude", "skills", "simplicio-loop")
    os.makedirs(skill_dir, exist_ok=True)
    open(os.path.join(skill_dir, "SKILL.md"), "w").close()
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    env = dict(os.environ, PATH=str(empty_path))
    r = _tick(root, "still working, no promise yet", env=env)
    assert r.stdout.strip() == "", "missing bound operator must BLOCK (stop), not re-feed:\n%s" % r.stdout
    assert not os.path.exists(_scratchpad(root)), "operator-missing block should clean up loop state"
    handoff = os.path.join(root, HANDOFF)
    assert os.path.exists(handoff), "operator-missing block should write HANDOFF.md"
    assert "bound operator missing" in open(handoff, encoding="utf-8").read()


def test_no_simplicio_loop_skill_skips_operator_check(tmp_path):
    # A bare simplicio-tasks loop (no simplicio-loop companion skill shipped) has no operator
    # requirement — the check must be a no-op and the loop continues normally.
    root = str(tmp_path)
    _arm(root, iteration=2, max_iter=5)
    r = _tick(root, "still working, no promise yet")
    assert "followup_message" in r.stdout
    assert _iteration(root) == 3


def _write_web_file(root, rel="frontend/Login.tsx"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("export function Login() { return <button onClick={()=>fetch('/api/login')}/> }\n")
    subprocess.run(["git", "init", "-q"], cwd=root)


def _install_flow_audit(root):
    scripts_dir = os.path.join(root, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    shutil.copy2(os.path.join(REPO, "scripts", "flow_audit.py"), os.path.join(scripts_dir, "flow_audit.py"))


def test_flow_audit_gap_blocks_promise_on_web_diff(tmp_path):
    # #80: a web-touching diff with no flow-audit receipt must not honor the promise, even with
    # evidence + watcher pass + no open ACs — the front→back gate is mechanical now.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _install_flow_audit(root)
    _write_web_file(root)
    _write_watcher_pass(root)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert "followup_message" in r.stdout or "block" in r.stdout, \
        "a web-touching diff with no flow-audit receipt must not honor the promise:\n%s" % r.stdout
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped without a flow-audit receipt"
    assert "flow audit" in r.stdout.lower()


def test_flow_audit_gap_absent_for_non_web_diff(tmp_path):
    # A non-web diff is unaffected — no new friction.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _install_flow_audit(root)
    path = os.path.join(root, "server.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("print('hi')\n")
    subprocess.run(["git", "init", "-q"], cwd=root)
    _write_watcher_pass(root)
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(root)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.stdout.strip() == "", "non-web diff must not be gated by flow-audit:\n%s" % r.stdout


def test_flow_audit_green_receipt_allows_stop(tmp_path):
    # A fresh, green flow-audit receipt lets the promise stop the loop as usual.
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _install_flow_audit(root)
    _write_web_file(root)
    _write_watcher_pass(root)
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(root)
    orch = os.path.join(root, ".simplicio-loop/orchestrator")
    os.makedirs(orch, exist_ok=True)
    receipt = os.path.join(orch, "flow-audit.json")
    with open(receipt, "w", encoding="utf-8") as f:
        json.dump({"ok": True, "counts": {"high_issues": 0}}, f)
    future = __import__("time").time() + 2
    os.utime(receipt, (future, future))
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.stdout.strip() == "", "green flow-audit receipt should allow the stop:\n%s" % r.stdout


def test_handoff_not_clobbered_by_wiki_on_cap_stop(tmp_path):
    # #68: loop_stop's rich handoff (frozen goal + AC checklist) must survive the cap stop — it
    # must NOT be immediately overwritten by cross_agent_wiki's thinner layout.
    root = str(tmp_path)
    _arm(root, iteration=5, max_iter=5)
    _install_runtime_scripts(root)
    r = _tick(root, "still going, no promise here")
    assert r.stdout.strip() == ""
    handoff = os.path.join(root, HANDOFF)
    assert os.path.exists(handoff)
    body = open(handoff, encoding="utf-8").read()
    assert body.startswith("# simplicio-loop handoff"), \
        "rich loop_stop handoff must not be clobbered by cross_agent_wiki:\n%s" % body[:200]
    assert "(cross-agent wiki)" not in body.splitlines()[0]


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_loop_e2e")
