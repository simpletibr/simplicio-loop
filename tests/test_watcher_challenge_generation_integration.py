import json
import os
import subprocess
import sys


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHER = os.path.join(REPO, "scripts", "watcher_verify.py")


def _run(cmd, cwd, env=None):
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
        stdin=subprocess.DEVNULL,
        env=full_env,
    )


def test_issue_generates_deterministic_anchor_bound_challenge(tmp_path):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio-loop/orchestrator" / "loop"
    loop.mkdir(parents=True)
    (loop / "anchor.json").write_text(json.dumps({
        "goal_fp": "goal-1",
        "criteria": [
            {"id": "AC2", "status": "pending"},
            {"id": "AC1", "status": "done"},
        ],
    }), encoding="utf-8")

    first = _run([sys.executable, WATCHER, "issue"], str(repo), env={"SIMPLICIO_LOOP_REPO": str(repo)})
    assert first.returncode == 0, first.stdout + first.stderr
    payload1 = json.loads((loop / "watcher_challenge.json").read_text(encoding="utf-8"))
    assert payload1["schema"] == "simplicio.anchor-challenge/v1"
    assert payload1["mode"] == "anchor-derived"
    assert "sorted criterion ids/statuses" in payload1["challenge_derivation"]

    first_challenge = payload1["challenge"]
    payload1_copy = {k: v for k, v in payload1.items() if k != "written_at"}

    second = _run([sys.executable, WATCHER, "issue"], str(repo), env={"SIMPLICIO_LOOP_REPO": str(repo)})
    assert second.returncode == 0, second.stdout + second.stderr
    payload2 = json.loads((loop / "watcher_challenge.json").read_text(encoding="utf-8"))
    payload2_copy = {k: v for k, v in payload2.items() if k != "written_at"}

    assert payload2["challenge"] == first_challenge
    assert payload2_copy == payload1_copy

    (loop / "anchor.json").write_text(json.dumps({
        "goal_fp": "goal-1",
        "criteria": [
            {"id": "AC1", "status": "done"},
            {"id": "AC2", "status": "done"},
        ],
    }), encoding="utf-8")
    third = _run([sys.executable, WATCHER, "issue"], str(repo), env={"SIMPLICIO_LOOP_REPO": str(repo)})
    assert third.returncode == 0, third.stdout + third.stderr
    payload3 = json.loads((loop / "watcher_challenge.json").read_text(encoding="utf-8"))
    assert payload3["challenge"] != first_challenge


def test_anchor_bound_challenge_stays_unverified_without_independent_receipt(tmp_path):
    repo = tmp_path / "repo"
    loop = repo / ".simplicio-loop/orchestrator" / "loop"
    loop.mkdir(parents=True)
    run_dir = repo / ".simplicio-loop/orchestrator" / "runs" / "demo"
    run_dir.mkdir(parents=True)

    (loop / "anchor.json").write_text(json.dumps({
        "goal_fp": "goal-1",
        "criteria": [{"id": "AC1", "status": "done"}],
    }), encoding="utf-8")
    issued = _run([sys.executable, WATCHER, "issue"], str(repo), env={"SIMPLICIO_LOOP_REPO": str(repo)})
    assert issued.returncode == 0, issued.stdout + issued.stderr

    (run_dir / "evidence-receipt.json").write_text(json.dumps({
        "schema": "simplicio.evidence-receipt/v1",
        "run_id": "demo",
        "status": "VERIFIED",
        "run": {"task_contract_hash": "hash1", "plan_hash": "hash2", "commit_sha": "", "diff_hash": ""},
        "criteria": [{"id": "AC1", "verification_state": "verified", "proof_refs": ["proof-1"]}],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                    "scenario_verified": 1, "rule_total": 0, "rule_verified": 0},
        "checks": [],
    }), encoding="utf-8")

    verified = _run([sys.executable, WATCHER, "verify"], str(repo),
                    env={"SIMPLICIO_LOOP_REPO": str(repo), "SIMPLICIO_RUN_DIR": str(run_dir)})
    assert verified.returncode == 0, verified.stdout + verified.stderr
    receipt = json.loads((loop / "watcher_state.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "UNVERIFIED"
    assert receipt["match"] is False
    assert "independent watcher receipt missing" in receipt["reported"]

