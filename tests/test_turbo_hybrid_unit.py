"""3.47.0 hybrid mode: `simplicio-loop "<task>"` runs the whole turbo engine, and its model calls go through the host's CLI.

The host CLI is a fake `opencode` on PATH that prints output recorded from the real one. Every way the hybrid backend can be
unavailable is a typed cause, and the same invocation then prints the two-command host-mode request, so the invoking agent
carries on with no user action.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host_cli_fakes as fakes  # noqa: E402

from simplicio_loop import turbo_host_llm as hl  # noqa: E402
from simplicio_loop import turbo_provider  # noqa: E402
from simplicio_loop.cli_impl import main as cli_main  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_hybrid_detection")
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"
TASK = "Fix the two bugs in inventory.py."
VERIFY = f'"{sys.executable}" "{HIDDEN}" --stage 2'


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    state = repo / ".simplicio-loop"
    state.mkdir(exist_ok=True)
    (state / "project-map.json").write_text(json.dumps({"schema": "simplicio.project-map/v1", "files": [
        {"path": "inventory.py", "symbols": ["Inventory"]}]}), encoding="utf-8")
    return repo


@pytest.fixture(autouse=True)
def _no_mapper_no_provider(monkeypatch):
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root, **kwargs: None)

    def boom(*args, **kwargs):
        raise AssertionError("hybrid and host mode never call the provider")

    monkeypatch.setattr(turbo_provider, "complete", boom)


def _solution_plan(repo: Path) -> str:
    old = (repo / "inventory.py").read_text(encoding="utf-8")
    return json.dumps({"operations": [{"path": "inventory.py", "find": old,
                                       "replace": (SOLUTION / "inventory.py").read_text(encoding="utf-8")}]})


def _on_opencode(monkeypatch, bin_dir: Path | None, tmp_path: Path | None = None) -> None:
    """Run as OpenCode's bash tool would: its env markers, and the fake opencode first on PATH.

    Without ``bin_dir`` there is no opencode at all: PATH holds git and nothing else.
    """
    monkeypatch.setenv("OPENCODE", "1")
    monkeypatch.setenv("OPENCODE_PID", "4242")
    monkeypatch.setenv("AGENT", "1")
    if bin_dir is not None:
        monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
        return
    only_git = Path(tmp_path) / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(only_git))


def _run(repo: Path, capsys, *args: str):
    rc = cli_main(["turbo", "--repo", str(repo), *args])
    return rc, json.loads(capsys.readouterr().out)


def _assert_host_request(out: dict, cause: str, tasks: list[str]) -> None:
    assert out["schema"] == "simplicio.turbo-request/v1" and out["status"] == "needs_plan" and out["mode"] == "host"
    assert out["reason"] == f"hybrid_unavailable: {cause}"
    assert out["tasks"] == tasks and out["apply"].startswith("simplicio-loop turbo --repo ") and "--apply -" in out["apply"]
    assert out["format"] and out["rules"] and "files" in out and "map" in out


# --- the one command ------------------------------------------------------------------------------------------------------

def test_one_command_runs_survey_plan_apply_and_verify_through_the_host_cli(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=_solution_plan(repo), cost=0.0006)
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0, out
    assert out["schema"] == "simplicio.turbo-run/v1" and out["status"] == "ok"
    assert out["mode"] == "hybrid" and out["llm"] == "opencode"
    assert out["tasks"] == 1 and out["model_calls"] == 1 and out["retries"] == 0
    assert out["applied"] == [1] and out["failed"] == [] and out["verify"]["passed"] is True
    assert out["tokens"] == {"prompt_tokens": 970, "cached_tokens": 0, "completion_tokens": 255, "reasoning_tokens": 0}
    assert out["cost_usd"] == 0.0006 and out["cost_basis"] == "host-reported"
    assert out["reasoning_off_for"] == ["openrouter/deepseek/deepseek-v4.1-flash"]
    assert isinstance(out["wall_s"], float) and out["budget_s"] == 100.0
    assert [c["prompt_tokens"] for c in out["calls"]] == [970] and out["calls"][0]["latency_s"] >= 0
    assert "apply" not in out and "files" not in out  # nothing is left for the host to do
    assert (repo / "inventory.py").read_text(encoding="utf-8") == (SOLUTION / "inventory.py").read_text(encoding="utf-8")
    (seen,) = fakes.log(bin_dir, "opencode")  # one model call, through the host's own CLI
    assert "Current inventory.py:" in seen["stdin"] and TASK in seen["stdin"]
    assert seen["env"]["SIMPLICIO_TURBO_NESTED"] == "1" and seen["cwd"] == str(repo.resolve())
    agent = json.loads((repo / ".simplicio-loop" / "host-llm" / "opencode.json").read_text(encoding="utf-8"))["agent"]
    assert agent["simplicio-planner"]["permission"] == {"*": "deny"}


def test_the_short_form_is_the_same_command(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=_solution_plan(repo))
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.chdir(repo)
    rc = cli_main([TASK, "--verify", VERIFY])  # simplicio-loop "<task>" --verify "<tests>"
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["mode"] == "hybrid" and out["status"] == "ok" and out["verify"]["passed"] is True


def test_a_repair_after_a_failed_verify_is_one_more_host_call(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    old = (repo / "inventory.py").read_text(encoding="utf-8")
    first = json.dumps({"operations": [{"path": "inventory.py", "find": old, "replace": old + "# looked at\n"}]})
    second = json.dumps({"operations": [{"path": "inventory.py", "find": old + "# looked at\n",
                                         "replace": (SOLUTION / "inventory.py").read_text(encoding="utf-8")}]})
    bin_dir = fakes.install(tmp_path, "opencode", calls=[{"mode": "opencode", "reply": first}, {"mode": "opencode", "reply": second}])
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0, out
    assert out["status"] == "ok" and out["model_calls"] == 2 and out["verify"]["passed"] is True
    assert out["verify_retry"] == {"attempted": True, "applied": True, "reason": None, "passed": True}
    assert "The tests failed after your plan was applied" in fakes.log(bin_dir, "opencode")[1]["stdin"]  # the repair prompt


def test_a_verify_that_still_fails_after_the_repair_is_failed_and_hands_the_host_what_it_needs(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    old = (repo / "inventory.py").read_text(encoding="utf-8")
    touched = json.dumps({"operations": [{"path": "inventory.py", "find": old, "replace": old + "# looked at\n"}]})
    again = json.dumps({"operations": [{"path": "inventory.py", "find": old + "# looked at\n", "replace": old + "# again\n"}]})
    bin_dir = fakes.install(tmp_path, "opencode", calls=[{"mode": "opencode", "reply": touched}, {"mode": "opencode", "reply": again}])
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 1 and out["status"] == "failed" and out["mode"] == "hybrid"
    assert out["verify"]["passed"] is False and out["verify_retry"]["passed"] is False
    assert out["apply"].startswith("simplicio-loop turbo --repo ") and "--verify" in out["apply"] and out["apply"].endswith("\nPLAN")
    assert out["files"]["inventory.py"].endswith("# again\n")  # the current text, so the host can fix it in one call


def test_a_plan_the_model_gets_wrong_twice_is_handed_to_the_host(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    wrong = json.dumps({"operations": [{"path": "inventory.py", "find": "NOT IN THE FILE", "replace": "x"}]})
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=wrong)
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0 and len(fakes.log(bin_dir, "opencode")) == 2  # one retry with dev-cli's error, as in provider mode
    _assert_host_request(out, "plan_rejected", [TASK])
    assert out["detail"] and "applied" not in out
    assert (repo / "inventory.py").read_text(encoding="utf-8") == (FIXTURE / "inventory.py").read_text(encoding="utf-8")
    assert f"--verify {shlex.quote(VERIFY)}" in out["apply"]


# --- every way the hybrid backend can be unavailable is a typed cause and the host-mode request -------------------------

def _dead(name: str, **call):
    return {"stdout_file": str(fakes.FIXTURES / name), "exit": 1, **call}


@pytest.mark.parametrize("cause, setup", [
    ("host_auth", lambda tp, mp: fakes.install(tp, "opencode", **_dead("opencode_error_auth.jsonl"))),
    ("network", lambda tp, mp: fakes.install(tp, "opencode", **_dead("opencode_error_network.jsonl"))),
    ("host_http", lambda tp, mp: fakes.install(tp, "opencode", stdout=json.dumps(
        {"type": "error", "error": {"name": "APIError", "data": {"message": "Service Unavailable", "statusCode": 503}}}), exit=1)),
    ("host_error", lambda tp, mp: fakes.install(tp, "opencode", stdout="", stderr="kaboom", exit=3)),
    ("host_timeout", lambda tp, mp: (mp.setenv(hl.CALL_TIMEOUT_ENV, "1"),
                                     fakes.install(tp, "opencode", mode="opencode", reply="{}", sleep=30))[1]),
])
def test_a_host_cli_that_fails_gives_the_host_mode_request_with_the_cause(tmp_path, monkeypatch, capsys, cause, setup):
    repo = _seed(tmp_path)
    _on_opencode(monkeypatch, setup(tmp_path, monkeypatch))
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0
    _assert_host_request(out, cause, [TASK])
    assert out["detail"] and "applied" not in out
    assert out["files"] == {"inventory.py": (FIXTURE / "inventory.py").read_text(encoding="utf-8")}
    assert (repo / "inventory.py").read_text(encoding="utf-8") == (FIXTURE / "inventory.py").read_text(encoding="utf-8")


def test_no_host_detected_gives_the_host_mode_request(tmp_path, monkeypatch, capsys):
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 0 and out["reason"] == "hybrid_unavailable: no_host_detected" and "detail" not in out
    assert list(out) == ["schema", "status", "mode", "reason", "tasks", "map", "files", "format", "rules", "apply"]


def test_the_host_cli_missing_from_path_gives_the_host_mode_request(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    _on_opencode(monkeypatch, None, tmp_path)
    rc, out = _run(repo, capsys, "--task", TASK)
    assert rc == 0
    _assert_host_request(out, "host_cli_missing", [TASK])
    assert out["detail"] == "opencode is not on PATH"


def test_no_network_is_found_by_the_probe_before_any_call_is_made(tmp_path, monkeypatch, capsys):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply="{}")
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.setenv(hl.PROBE_ENV, "1")
    monkeypatch.setattr(hl, "probe_network", lambda targets, budget=2.0, environ=None: False)
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 0
    _assert_host_request(out, "network", [TASK])
    assert fakes.log(bin_dir, "opencode") == []  # the CLI was never started


def test_a_host_that_may_keep_its_tools_falls_back_to_host_mode_until_it_is_named(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hl, "ancestor_names", lambda limit=12: ["hermes"])
    bin_dir = fakes.install(tmp_path, "hermes", mode="text", reply="{}")
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 0
    _assert_host_request(out, "opt_in", [TASK])
    assert "SIMPLICIO_TURBO_LLM=hermes" in out["detail"] and fakes.log(bin_dir, "hermes") == []  # the CLI was never started


def test_a_forced_host_mode_skips_the_hybrid_backend(tmp_path, monkeypatch, capsys):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply="{}")
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.setenv(hl.LLM_ENV, "host")
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 0
    _assert_host_request(out, "forced_host", [TASK])
    assert fakes.log(bin_dir, "opencode") == []


def test_a_nested_simplicio_loop_never_starts_the_hybrid_backend_again(tmp_path, monkeypatch, capsys):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply="{}")
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.setenv(hl.NESTED_ENV, "1")  # what the engine sets on the CLI it starts
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 0
    _assert_host_request(out, "nested", [TASK])
    assert fakes.log(bin_dir, "opencode") == []


def test_llm_env_can_force_a_host_without_its_markers_and_the_provider_stays_opt_in(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    bin_dir = fakes.install(tmp_path, "claude", mode="claude", reply=_solution_plan(repo))
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv(hl.LLM_ENV, "claude-code")
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0 and out["mode"] == "hybrid" and out["llm"] == "claude-code" and out["status"] == "ok"
    assert out["tokens"]["prompt_tokens"] == 500 and out["model"] == "claude-test"
    monkeypatch.setenv(hl.LLM_ENV, "provider")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc, out = _run(_seed(tmp_path / "second"), capsys, "--task", TASK)
    assert rc == 2 and out["mode"] == "provider" and out["reason_code"] == "turbo_provider_key_missing"


def test_an_unknown_llm_value_is_blocked_and_names_the_valid_ones(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(hl.LLM_ENV, "nope")
    rc, out = _run(_seed(tmp_path), capsys, "--task", TASK)
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_llm_unknown"
    assert "opencode" in out["detail"] and "host" in out["detail"] and "provider" in out["detail"]


def test_explicit_provider_stays_headless_only_even_on_a_host(tmp_path, monkeypatch, capsys):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply="{}")
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc, out = _run(_seed(tmp_path), capsys, "--provider", "openrouter", "--task", TASK)
    assert rc == 2 and out["mode"] == "provider" and out["reason_code"] == "turbo_provider_key_missing"
    assert fakes.log(bin_dir, "opencode") == []


# --- a failure in the middle of a run: keep what was applied, hand over the rest --------------------------------------

def _chain(repo: Path, count: int) -> str:
    tasks = [{"text": f"Create page{i}.html.", "target": f"page{i}.html", "depends_on": [i - 1] if i > 1 else []}
             for i in range(1, count + 1)]
    path = repo / "tasks.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return str(path)


def _page(number: int) -> dict:
    return {"mode": "opencode", "reply": json.dumps({"operations": [{"path": f"page{number}.html", "find": "", "replace": f"page {number}\n"}]})}


def test_a_failure_mid_run_keeps_the_applied_tasks_and_hands_over_only_the_remaining_ones(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    bin_dir = fakes.install(tmp_path, "opencode", calls=[_page(1), _page(2), _dead("opencode_error_auth.jsonl")])
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--tasks-file", _chain(repo, 4), "--verify", VERIFY)
    assert rc == 0
    _assert_host_request(out, "host_auth", ["Create page3.html.", "Create page4.html."])
    assert out["applied"] == [1, 2] and out["detail"]
    assert list(out)[:5] == ["schema", "status", "mode", "reason", "detail"] and list(out).index("applied") == 5
    assert (repo / "page1.html").read_text(encoding="utf-8") == "page 1\n" and (repo / "page2.html").is_file()
    assert not (repo / "page3.html").exists()
    assert f"--verify {shlex.quote(VERIFY)}" in out["apply"]  # the host's apply command verifies the whole result


def test_the_time_budget_stops_new_lanes_and_hands_the_rest_over(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    slow = [{**_page(i), "sleep": 1.5} for i in (1, 2, 3, 4, 5)]
    bin_dir = fakes.install(tmp_path, "opencode", calls=slow)
    _on_opencode(monkeypatch, bin_dir)
    monkeypatch.setenv(hl.BUDGET_ENV, "2")
    rc, out = _run(repo, capsys, "--tasks-file", _chain(repo, 5))  # more than three tasks: one lane each
    assert rc == 0
    _assert_host_request(out, "budget", [f"Create page{i}.html." for i in (2, 3, 4, 5)])
    assert out["applied"] == [1] and len(fakes.log(bin_dir, "opencode")) == 1  # lane 2 was never started
    assert (repo / "page1.html").is_file()


def test_the_budget_is_100_seconds_unless_the_environment_says_otherwise(monkeypatch):
    assert hl.budget_s({}) == 100.0  # under the 120 s tool timeout of Claude Code and OpenCode
    assert hl.budget_s({hl.BUDGET_ENV: "90"}) == 90.0
    assert hl.budget_s({hl.BUDGET_ENV: "0"}) == 100.0 and hl.budget_s({hl.BUDGET_ENV: "soon"}) == 100.0


def test_independent_tasks_fan_out_without_a_warm_up_call(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    (repo / "tasks.json").write_text(json.dumps([{"text": f"Create page{i}.html.", "target": f"page{i}.html"} for i in range(1, 5)]),
                                     encoding="utf-8")
    # The lanes run at the same time, so which task gets which invocation is not fixed; each invocation creates its own page.
    bin_dir = fakes.install(tmp_path, "opencode", calls=[_page(1), _page(2), _page(3), _page(4)])
    _on_opencode(monkeypatch, bin_dir)
    rc, out = _run(repo, capsys, "--tasks-file", str(repo / "tasks.json"))
    seen = fakes.log(bin_dir, "opencode")
    assert len(seen) == 4 and not any("Reply with OK." in s["stdin"] for s in seen)  # no warm-up: a host CLI has no cache to warm
    assert out["mode"] == "hybrid" and out["model_calls"] == 4


def test_the_hybrid_result_survives_a_host_that_reports_no_usage(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    bin_dir = fakes.install(tmp_path, "hermes", mode="text", reply=_solution_plan(repo))
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv(hl.LLM_ENV, "hermes")
    rc, out = _run(repo, capsys, "--task", TASK, "--verify", VERIFY)
    assert rc == 0 and out["status"] == "ok" and out["llm"] == "hermes"
    assert out["tokens"] == {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
    assert out["tokens_reported"] is False and out["cost_usd"] is None
    (seen,) = fakes.log(bin_dir, "hermes")
    assert seen["argv"][0] == "-z" and "Mapper project map:" in seen["argv"][1] and seen["stdin"] == ""
