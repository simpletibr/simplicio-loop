"""End-to-end coverage for `scripts/autoresearch.py` against a real, throwaway git repo.

`test_worker_selftests.py` proves the pure decision math (decide/plateau_verdict/parse_eval_output)
with no I/O. This file proves the mechanical contract the pure math feeds into actually happens on
disk: mandatory guardrails block a cap-less run, `init` refuses to mutate on main/master and creates
an isolated branch instead, `record` performs the matching scoped git action (commit on keep,
checkout on revert) and NEVER keeps a failing-gate mutation regardless of score, `finish` squashes
kept commits into one and refuses when the winner doesn't pass, and the emitted receipt matches the
`simplicio.savings-event/v1` shape.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "autoresearch.py")

EVAL_PY = """
import json
with open("target.py") as f:
    v = int(f.read().split("=")[1].strip())
print(json.dumps({"gate": "pass" if v >= 0 else "fail", "score": v}))
"""


def _run(args, cwd):
    return subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True,
                          cwd=str(cwd))


def _git(args, cwd):
    return subprocess.run(["git"] + args, capture_output=True, text=True, cwd=str(cwd))


def _init_repo(tmp_path):
    _git(["init", "-q"], tmp_path)
    _git(["config", "user.email", "a@b.c"], tmp_path)
    _git(["config", "user.name", "tester"], tmp_path)
    (tmp_path / "target.py").write_text("x = 1\n")
    (tmp_path / "eval.py").write_text(EVAL_PY)
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "init"], tmp_path)
    return tmp_path


def test_init_requires_iteration_and_budget_caps(tmp_path):
    _init_repo(tmp_path)
    # missing --max-token-budget entirely -> BLOCKED (yool guardrail, exit 2)
    r = _run(["init", "--target", "target.py", "--eval", "python3 eval.py",
              "--max-iterations", "3"], tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "MANDATORY" in r.stdout, r.stdout


def test_init_never_leaves_main_master_and_creates_isolated_branch(tmp_path):
    _init_repo(tmp_path)
    r = _run(["init", "--target", "target.py", "--eval", "python3 eval.py",
              "--branch", "run1", "--max-iterations", "5", "--max-token-budget", "1000",
              "--store", ".simplicio-loop/orchestrator/autoresearch/run1"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MEASURED|baseline gate=pass score=1.0" in r.stdout, r.stdout
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], tmp_path).stdout.strip()
    assert branch not in ("main", "master"), "must never stay on main/master: %r" % branch
    assert branch == "autoresearch/run1"


def test_record_reverts_failing_gate_regardless_of_score(tmp_path):
    _init_repo(tmp_path)
    store = ".simplicio-loop/orchestrator/autoresearch/run2"
    _run(["init", "--target", "target.py", "--eval", "python3 eval.py", "--branch", "run2",
          "--max-iterations", "5", "--max-token-budget", "1000", "--store", store], tmp_path)
    # mutate to a HUGE score that nonetheless fails the correctness gate (v < 0)
    (tmp_path / "target.py").write_text("x = -999\n")
    r = _run(["record", "--iteration", "1", "--store", store], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "decision=revert" in r.stdout, r.stdout
    # the working tree must be restored — the failing mutation is gone
    assert (tmp_path / "target.py").read_text().strip() == "x = 1", \
        "gate-failing mutation was not reverted: %s" % (tmp_path / "target.py").read_text()


def test_record_keeps_and_commits_an_improving_pass(tmp_path):
    _init_repo(tmp_path)
    store = ".simplicio-loop/orchestrator/autoresearch/run3"
    _run(["init", "--target", "target.py", "--eval", "python3 eval.py", "--branch", "run3",
          "--max-iterations", "5", "--max-token-budget", "1000", "--store", store], tmp_path)
    (tmp_path / "target.py").write_text("x = 9\n")
    r = _run(["record", "--iteration", "1", "--store", store], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "decision=keep" in r.stdout, r.stdout
    log = _git(["log", "--oneline"], tmp_path).stdout
    assert "iter 1 score=9.0" in log, log


def test_record_blocks_iteration_beyond_cap(tmp_path):
    _init_repo(tmp_path)
    store = ".simplicio-loop/orchestrator/autoresearch/run4"
    _run(["init", "--target", "target.py", "--eval", "python3 eval.py", "--branch", "run4",
          "--max-iterations", "2", "--max-token-budget", "1000", "--store", store], tmp_path)
    r = _run(["record", "--iteration", "99", "--store", store, "--gate", "pass", "--score", "1"],
             tmp_path)
    assert r.returncode == 12, r.stdout + r.stderr
    assert "exceeds the frozen max_iterations cap" in r.stdout, r.stdout


def test_plateau_and_finish_squash_with_receipt(tmp_path):
    _init_repo(tmp_path)
    store = ".simplicio-loop/orchestrator/autoresearch/run5"
    _run(["init", "--target", "target.py", "--eval", "python3 eval.py", "--branch", "run5",
          "--max-iterations", "10", "--max-token-budget", "1000", "--store", store,
          "--plateau-n", "2"], tmp_path)
    # iteration 1: keep (improves 1 -> 5)
    (tmp_path / "target.py").write_text("x = 5\n")
    _run(["record", "--iteration", "1", "--store", store], tmp_path)
    # iterations 2-3: two reverting failures in a row -> PLATEAU at k=2
    (tmp_path / "target.py").write_text("x = -1\n")
    _run(["record", "--iteration", "2", "--store", store], tmp_path)
    (tmp_path / "target.py").write_text("x = -2\n")
    _run(["record", "--iteration", "3", "--store", store], tmp_path)

    p = _run(["plateau", "--store", store, "--exit-code"], tmp_path)
    assert p.returncode == 10, "expected PLATEAU exit 10, got %d:\n%s" % (p.returncode, p.stdout)
    assert "plateau" in p.stdout.lower(), p.stdout

    f = _run(["finish", "--store", store, "--message", "perf: tune x"], tmp_path)
    assert f.returncode == 0, f.stdout + f.stderr
    assert "kept=1 reverted=2" in f.stdout, f.stdout

    log = _git(["log", "--oneline"], tmp_path).stdout.splitlines()
    assert len(log) == 2, "expected exactly 2 commits after squash (init + squashed): %r" % log
    assert "perf: tune x" in log[0]

    receipt_path = tmp_path / store / "receipt.json"
    assert receipt_path.exists(), "finish must write a receipt"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema"] == "simplicio.savings-event/v1"
    assert receipt["source"] == "autoresearch"
    assert receipt["baseline"]["score"] == 1.0
    assert receipt["actual"]["score"] == 5.0
    assert receipt["kept"] == 1 and receipt["reverted"] == 2


def test_finish_blocks_when_winner_gate_is_not_pass(tmp_path):
    _init_repo(tmp_path)
    store = ".simplicio-loop/orchestrator/autoresearch/run6"
    # baseline eval command always fails the gate (target starts at x = -5)
    (tmp_path / "target.py").write_text("x = -5\n")
    _git(["add", "-A"], tmp_path)
    _git(["commit", "-q", "-m", "bad baseline"], tmp_path)
    _run(["init", "--target", "target.py", "--eval", "python3 eval.py", "--branch", "run6",
          "--max-iterations", "3", "--max-token-budget", "1000", "--store", store], tmp_path)
    f = _run(["finish", "--store", store], tmp_path)
    assert f.returncode == 12, f.stdout + f.stderr
    assert "BLOCKED" in f.stdout, f.stdout


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_autoresearch")
