"""End-to-end tests for scripts/issue_eval.py run_case on a local 2-commit repo."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue_eval.py"

spec = importlib.util.spec_from_file_location("issue_eval", SCRIPT)
issue_eval = importlib.util.module_from_spec(spec)
sys.modules["issue_eval"] = issue_eval
spec.loader.exec_module(issue_eval)

TITLE = 'fix "quoted" it\'s $HOME title'

ENGINE = '''
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--repo")
p.add_argument("--task")
p.add_argument("--verify")
p.add_argument("--record")
p.add_argument("--status", default="ok")
p.add_argument("--tokens", action="store_true")
p.add_argument("--garbage", action="store_true")
a = p.parse_args()
rec = {
    "repo": a.repo, "task": a.task, "verify": a.verify, "cwd": os.getcwd(),
    "repo_exists": os.path.isdir(a.repo),
    "a": open(os.path.join(a.repo, "a.txt")).read() if os.path.exists(os.path.join(a.repo, "a.txt")) else None,
    "b_exists": os.path.exists(os.path.join(a.repo, "b.txt")),
}
json.dump(rec, open(a.record, "w"))
if a.garbage:
    print("not json at all")
else:
    out = {"schema": "simplicio.turbo-run/v1", "status": a.status}
    if a.tokens:
        out.update(tokens_in=11, tokens_out=7)
    print("engine log line")
    print(json.dumps(out))
'''


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def src_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q")
    git(src, "config", "user.email", "t@t")
    git(src, "config", "user.name", "t")
    (src / "a.txt").write_text("first")
    git(src, "add", ".")
    git(src, "commit", "-qm", "one")
    base = git(src, "rev-parse", "HEAD")
    (src / "b.txt").write_text("second")
    git(src, "add", ".")
    git(src, "commit", "-qm", "two")
    return src, base


@pytest.fixture
def engine(tmp_path):
    script = tmp_path / "engine.py"
    script.write_text(ENGINE)
    record = tmp_path / "record.json"

    def cmd(extra=""):
        return (
            f"{sys.executable} {script} --repo {{repo}} --task {{task}} "
            f"--verify {{verify}} --record {record} {extra}"
        )

    return cmd, record


def make_case(base, verify="grep -q first a.txt"):
    case = {
        "repo": "owner/name",
        "issue_number": 1,
        "pr_number": 2,
        "issue_title": TITLE,
        "base_commit": base,
        "size": "small",
        "source": "issue",
    }
    if verify is not None:
        case["verify_command"] = verify
    return case


def run(case, cmd, src, **kw):
    async def go():
        return await issue_eval.run_case(
            case, cmd, asyncio.Semaphore(1), ROOT, repo_source=str(src), **kw
        )

    return asyncio.run(go())


def test_checkout_at_base_commit(src_repo, engine):
    src, base = src_repo
    cmd, record = engine
    run(make_case(base), cmd(), src)
    rec = json.loads(record.read_text())
    assert rec["a"] == "first"
    assert rec["b_exists"] is False


def test_placeholders_substituted(src_repo, engine):
    src, base = src_repo
    cmd, record = engine
    run(make_case(base, verify="grep -q first a.txt"), cmd(), src)
    rec = json.loads(record.read_text())
    assert rec["repo"] == rec["cwd"]
    assert rec["repo"] != "owner/name"
    assert rec["repo_exists"] is True
    assert rec["task"] == TITLE
    assert rec["verify"] == "grep -q first a.txt"


def test_ok_and_verify_pass_is_success(src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    r = run(make_case(base), cmd(), src)
    assert r.status == "success"
    assert r.engine_status == "ok"
    assert r.verify_result == "pass"
    assert r.wall_time_s is not None and r.wall_time_s > 0


def test_ok_but_verify_fails_is_failure(src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    r = run(make_case(base, verify="false"), cmd(), src)
    assert r.status == "failed"
    assert r.engine_status == "ok"
    assert r.verify_result == "fail"


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_engine_not_ok_is_failure_even_if_verify_would_pass(src_repo, engine, status):
    src, base = src_repo
    cmd, _ = engine
    r = run(make_case(base, verify="true"), cmd(f"--status {status}"), src)
    assert r.status == "failed"
    assert r.engine_status == status
    assert r.verify_result == "UNVERIFIED"
    assert status in r.error


def test_non_json_output_is_failure_with_reason(src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    r = run(make_case(base, verify="true"), cmd("--garbage"), src)
    assert r.status == "failed"
    assert "turbo-run/v1" in r.error
    assert r.verify_result == "UNVERIFIED"


def test_clone_failure_is_failure_and_engine_not_run(tmp_path, src_repo, engine):
    _, base = src_repo
    cmd, record = engine
    r = run(make_case(base), cmd(), tmp_path / "does-not-exist")
    assert r.status == "failed"
    assert "clone" in r.error
    assert r.verify_result == "UNVERIFIED"
    assert not record.exists()


def test_checkout_failure_is_failure_and_engine_not_run(src_repo, engine):
    src, _ = src_repo
    cmd, record = engine
    r = run(make_case("0" * 40), cmd(), src)
    assert r.status == "failed"
    assert "checkout" in r.error
    assert not record.exists()


def test_missing_verify_command_is_unverified_not_success(src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    r = run(make_case(base, verify=None), cmd(), src)
    assert r.status == "unverified"
    assert r.verify_result == "UNVERIFIED"


def test_default_repo_source_is_a_clonable_url():
    assert issue_eval.DEFAULT_REPO_SOURCE == "https://github.com/{repo}.git"


def _write_cases(tmp_path, base):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"schema": "simplicio.issue-eval/v1", "cases": [make_case(base)]}))
    return cases


def _cli(tmp_path, src, base, cmd):
    out = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable, str(SCRIPT), "--cases", str(_write_cases(tmp_path, base)),
            "--engine", cmd, "--repo-source", str(src), "--out", str(out),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.read_text())


def test_report_has_measured_wall_time_and_unverified_tokens(tmp_path, src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    report = _cli(tmp_path, src, base, cmd())
    task = report["tasks"][0]
    assert task["wall_ms"] > 0
    assert task["success"] is True
    assert task["resources"]["input_tokens"] is None
    assert task["resources"]["output_tokens"] is None
    assert task["tokens_status"] == "UNVERIFIED"
    assert report["consolidated"]["total_input_tokens"] is None
    assert "tokens_*" in report["unverified_fields"]
    assert report["consolidated"]["success_rate"] == 1.0


def test_report_tokens_measured_when_engine_reports_them(tmp_path, src_repo, engine):
    src, base = src_repo
    cmd, _ = engine
    report = _cli(tmp_path, src, base, cmd("--tokens"))
    task = report["tasks"][0]
    assert task["resources"]["input_tokens"] == 11
    assert task["resources"]["output_tokens"] == 7
    assert task["tokens_status"] == "MEASURED"
    assert report["consolidated"]["total_input_tokens"] == 11
    assert "tokens_*" not in report["unverified_fields"]
