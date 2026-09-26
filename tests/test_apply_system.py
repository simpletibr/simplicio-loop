"""System test for the plan-once/apply-once hot path (issue #1310): real
CLIs (`python -m simplicio_loop.cli orient --brief`, then `... apply`)
against a temp git repo seeded from bench/llm_ab/fixture -- the same
pure-HTML create/edit scenario the issue's own benchmark uses.

Scenario: orient --brief for 3 tasks (2 parallel creates, 1 dependent
edit of one of them), then one apply covering all three -> PASS + a
receipt. Also: a bad `find` -> BLOCKED, tree unchanged; a stale
repo_state_chain -> BLOCKED, tree unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "bench" / "llm_ab" / "fixture"


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", *args],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120, check=False,
    )


def _survey(repo: Path, task: str) -> None:
    """Every flow goes through Mapper + Fast (issue #1318): run the real
    `orient --brief` so `apply` finds its survey."""
    proc = _run_cli("orient", "--repo", ".", "--task", task, "--brief", "--json", cwd=repo)
    assert proc.returncode == 0, proc.stderr[-2000:]


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("cadastro.html", "login.html"):
        src = FIXTURE_DIR / name
        if src.is_file():
            (repo / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            (repo / name).write_text(f"<!-- SIMPLICIO-PLACEHOLDER: {name} not implemented yet. -->",
                                     encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed from fixture"], cwd=str(repo), check=True)
    return repo


def test_orient_brief_then_apply_two_parallel_creates_and_one_dependent_edit(tmp_path):
    repo = _seed_repo(tmp_path)
    cadastro_placeholder = (repo / "cadastro.html").read_text(encoding="utf-8")
    login_placeholder = (repo / "login.html").read_text(encoding="utf-8")

    brief_proc = _run_cli(
        "orient", "--repo", ".",
        "--task", "Replace cadastro.html placeholder with a real signup form",
        "--task", "Replace login.html placeholder with a real login form",
        "--task", "Add a lang attribute to cadastro.html's html tag",
        "--brief", "--json",
        cwd=repo,
    )
    assert brief_proc.returncode in (0, 2), brief_proc.stderr
    brief = json.loads(brief_proc.stdout)
    assert brief["schema"] == "simplicio.loop-orient-brief/v1"
    assert next(iter(brief)) == "route"
    assert "repo_state_chain" in brief

    ops = {
        "tasks": [
            {
                "id": "create-cadastro",
                "operations": [{
                    "path": "cadastro.html", "find": cadastro_placeholder,
                    "replace": "<html lang=\"en\"><body><form>signup</form></body></html>",
                }],
            },
            {
                "id": "create-login",
                "operations": [{
                    "path": "login.html", "find": login_placeholder,
                    "replace": "<html><body><form>login</form></body></html>",
                }],
            },
            {
                "id": "edit-cadastro-lang",
                "depends_on": ["create-cadastro"],
                "operations": [{
                    "path": "cadastro.html", "find": "<html lang=\"en\">",
                    "replace": "<html lang=\"en-US\">",
                }],
            },
        ],
        "repo_state_chain": brief["repo_state_chain"],
    }
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps(ops), encoding="utf-8")

    apply_proc = _run_cli("apply", str(ops_path), "--repo", ".", "--json", cwd=repo)
    result = json.loads(apply_proc.stdout)
    assert result["status"] == "PASS", result
    assert apply_proc.returncode == 0
    assert {t["id"]: t["status"] for t in result["tasks"]} == {
        "create-cadastro": "PASS", "create-login": "PASS", "edit-cadastro-lang": "PASS",
    }
    receipt_path = Path(result["receipt_path"])
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert "en-US" in (repo / "cadastro.html").read_text(encoding="utf-8")
    assert "login" in (repo / "login.html").read_text(encoding="utf-8")


def test_apply_bad_find_is_blocked_and_tree_unchanged(tmp_path):
    repo = _seed_repo(tmp_path)
    before = (repo / "cadastro.html").read_text(encoding="utf-8")
    ops = {"tasks": [{"id": "t1", "operations": [
        {"path": "cadastro.html", "find": "THIS TEXT DOES NOT EXIST", "replace": "x"},
    ]}]}
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps(ops), encoding="utf-8")
    _survey(repo, "Edit cadastro.html")

    proc = _run_cli("apply", str(ops_path), "--repo", ".", "--json", cwd=repo)
    result = json.loads(proc.stdout)
    assert result["status"] == "BLOCKED"
    assert proc.returncode == 2
    assert result["reason_code"] == "validation_failed"
    assert (repo / "cadastro.html").read_text(encoding="utf-8") == before
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo),
                            capture_output=True, text=True, check=True)
    tracked_dirty = [line for line in status.stdout.splitlines() if not line.strip().startswith("??")]
    assert tracked_dirty == []


def test_apply_ops_json_at_repo_root_is_not_treated_as_stale(tmp_path):
    """issue #1318: brief -> write ops.json AT THE REPO ROOT (not /tmp) ->
    apply -> PASS. Regression for the real hot-path bug: an untracked
    ops.json inside the repo used to change `repo_state_chain`'s tree hash
    between `orient --brief` and `apply`, blocking a run that touched
    nothing else."""
    repo = _seed_repo(tmp_path)
    before = (repo / "cadastro.html").read_text(encoding="utf-8")

    brief_proc = _run_cli(
        "orient", "--repo", ".", "--task", "Add a lang attribute to cadastro.html's html tag",
        "--brief", "--json", cwd=repo,
    )
    brief = json.loads(brief_proc.stdout)

    ops = {
        "tasks": [{"id": "t1", "operations": [
            {"path": "cadastro.html", "find": before,
             "replace": "<html lang=\"en\"><body><form>signup</form></body></html>"},
        ]}],
        "repo_state_chain": brief["repo_state_chain"],
    }
    ops_path = repo / "ops.json"
    ops_path.write_text(json.dumps(ops), encoding="utf-8")

    apply_proc = _run_cli("apply", "ops.json", "--repo", ".", "--json", cwd=repo)
    result = json.loads(apply_proc.stdout)
    assert result["status"] == "PASS", result
    assert apply_proc.returncode == 0


def test_apply_stale_repo_state_chain_is_blocked_and_tree_unchanged(tmp_path):
    repo = _seed_repo(tmp_path)
    before = (repo / "cadastro.html").read_text(encoding="utf-8")
    ops = {
        "tasks": [{"id": "t1", "operations": [
            {"path": "cadastro.html", "find": before, "replace": "<html>changed</html>"},
        ]}],
        "repo_state_chain": {"head": "0" * 40, "dirty_status_hash": "0" * 64, "tree_hash": "0" * 64},
    }
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps(ops), encoding="utf-8")
    _survey(repo, "Edit cadastro.html")

    proc = _run_cli("apply", str(ops_path), "--repo", ".", "--json", cwd=repo)
    result = json.loads(proc.stdout)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "stale_mapper_generation"
    assert proc.returncode == 2
    assert (repo / "cadastro.html").read_text(encoding="utf-8") == before


def test_apply_without_orient_brief_is_blocked_and_tree_unchanged(tmp_path):
    """No Mapper + Fast survey -> apply refuses (issue #1318)."""
    repo = _seed_repo(tmp_path)
    before = (repo / "cadastro.html").read_text(encoding="utf-8")
    ops = {"tasks": [{"id": "t1", "operations": [
        {"path": "cadastro.html", "find": before, "replace": "<html>x</html>"}]}]}
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps(ops), encoding="utf-8")
    proc = _run_cli("apply", str(ops_path), "--repo", ".", "--json", cwd=repo)
    result = json.loads(proc.stdout)
    assert result["reason_code"] == "mapper_fast_provenance_missing"
    assert proc.returncode == 2
    assert (repo / "cadastro.html").read_text(encoding="utf-8") == before
