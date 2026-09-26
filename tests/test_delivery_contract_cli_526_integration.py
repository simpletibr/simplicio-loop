"""CLI-level integration tests for the delivery contract (issue #526 Etapa 4):

  * `scripts/task_anchor.py set --delivery FILE` — schema validation at the CLI boundary, freeze
    semantics (needs an anchor to attach to; --force to change), and preservation across an
    ordinary goal re-set.
  * `scripts/pr_evidence.py build --local-report` — auto-triggered by `open_pr: false`, never
    calls any PR API, writes a local file with a clear banner + the compliance section.
  * `scripts/delivery_contract.py` subcommands driven as a real subprocess against a real git repo.

Uses the same subprocess + `SIMPLICIO_ANCHOR_FILE`/env-override isolation pattern as
`tests/test_intake_progress.py` so nothing here ever touches this repo's own `.simplicio-loop/orchestrator/`.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANCHOR_SCRIPT = os.path.join(REPO, "scripts", "task_anchor.py")
PR_EVIDENCE = os.path.join(REPO, "scripts", "pr_evidence.py")
DELIVERY = os.path.join(REPO, "scripts", "delivery_contract.py")

VALID_CONTRACT = {
    "open_pr": False,
    "push_branch": True,
    "allow_new_files_in_repo": False,
    "allow_comments_in_code": False,
    "commit_message_convention": "#<issue> - <type>: <desc>",
}


def _env(tmp_path):
    return {
        "SIMPLICIO_ANCHOR_FILE": str(tmp_path / "anchor.json"),
        "SIMPLICIO_DELIVERY_BASELINE_FILE": str(tmp_path / "delivery_baseline.json"),
        "SIMPLICIO_DELIVERY_REPORT_FILE": str(tmp_path / "delivery_report.md"),
    }


def _run(script, args, cwd, env):
    full_env = dict(os.environ)
    full_env.update(env)
    return subprocess.run([sys.executable, script] + args, capture_output=True, text=True,
                          cwd=cwd, env=full_env, stdin=subprocess.DEVNULL)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "a@b.c")
    git(repo, "config", "user.name", "tester")
    (repo / "existing.txt").write_text("hello\n", encoding="utf-8")
    git(repo, "add", "existing.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


# ----- task_anchor.py set --delivery ----------------------------------------------------------

def test_set_delivery_alone_requires_existing_anchor(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    r = _run(ANCHOR_SCRIPT, ["set", "--delivery", str(delivery_file)], str(tmp_path), env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no task anchor set" in (r.stdout + r.stderr)


def test_set_goal_and_delivery_together_freezes_both(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    r = _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                            "--ac", "Cap mirrored in the UHE block",
                            "--delivery", str(delivery_file)],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["delivery"] == VALID_CONTRACT
    assert (tmp_path / "delivery_baseline.json").exists()


def test_set_delivery_unknown_field_is_blocked(tmp_path):
    env = _env(tmp_path)
    bad = dict(VALID_CONTRACT, unexpected_field=True)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(bad), encoding="utf-8")
    r = _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                            "--ac", "Cap mirrored in the UHE block",
                            "--delivery", str(delivery_file)],
             str(tmp_path), env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "unexpected_field" in (r.stdout + r.stderr)
    assert not (tmp_path / "anchor.json").exists()


def test_set_delivery_alone_attaches_to_existing_anchor(tmp_path):
    env = _env(tmp_path)
    r0 = _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                              "--ac", "Cap mirrored in the UHE block"], str(tmp_path), env)
    assert r0.returncode == 0, r0.stdout + r0.stderr
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    r1 = _run(ANCHOR_SCRIPT, ["set", "--delivery", str(delivery_file)], str(tmp_path), env)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["delivery"] == VALID_CONTRACT
    assert anchor["goal"] == "Ship the fix"  # goal untouched by the delivery-only re-set


def test_changed_delivery_without_force_is_blocked(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                        "--ac", "Cap mirrored", "--delivery", str(delivery_file)],
         str(tmp_path), env)
    changed = dict(VALID_CONTRACT, open_pr=True)
    delivery_file.write_text(json.dumps(changed), encoding="utf-8")
    r = _run(ANCHOR_SCRIPT, ["set", "--delivery", str(delivery_file)], str(tmp_path), env)
    assert r.returncode == 12, r.stdout + r.stderr
    assert "--force" in (r.stdout + r.stderr)
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["delivery"]["open_pr"] is False  # unchanged


def test_changed_delivery_with_force_succeeds(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                        "--ac", "Cap mirrored", "--delivery", str(delivery_file)],
         str(tmp_path), env)
    changed = dict(VALID_CONTRACT, open_pr=True)
    delivery_file.write_text(json.dumps(changed), encoding="utf-8")
    r = _run(ANCHOR_SCRIPT, ["set", "--delivery", str(delivery_file), "--force"],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["delivery"]["open_pr"] is True


def test_delivery_survives_an_ordinary_goal_reset(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                        "--ac", "Cap mirrored", "--delivery", str(delivery_file)],
         str(tmp_path), env)
    # Re-set the SAME goal, adding a second AC, WITHOUT re-passing --delivery.
    r = _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                            "--ac", "Cap mirrored", "--ac", "Second criterion"],
             str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    anchor = json.loads((tmp_path / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["delivery"] == VALID_CONTRACT
    assert len(anchor["criteria"]) == 2


def test_anchor_selftest_stays_green(tmp_path):
    r = subprocess.run([sys.executable, ANCHOR_SCRIPT, "selftest"], capture_output=True,
                       text=True, cwd=REPO, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


# ----- pr_evidence.py build --local-report -----------------------------------------------------

def test_local_report_auto_triggered_by_open_pr_false(tmp_path):
    env = _env(tmp_path)
    delivery_file = tmp_path / "delivery.json"
    delivery_file.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                        "--ac", "Cap mirrored", "--delivery", str(delivery_file)],
         str(tmp_path), env)
    out_file = tmp_path / "report.md"
    r = _run(PR_EVIDENCE, ["build", "--anchor", str(tmp_path / "anchor.json"),
                          "--out", str(out_file)], str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = out_file.read_text(encoding="utf-8")
    assert "Local delivery report" in body
    assert "no PR was opened" in body
    assert "Delivery contract compliance" in body
    assert "MEASURED" in body


def test_build_without_delivery_contract_is_unaffected(tmp_path):
    env = _env(tmp_path)
    _run(ANCHOR_SCRIPT, ["set", "--item", "526", "--goal", "Ship the fix",
                        "--ac", "Cap mirrored"], str(tmp_path), env)
    out_file = tmp_path / "report.md"
    r = _run(PR_EVIDENCE, ["build", "--anchor", str(tmp_path / "anchor.json"),
                          "--out", str(out_file)], str(tmp_path), env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = out_file.read_text(encoding="utf-8")
    assert "Local delivery report" not in body


def test_pr_evidence_selftest_stays_green():
    r = subprocess.run([sys.executable, PR_EVIDENCE, "selftest"], capture_output=True,
                       text=True, cwd=REPO, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


# ----- delivery_contract.py CLI, subprocess-driven --------------------------------------------

def test_cli_validate_rejects_unknown_field(tmp_path):
    bad = dict(VALID_CONTRACT, mystery=1)
    path = tmp_path / "delivery.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    r = _run(DELIVERY, ["validate", "--file", str(path)], str(tmp_path), {})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "mystery" in (r.stdout + r.stderr)


def test_cli_validate_accepts_valid_contract(tmp_path):
    path = tmp_path / "delivery.json"
    path.write_text(json.dumps(VALID_CONTRACT), encoding="utf-8")
    r = _run(DELIVERY, ["validate", "--file", str(path)], str(tmp_path), {})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "valid" in r.stdout


def test_cli_new_file_guard_roundtrip(tmp_path):
    repo = make_repo(tmp_path)
    baseline = tmp_path / "baseline.json"
    r1 = _run(DELIVERY, ["capture-baseline", "--root", str(repo), "--baseline", str(baseline)],
              str(tmp_path), {})
    assert r1.returncode == 0, r1.stdout + r1.stderr
    (repo / "FooTests.cs").write_text("// x\n", encoding="utf-8")
    r2 = _run(DELIVERY, ["check-new-files", "--root", str(repo), "--baseline", str(baseline)],
              str(tmp_path), {})
    assert r2.returncode == 1, r2.stdout + r2.stderr
    payload = json.loads(r2.stdout)
    assert "FooTests.cs" in payload["violations"]


def test_cli_check_commit_message(tmp_path):
    r_ok = _run(DELIVERY, ["check-commit-message", "--message",
                          "#526 - feat: add delivery contract",
                          "--convention", "#<issue> - <type>: <desc>"], str(tmp_path), {})
    assert r_ok.returncode == 0
    r_bad = _run(DELIVERY, ["check-commit-message", "--message", "oops",
                           "--convention", "#<issue> - <type>: <desc>"], str(tmp_path), {})
    assert r_bad.returncode == 1
