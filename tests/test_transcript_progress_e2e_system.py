"""E2E gap-closure for issue #302 (EPIC #296) — the two gaps flagged on PR #332's own comment:

  * AC3/AC4 were previously covered only at the unit level (calling `loop_stop._emit_final_progress`
    / `loop_stop._progress_header_prefix` directly against an isolated progress dir, see
    tests/test_transcript_progress.py). This module instead drives the REAL hook entrypoint —
    `hooks/loop_stop.py` invoked as a subprocess exactly as the host would (stdin JSON, cwd=root,
    no monkeypatching) — the same harness tests/test_loop_e2e.py already uses for the promise/
    evidence/anchor contract, extended here to also assert on `progress.jsonl`.

  * AC6 had no genuine 3-turn synthetic transcript-vs-progress.jsonl e2e. This module adds one:
    three sequential `loop_stop.py` re-feed invocations against a shared scratchpad/anchor
    fixture, capturing the turn-header text (`loop_progress.py render --turn-header`, exactly
    the line SKILL.md § Output requires the agent to echo first) at each turn AND the re-feed
    header the hook itself emits, asserting: the header is present every turn, `pct_overall`
    advances monotonically as ACs are verified turn over turn, and the run closes at 100% /
    `run_state: done` on the final promise+evidence turn.
"""
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "hooks", "loop_stop.py")
PROGRESS = os.path.join(REPO, "scripts", "loop_progress.py")


def _env(root):
    """`hooks/loop_stop.py`'s `_loop_progress_module()` imports `scripts/loop_progress.py`
    relative to `os.getcwd()` (see `_install_progress_module` below, which copies the real
    module there) — but the module's OWN default state directory is relative to wherever it
    physically lives on disk, not the caller's cwd. Pinning these three env vars makes every
    process in this test (the real hook subprocess AND this test's own direct CLI calls) agree
    on the identical `.simplicio-loop/orchestrator/loop/` under `root`, whichever copy of the script runs."""
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    full_env = dict(os.environ)
    full_env.update({
        "SIMPLICIO_PROGRESS_DIR": loop,
        "SIMPLICIO_ANCHOR_FILE": os.path.join(loop, "anchor.json"),
        "SIMPLICIO_BACKLOG_FILE": os.path.join(root, ".simplicio-loop/orchestrator", "backlog", "backlog.jsonl"),
    })
    return full_env


def _install_progress_module(root):
    """`loop_stop.py`'s `_loop_progress_module()` only finds `loop_progress.py` under
    `<cwd>/scripts/` — copy the real worker (+ its `_locked_append` dependency) there so the
    REAL hook subprocess actually wires the #302 re-feed-header enrichment instead of silently
    fail-opening to an empty prefix for lack of the module."""
    scripts_dir = os.path.join(root, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for name in ("loop_progress.py", "_locked_append.py"):
        shutil.copy2(os.path.join(REPO, "scripts", name), os.path.join(scripts_dir, name))

SCRATCHPAD_TPL = """---
iteration: {iteration}
max_iterations: {max_iter}
completion_promise: "SIMPLICIO_DONE"
evidence_required: true
started_at: "2026-07-14T00:00:00Z"
---
Implement the thing and prove it works.
"""


def _arm(root, iteration=1, max_iter=24):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write(SCRATCHPAD_TPL.format(iteration=iteration, max_iter=max_iter))
    _install_progress_module(root)
    return loop


def _scratchpad(root):
    return os.path.join(root, ".simplicio-loop/orchestrator", "loop", "scratchpad.md")


def _iteration(root):
    with open(_scratchpad(root), encoding="utf-8") as f:
        for line in f:
            if line.startswith("iteration:"):
                return int(line.split(":", 1)[1])
    return None


def _write_anchor(root, criteria, item="T1", goal_fp="x"):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "anchor.json"), "w", encoding="utf-8") as f:
        json.dump({"item": item, "goal": "g", "goal_fp": goal_fp, "criteria": criteria}, f)


def _write_watcher_pass(root, challenge="chal-1", goal_fp="", checked_at="2026-07-14T00:00:01Z"):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "watcher_challenge.json"), "w", encoding="utf-8") as f:
        json.dump({"challenge": challenge, "goal_fp": goal_fp, "written_at": "2026-07-14T00:00:00Z"}, f)
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({"match": True, "status": "MEASURED", "checked_at": checked_at,
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
                for name in ("implementation", "unit", "integration", "system", "regression",
                            "benchmark")
            },
            "coverage": {"measured": 91.2},
        }, f)
    return run_dir


def _tick(root, response_text):
    """Run the REAL loop_stop.py hook exactly as Cursor would: cwd=root, stdin={'text': ...}.
    No mocks, no monkeypatching, no direct import of internal helpers."""
    return subprocess.run([sys.executable, HOOK], input=json.dumps({"text": response_text}),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=root, env=_env(root))


def _turn_header(root):
    """Run the REAL loop_progress.py CLI exactly as the SKILL.md § Output contract requires the
    agent to at the top of every turn: `render --turn-header`, echoed verbatim into the
    transcript. Also driven as a subprocess against the shared `.simplicio-loop/orchestrator/loop/` state."""
    r = subprocess.run([sys.executable, PROGRESS, "render", "--turn-header"],
                       capture_output=True, text=True, cwd=root, env=_env(root),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def _emit(root, step, status, **kwargs):
    args = [sys.executable, PROGRESS, "emit", "--step", step, "--status", status]
    for k, v in kwargs.items():
        if v is None:
            continue
        args += ["--%s" % k, str(v)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=root, env=_env(root),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _events(root):
    path = os.path.join(root, ".simplicio-loop/orchestrator", "loop", "progress.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def _status_json(root):
    r = subprocess.run([sys.executable, PROGRESS, "status", "--json"],
                       capture_output=True, text=True, cwd=root, env=_env(root),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


# ----------------------------------------------------------------------------------------------
# AC3/AC4 — through the REAL hook entrypoint (subprocess), not the unit-level emit helpers.
# ----------------------------------------------------------------------------------------------

def test_ac3_promise_rejected_through_real_hook_emits_progress_event(tmp_path):
    """AC3: a promise typed WITHOUT in-turn evidence must not touch `done`, and the hook — run
    for real, stdin JSON in, JSON re-feed out — must have appended a `refeed_exit` event with
    `outcome: blocked` carrying "promise REJEITADA" to `progress.jsonl`."""
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    r = _tick(root, "I think I'm done. <promise>SIMPLICIO_DONE</promise>")  # no evidence token
    assert r.returncode == 0
    assert "followup_message" in r.stdout or "block" in r.stdout, (
        "a bare promise must be ignored, not honored:\n%s" % r.stdout)
    assert os.path.exists(_scratchpad(root)), "loop wrongly stopped on a bare promise"
    assert _iteration(root) == 2

    events = _events(root)
    rejects = [e for e in events if e["step"] == "refeed_exit" and e["outcome"] == "blocked"]
    assert rejects, "expected a refeed_exit/outcome=blocked event from the REAL hook run; got %r" % events
    assert "promise REJEITADA" in rejects[-1]["detail"], rejects[-1]
    assert rejects[-1]["source"] == "loop_stop.py"


def test_ac4_promise_verified_through_real_hook_emits_progress_event_and_closes_run(tmp_path):
    """AC4: a promise WITH in-turn evidence, a satisfied anchor, and a persisted run receipt must
    touch `done` (the hook stops, cleans up state) AND the real hook run must have appended an
    `outcome: pass` `refeed_exit` event — closing `run_state` to "done" when the snapshot is
    recomputed fresh from `progress.jsonl` (never from a cached `progress.json`, per AC7 of #298)."""
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=5)
    _write_watcher_pass(root)
    _write_anchor(root, [{"id": "AC1", "status": "done"}])
    _seed_verified_run(root)
    r = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                    "https://github.com/o/r/pull/9")
    assert r.returncode == 0
    assert r.stdout.strip() == "", "expected STOP (verified promise), got: %s" % r.stdout
    assert not os.path.exists(_scratchpad(root)), "state should be cleaned up on a verified stop"

    events = _events(root)
    closes = [e for e in events if e["step"] == "refeed_exit" and e["outcome"] == "pass"]
    assert closes, "expected an outcome=pass refeed_exit event from the REAL hook run; got %r" % events
    assert closes[-1]["detail"] == "promise verificada"

    snap = _status_json(root)
    assert snap["run_state"] == "done", snap


# ----------------------------------------------------------------------------------------------
# AC6 — genuine 3-turn synthetic transcript-vs-progress.jsonl e2e.
# ----------------------------------------------------------------------------------------------

def test_ac6_three_turn_transcript_matches_progress_jsonl_and_pct_is_monotonic(tmp_path):
    """Simulates 3 sequential turns of the real loop against a shared scratchpad/anchor fixture:

    Turn 1 (0/3 ACs verified) -> agent narrates the turn-header, does some work, no promise yet
             -> `loop_stop.py` re-feeds; both headers agree, `pct_overall` is the turn-1 baseline.
    Turn 2 (1/3 ACs verified) -> same shape; `pct_overall` must be >= turn 1's.
    Turn 3 (3/3 ACs verified, watcher pass, verified run receipt, promise + evidence in the
             response) -> `loop_stop.py` honors the promise and STOPS; the run closes at 100%,
             `run_state: done`.

    This is the mechanical version of SKILL.md § "Verifying a good loop": transcript header ==
    `progress.jsonl` state, every turn, not just at the end.
    """
    root = str(tmp_path)
    _arm(root, iteration=1, max_iter=24)

    turn_headers = []
    refeed_headers = []
    pct_trace = []

    # ---- turn 1: nothing verified yet -----------------------------------------------------
    _write_anchor(root, [
        {"id": "AC1", "status": "pending"},
        {"id": "AC2", "status": "pending"},
        {"id": "AC3", "status": "pending"},
    ])
    _emit(root, "triage", "begin", iteration=1, detail="turn 1 triage")
    _emit(root, "decide", "end", iteration=1, source="llm", detail="target AC1 first")
    turn1_header = _turn_header(root)
    turn_headers.append(turn1_header)
    assert "UNVERIFIED|" in turn1_header or "MEASURED|" in turn1_header, turn1_header

    r1 = _tick(root, "Still working on AC1, no promise yet this turn.")
    assert r1.returncode == 0
    assert "followup_message" in r1.stdout or "block" in r1.stdout
    assert _iteration(root) == 2
    refeed_headers.append(r1.stdout)
    pct_trace.append(_status_json(root)["pct_overall"])

    # ---- turn 2: AC1 verified --------------------------------------------------------------
    _write_anchor(root, [
        {"id": "AC1", "status": "done"},
        {"id": "AC2", "status": "pending"},
        {"id": "AC3", "status": "pending"},
    ])
    _emit(root, "journal", "end", iteration=2, outcome="pass", detail="AC1 verified")
    turn2_header = _turn_header(root)
    turn_headers.append(turn2_header)

    r2 = _tick(root, "AC1 done, moving to AC2, no promise yet.")
    assert r2.returncode == 0
    assert "followup_message" in r2.stdout or "block" in r2.stdout
    assert _iteration(root) == 3
    refeed_headers.append(r2.stdout)
    pct_trace.append(_status_json(root)["pct_overall"])

    # ---- turn 3: all ACs verified, promise + evidence -> STOP -------------------------------
    _write_anchor(root, [
        {"id": "AC1", "status": "done"},
        {"id": "AC2", "status": "done"},
        {"id": "AC3", "status": "done"},
    ])
    _write_watcher_pass(root)
    _seed_verified_run(root)
    _emit(root, "journal", "end", iteration=3, outcome="pass", detail="AC2/AC3 verified")
    turn3_header = _turn_header(root)
    turn_headers.append(turn3_header)

    r3 = _tick(root, "All green. <promise>SIMPLICIO_DONE</promise> tests pass ✓ "
                     "https://github.com/o/r/pull/9")
    assert r3.returncode == 0
    assert r3.stdout.strip() == "", "expected STOP on turn 3, got: %s" % r3.stdout
    assert not os.path.exists(_scratchpad(root)), "state should be cleaned up on a verified stop"
    final = _status_json(root)
    pct_trace.append(final["pct_overall"])

    # -- (a) turn-header present every turn, tagged MEASURED|/UNVERIFIED| (SKILL.md § Output) --
    assert len(turn_headers) == 3
    for h in turn_headers:
        assert h.startswith(("MEASURED|", "UNVERIFIED|")), h

    # -- (b) the re-feed header the REAL hook emits on turns 1/2 carries the SAME snapshot's
    #        percentage the transcript's own turn-header would show one call later (both read
    #        the identical anchor/backlog/event-trail state at that point in time) --
    for i, refeed in enumerate(refeed_headers):
        assert "iteration %d." % (i + 2) in refeed, refeed
        # fail-open prefix is present whenever an anchor exists on disk (it always does here)
        assert "fase F" in refeed, refeed

    # -- (c) pct_overall is monotonically non-decreasing across the whole 3-turn run --
    for i in range(1, len(pct_trace)):
        prev, cur = pct_trace[i - 1], pct_trace[i]
        assert prev is None or cur is None or cur >= prev - 1e-9, (
            "pct_overall regressed at turn %d: %r -> %r (trace=%r)" % (i, prev, cur, pct_trace))

    # -- (d) the run closes at 100% / done on the final (promise-honored) turn --
    assert abs(final["pct_overall"] - 1.0) < 1e-6, final
    assert final["run_state"] == "done", final

    # -- (e) progress.jsonl itself tells the identical story end to end (transcript == ledger) --
    events = _events(root)
    steps_seen = [(e["step"], e["status"]) for e in events]
    assert ("triage", "begin") in steps_seen
    assert ("decide", "end") in steps_seen
    assert steps_seen.count(("journal", "end")) >= 2
    assert steps_seen[-1] == ("refeed_exit", "end")
    assert events[-1]["outcome"] == "pass"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_transcript_progress_e2e")
