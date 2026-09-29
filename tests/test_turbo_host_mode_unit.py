"""3.45.1 host mode: the invoking model plans, dev-cli applies. No provider call and no key."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    state = repo / ".simplicio-loop"
    state.mkdir(exist_ok=True)
    project = {"schema": "simplicio.project-map/v1", "product": "shop-utils",
               "files": [{"path": "inventory.py", "symbols": ["Inventory"]},
                         {"path": "shop/report.py", "symbols": ["summary"]},
                         {"path": "shop/invoice.py", "symbols": ["invoice_total"]}]}
    (state / "project-map.json").write_text(json.dumps(project), encoding="utf-8")
    return repo


def _solution_ops(repo: Path, rels):
    ops = []
    for rel in rels:
        old = (repo / rel).read_text(encoding="utf-8") if (repo / rel).is_file() else ""
        ops.append({"path": rel, "find": old, "replace": (SOLUTION / rel).read_text(encoding="utf-8")})
    return ops


@pytest.fixture
def host(monkeypatch):
    """Host mode never touches the provider, even when a key is present in the environment."""
    def boom(*args, **kwargs):
        raise AssertionError("host mode called the provider")

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-must-be-ignored")
    monkeypatch.setattr(turbo_provider, "complete", boom)
    monkeypatch.setattr(turbo_provider, "require_key", boom)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root, **kwargs: None)


def _request(repo: Path, capsys, *extra: str):
    rc = cli_main(["turbo", "--repo", str(repo), *extra])
    return rc, json.loads(capsys.readouterr().out)


def test_the_request_carries_the_map_slice_the_task_and_the_file_and_calls_no_provider(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    rc, out = _request(repo, capsys, "--task", "Fix the two bugs in inventory.py.", "--verify", "pytest -q")
    assert rc == 0
    assert list(out) == ["schema", "status", "mode", "repo", "plan_path", "apply", "format", "tasks", "prompt"]
    assert out["schema"] == "simplicio.turbo-request/v1" and out["status"] == "needs_plan" and out["mode"] == "host"
    assert out["plan_path"] == ".simplicio-loop/turbo/plan.json"
    assert out["apply"] == (f"simplicio-loop turbo --repo {shlex.quote(str(repo.resolve()))} "
                            "--apply .simplicio-loop/turbo/plan.json --verify 'pytest -q'")
    assert out["format"] == {"operations": [{"path": "<repo-relative>", "find": "<exact text that occurs once; "
                                             "empty creates the file>", "replace": "<new text>"}]}
    assert out["tasks"] == [{"index": 1, "text": "Fix the two bugs in inventory.py.",
                             "target": "inventory.py", "context": []}]
    prompt = out["prompt"]
    assert "Current inventory.py:\n" + (FIXTURE / "inventory.py").read_text(encoding="utf-8") in prompt
    assert "Mapper project map:" in prompt and "shop/report.py" not in prompt  # one task: only its slice of the map
    assert json.loads((repo / ".simplicio-loop" / "turbo" / "request.json").read_text(encoding="utf-8")) == out


def test_the_request_without_verify_prints_a_plain_apply_command(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--task", "Fix inventory.py")
    assert rc == 0 and out["apply"].endswith("--apply .simplicio-loop/turbo/plan.json")
    assert "--verify" not in out["apply"]


def test_the_request_without_a_task_is_blocked(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys)
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_no_tasks" and out["mode"] == "host"


def test_host_flow_end_to_end_on_the_hard_fixture(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    verify = f'"{sys.executable}" "{HIDDEN}" --stage 1 && "{sys.executable}" "{HIDDEN}" --stage 2'
    rc, request = _request(repo, capsys, "--task", "Create pricing.py with order_total as specified.",
                           "--task", "Fix the two bugs in inventory.py.", "--verify", verify)
    assert rc == 0 and len(request["tasks"]) == 2
    (repo / request["plan_path"]).write_text(
        json.dumps({"operations": _solution_ops(repo, ["pricing.py", "inventory.py"])}), encoding="utf-8")
    rc = cli_main(shlex.split(request["apply"])[1:])  # the printed command runs as printed
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert out["schema"] == "simplicio.turbo-run/v1" and out["mode"] == "host" and out["status"] == "ok"
    assert out["applied"] == ["pricing.py", "inventory.py"] and out["failed"] == []
    assert out["verify"]["passed"] is True


def test_a_find_that_does_not_match_fails_with_the_reason_and_an_excerpt(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    plan = repo / "plan.json"
    plan.write_text(json.dumps({"operations": [
        {"path": "inventory.py", "find": "class Inventory:\n    def nothing(self):\n        pass\n", "replace": "x\n"}]}),
        encoding="utf-8")
    rc, out = _request(repo, capsys, "--apply", str(plan))
    assert rc == 1 and out["status"] == "failed" and out["mode"] == "host" and out["applied"] == []
    (entry,) = out["failed"]
    assert entry["path"] == "inventory.py" and entry["reason"]
    assert "class Inventory:" in entry["excerpt"] and len(entry["excerpt"]) <= 700
    assert out["verify"] is None
    assert (repo / "inventory.py").read_text(encoding="utf-8") == (FIXTURE / "inventory.py").read_text(encoding="utf-8")


def test_a_failing_verify_reports_failed_with_its_output(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    (repo / "plan.json").write_text(json.dumps({"operations": [
        {"path": "notes.txt", "find": "", "replace": "hello\n"}]}), encoding="utf-8")
    rc, out = _request(repo, capsys, "--apply", "plan.json", "--verify", f'"{sys.executable}" -c "print(1); raise SystemExit(3)"')
    assert rc == 1 and out["status"] == "failed" and out["applied"] == ["notes.txt"]
    assert out["verify"]["passed"] is False and out["verify"]["returncode"] == 3
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "hello\n"


@pytest.mark.parametrize("text, reason", [
    ("not json at all", "turbo_plan_malformed"),
    ('{"operations": []}', "turbo_plan_malformed"),
    ('{"operations": [{"path": 3, "find": "", "replace": "x"}]}', "turbo_plan_malformed"),
    ('{"operations": [{"find": "", "replace": "x"}]}', "turbo_plan_malformed"),
])
def test_a_malformed_plan_is_failed_with_a_typed_reason(tmp_path, host, capsys, text, reason):
    repo = _seed(tmp_path)
    (repo / "plan.json").write_text(text, encoding="utf-8")
    rc, out = _request(repo, capsys, "--apply", "plan.json")
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == reason and out["detail"]


def test_a_missing_plan_is_failed_with_a_typed_reason(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--apply", ".simplicio-loop/turbo/plan.json")
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_missing"


def test_the_provider_is_an_explicit_opt_in_and_needs_its_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc, out = _request(_seed(tmp_path), capsys, "--provider", "openrouter", "--task", "fix inventory.py")
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_provider_key_missing"


def test_a_key_in_the_environment_does_not_turn_the_provider_on(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--task", "fix inventory.py")
    assert rc == 0 and out["status"] == "needs_plan"  # `host` makes any provider call raise


def test_turbo_help_describes_host_mode_and_the_opt_in_provider(capsys):
    with pytest.raises(SystemExit):
        cli_main(["turbo", "--help"])
    text = capsys.readouterr().out
    assert "--apply" in text and "--provider" in text and "needs_plan" in text
    assert "OPENROUTER_API_KEY" in text and "deepseek/deepseek-v4.1-flash" in text
