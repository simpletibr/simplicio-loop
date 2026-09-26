"""E2E — the ACTUAL loop driver (`hooks/loop_stop.py`, no mocks) driven through both terminal
states, asserting the resulting `run_state`/`PROGRESS.md` (issue #301 AC6).

`tests/test_loop_e2e.py` already proves the driver's STOP/CONTINUE decisions (evidence-gated
promise, cap, anchor). `tests/test_progress_e2e.py` already proves the `run_state` FORMULA in
isolation and via direct `loop_progress.py emit` calls. What was still missing (flagged in the
issue #301 review comment) is a test that drives the real `hooks/loop_stop.py` subprocess through
BOTH terminal paths and reads the `progress.json`/`PROGRESS.md` files IT wrote, closing the loop
between "the driver decided to stop" and "the progress projection reflects why".

`hooks/loop_stop.py`'s `_loop_progress_module()` imports `loop_progress` by inserting
`<cwd>/scripts` onto `sys.path` — so for the hook's in-process progress emission to actually fire
(rather than silently no-op via the `except Exception: return None` fail-open branch), the test
copies `scripts/loop_progress.py` + its `_locked_append.py` dependency into the scratch root's own
`scripts/` dir, exactly like `test_loop_e2e.py._install_runtime_scripts` does for the planner/wiki
scripts. Once copied there, `loop_progress.py`'s own `REPO = dirname(HERE)` resolves to the
scratch root itself, so `progress.json`/`progress.jsonl`/`PROGRESS.md` land under
`<root>/.simplicio-loop/orchestrator/loop/` with zero env-var overrides needed — the same directory
`hooks/loop_stop.py` uses for `anchor.json`/`scratchpad.md`.
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "hooks", "loop_stop.py")
LOOP_DIR_REL = os.path.join(".simplicio-loop/orchestrator", "loop")

SCRATCHPAD_TPL = """---
iteration: {iteration}
max_iterations: {max_iter}
completion_promise: "SIMPLICIO_DONE"
evidence_required: true
started_at: "2026-06-24T00:00:00Z"
---
Implement the thing and prove it works.
"""


def _install_progress_module(root):
    """Copy loop_progress.py + its _locked_append.py dependency into <root>/scripts so
    hooks/loop_stop.py's dynamic import actually finds and runs it (rather than fail-open no-op)."""
    scripts_dir = os.path.join(root, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for name in ("loop_progress.py", "_locked_append.py"):
        shutil.copy2(os.path.join(REPO, "scripts", name), os.path.join(scripts_dir, name))


def _arm(root, iteration=1, max_iter=5):
    loop = os.path.join(root, LOOP_DIR_REL)
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write(SCRATCHPAD_TPL.format(iteration=iteration, max_iter=max_iter))
    return loop


def _write_anchor(root, criteria, item="1"):
    loop = os.path.join(root, LOOP_DIR_REL)
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "anchor.json"), "w", encoding="utf-8") as f:
        json.dump({"item": item, "goal": "g", "goal_fp": "x", "criteria": criteria}, f)


def _write_watcher_pass(root, challenge="chal-1", goal_fp=""):
    loop = os.path.join(root, LOOP_DIR_REL)
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "watcher_challenge.json"), "w", encoding="utf-8") as f:
        json.dump({"challenge": challenge, "goal_fp": goal_fp,
                   "written_at": "2026-07-01T00:00:00Z"}, f)
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": "2026-07-01T00:00:01Z",
                   "challenge": challenge, "goal_fp": goal_fp}, f)


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
                   "source_payload": {"evidence_receipt": "evidence-receipt.json",
                                      "criteria_verified": 1}}, f)
    with open(os.path.join(run_dir, "quality-matrix.json"), "w", encoding="utf-8") as f:
        json.dump({
            "schema": "simplicio.quality-matrix/v1",
            "coverage_threshold": 85,
            "requirements": {
                name: {"status": "pass", "proof_ref": "tests/%s" % name}
                for name in ("implementation", "unit", "integration", "system", "regression", "benchmark")
            },
            "coverage": {"measured": 91.2},
        }, f)
    return run_dir


def _tick(root, response_text):
    return subprocess.run([sys.executable, HOOK], input=json.dumps({"text": response_text}),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=root)


def _progress_json(root):
    path = os.path.join(root, LOOP_DIR_REL, "progress.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _progress_md(root):
    path = os.path.join(root, LOOP_DIR_REL, "PROGRESS.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _events(root):
    path = os.path.join(root, LOOP_DIR_REL, "progress.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_promise_verified_stop_writes_run_state_done_and_100pct(tmp_path):
    """Drive the REAL hook through the promise-verified STOP path (same fixture as
    test_loop_e2e.test_promise_with_evidence_stops) and assert the progress projection it wrote
    on the way out — not a hand-constructed event."""
    root = str(tmp_path)
    _install_progress_module(root)
    _arm(root, iteration=1, max_iter=5)
    _write_watcher_pass(root)
    _write_anchor(root, [{"id": "AC1", "status": "done"}])  # fully verified: pct_item = 1.0
    _seed_verified_run(root)

    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")

    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "", "expected STOP (no re-feed), got: %s" % r.stdout
    assert not os.path.exists(os.path.join(root, LOOP_DIR_REL, "scratchpad.md")), \
        "loop state should be cleaned up on a verified stop"

    snap = _progress_json(root)
    assert snap["run_state"] == "done", snap
    assert abs(snap["pct_overall"] - 1.0) < 1e-6, snap

    md = _progress_md(root)
    assert "run_state" in md and "done" in md
    assert "100%" in md, md

    events = _events(root)
    assert events, "expected the refeed_exit event to have been appended"
    last = events[-1]
    assert last["step"] == "refeed_exit"
    assert last["status"] == "end"
    assert last["outcome"] == "pass"
    assert "promise verificada" in last["detail"]


def test_cap_reached_stop_writes_run_state_capped(tmp_path):
    """Drive the REAL hook through the cap-reached STOP path (same fixture as
    test_loop_e2e.test_iteration_cap_stops) and assert `run_state == capped` — a DIFFERENT
    terminal outcome than the promise-verified case above, proving the driver's two distinct
    stop reasons produce two distinct, observable run_state values."""
    root = str(tmp_path)
    _install_progress_module(root)
    _arm(root, iteration=5, max_iter=5)  # already at the cap

    r = _tick(root, "still going, no promise here")

    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "", "cap reached must STOP, not re-feed:\n%s" % r.stdout
    assert not os.path.exists(os.path.join(root, LOOP_DIR_REL, "scratchpad.md")), \
        "cap stop should clean up state"

    snap = _progress_json(root)
    assert snap["run_state"] == "capped", snap
    assert snap["run_state"] != "done", "cap stop must be distinguishable from a verified stop"

    events = _events(root)
    assert events
    last = events[-1]
    assert last["step"] == "refeed_exit"
    assert last["status"] == "end"
    assert last["outcome"] == "blocked"
    assert "cap atingido" in last["detail"]


def test_promise_and_cap_terminal_states_are_distinct(tmp_path):
    """Belt-and-suspenders: run BOTH scenarios back-to-back in sibling scratch roots and assert
    the two `run_state` values actually differ — the literal AC6 wording ("promise-verified vs.
    cap-reached termination")."""
    done_root = str(tmp_path / "done-case")
    capped_root = str(tmp_path / "capped-case")
    os.makedirs(done_root, exist_ok=True)
    os.makedirs(capped_root, exist_ok=True)

    _install_progress_module(done_root)
    _arm(done_root, iteration=1, max_iter=5)
    _write_watcher_pass(done_root)
    _write_anchor(done_root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(done_root)
    r1 = _tick(done_root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                         "https://github.com/o/r/pull/9")
    assert r1.stdout.strip() == ""

    _install_progress_module(capped_root)
    _arm(capped_root, iteration=5, max_iter=5)
    r2 = _tick(capped_root, "still going, no promise here")
    assert r2.stdout.strip() == ""

    done_state = _progress_json(done_root)["run_state"]
    capped_state = _progress_json(capped_root)["run_state"]
    assert done_state == "done"
    assert capped_state == "capped"
    assert done_state != capped_state


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_loop_driver_run_state_e2e")
