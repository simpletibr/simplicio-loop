"""3.47.0 hybrid mode, the backend: the turbo engine's model calls go through the invoking host's own headless CLI.

Fake CLIs (`tests/_host_cli_fakes.py`) print the output shapes recorded from the real CLIs
(`tests/fixtures/host_llm/`), so the parsers are tested against what each host really prints.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host_cli_fakes as fakes  # noqa: E402

from simplicio_loop import turbo  # noqa: E402
from simplicio_loop import turbo_host_llm as hl  # noqa: E402

pytestmark = pytest.mark.usefixtures("hermetic_hybrid_detection")
PLAN = json.dumps({"operations": [{"path": "inventory.py", "find": "self._stock[sku] = qty",
                                   "replace": "self._stock[sku] = self._stock.get(sku, 0) + qty"}]})
TASKS = [{"index": 1, "text": "Fix the two bugs in inventory.py.", "target": "inventory.py", "context": []}]


def _messages(root: Path | None = None) -> list[dict]:
    return [turbo.header_message('{"files":[]}'), turbo.task_message(TASKS, root)]


def _backend(hid: str, model: str | None = None) -> hl.Backend:
    return hl.Backend(entry=hl.entry(hid), model=model)


# --- parsers, one family each, on the output the real CLI printed -------------------------------------------------

def test_opencode_events_give_text_tokens_and_cost():
    parsed = hl.parse_output(hl.entry("opencode"), fakes.fixture("opencode_ok.jsonl"), "", 0)
    assert parsed.error is None and parsed.cause is None
    assert json.loads(parsed.text)["operations"][0]["path"] == "inventory.py"
    assert (parsed.prompt_tokens, parsed.cached_tokens, parsed.completion_tokens, parsed.reasoning_tokens) == (970, 0, 255, 0)
    assert parsed.cost == pytest.approx(0.000597)


@pytest.mark.parametrize("name, cause", [
    ("opencode_error_auth.jsonl", "host_auth"),
    ("opencode_error_network.jsonl", "network"),
    ("opencode_error_unknown.jsonl", "host_error"),
])
def test_opencode_error_events_are_typed(name, cause):
    parsed = hl.parse_output(hl.entry("opencode"), fakes.fixture(name), "", 1)
    assert parsed.text is None and parsed.cause == cause and parsed.error


def test_claude_json_gives_text_tokens_cost_and_model():
    parsed = hl.parse_output(hl.entry("claude-code"), fakes.fixture("claude_ok.json"), "", 0)
    assert parsed.error is None and parsed.text == "OK" and parsed.model == "claude-sonnet-5-5"
    assert (parsed.prompt_tokens, parsed.cached_tokens, parsed.completion_tokens) == (478, 0, 4)
    assert parsed.cost == pytest.approx(0.000996)


@pytest.mark.parametrize("name", ["claude_error_notloggedin.json", "claude_error_badkey.json"])
def test_claude_errors_are_auth_errors(name):
    parsed = hl.parse_output(hl.entry("claude-code"), fakes.fixture(name), "", 1)
    assert parsed.text is None and parsed.cause == "host_auth" and parsed.error


@pytest.mark.parametrize("hid, name, tokens", [("pi", "pi_ok.jsonl", 80), ("oh-my-pi", "omp_ok.jsonl", 281)])
def test_pi_family_events_give_text_and_usage(hid, name, tokens):
    parsed = hl.parse_output(hl.entry(hid), fakes.fixture(name), "", 0)
    assert parsed.error is None and parsed.text == "OK" and parsed.prompt_tokens == tokens
    assert parsed.model == "deepseek/deepseek-v4.1-flash" and parsed.cost and parsed.cost < 0.001


def test_pi_reports_a_model_error_on_exit_zero_and_that_is_a_failed_call():
    parsed = hl.parse_output(hl.entry("pi"), fakes.fixture("pi_error_usage_limit.jsonl"), "", 0)
    assert parsed.text is None and parsed.cause == "host_http" and "usage limit" in parsed.error


def test_json_paths_family_reads_the_text_and_usage_named_by_the_entry():
    agy = hl.parse_output(hl.entry("antigravity"), fakes.fixture("agy_ok.json"), "", 0)
    assert agy.error is None and agy.text == "OK" and (agy.prompt_tokens, agy.completion_tokens) == (26817, 1)
    claw = hl.parse_output(hl.entry("openclaw"), fakes.fixture("openclaw_ok.json"), "", 0)
    assert claw.error is None and claw.text == "OK" and claw.model == "deepseek/deepseek-v4.1-flash"
    failed = hl.parse_output(hl.entry("openclaw"), json.dumps({"ok": False, "error": "no provider configured"}), "", 1)
    assert failed.text is None and failed.error and failed.cause == "host_error"


def test_codex_jsonl_gives_the_agent_message_and_the_turn_usage():
    """Documented schema (developers.openai.com/codex/noninteractive); codex is not signed in on the machine that checked it."""
    parsed = hl.parse_output(hl.entry("codex"), fakes.fixture("documented_codex_ok.jsonl"), "", 0)
    assert parsed.error is None and parsed.text == "OK"
    assert (parsed.prompt_tokens, parsed.cached_tokens, parsed.completion_tokens, parsed.reasoning_tokens) == (24763, 24448, 122, 30)
    failed = hl.parse_output(hl.entry("codex"), fakes.fixture("documented_codex_error.jsonl"), "", 1)
    assert failed.text is None and failed.cause == "host_auth" and "401" in failed.error


def test_json_paths_family_reads_the_documented_shapes_of_gemini_grok_and_qwen():
    gemini = hl.parse_output(hl.entry("gemini"), fakes.fixture("documented_gemini_ok.json"), "", 0)
    assert gemini.error is None and gemini.text == "OK" and gemini.prompt_tokens == 0
    bad = hl.parse_output(hl.entry("gemini"), fakes.fixture("documented_gemini_error.json"), "", 1)
    assert bad.text is None and "Auth method" in bad.error
    grok = hl.parse_output(hl.entry("grok"), fakes.fixture("documented_grok_ok.json"), "", 0)
    assert grok.error is None and grok.text == "OK" and grok.cost == 0.0012
    assert (grok.prompt_tokens, grok.cached_tokens, grok.completion_tokens, grok.reasoning_tokens) == (1212, 400, 45, 5)  # uncached + cache hits
    grok_bad = hl.parse_output(hl.entry("grok"), fakes.fixture("documented_grok_error.json"), "", 1)
    assert grok_bad.text is None and grok_bad.cause == "host_auth"
    qwen = hl.parse_output(hl.entry("qwen-code"), fakes.fixture("documented_qwen_ok.json"), "", 0)  # an array: the last `result` message
    assert qwen.error is None and qwen.text == "OK" and (qwen.prompt_tokens, qwen.completion_tokens) == (50, 2)
    qwen_bad = hl.parse_output(hl.entry("qwen-code"), fakes.fixture("documented_qwen_error.json"), "", 1)
    assert qwen_bad.text is None and qwen_bad.cause == "host_auth"


def test_droid_prints_the_shape_claude_code_prints():
    parsed = hl.parse_output(hl.entry("droid"), fakes.fixture("documented_droid_ok.json"), "", 0)
    assert parsed.error is None and parsed.text == "OK" and parsed.usage is False


def test_text_family_takes_stdout_as_the_reply_and_a_nonzero_exit_as_the_error():
    ok = hl.parse_output(hl.entry("hermes"), fakes.fixture("hermes_ok.txt"), "", 0)
    assert ok.error is None and ok.text == "OK" and ok.prompt_tokens == 0
    bad = hl.parse_output(hl.entry("hermes"), fakes.fixture("hermes_error_403.txt"), "", 2)
    assert bad.text is None and bad.cause == "host_auth" and "403" in bad.error


def test_an_empty_reply_and_a_silent_failure_are_errors():
    assert hl.parse_output(hl.entry("hermes"), "", "", 0).cause == "host_error"
    silent = hl.parse_output(hl.entry("hermes"), "", "boom: something broke\n", 1)
    assert silent.cause == "host_error" and "boom" in silent.error


@pytest.mark.parametrize("message, status, cause", [
    ("User not found.", 401, "host_auth"),
    ("Not logged in · Please run /login", None, "host_auth"),
    ("OpenRouter API key is missing. Pass it using the 'apiKey' parameter", None, "host_auth"),  # a real opencode without a key
    ("Cannot connect to API: Unable to connect. Is the computer able to access the url?", None, "network"),
    ("getaddrinfo ENOTFOUND api.example.com", None, "network"),
    ("The usage limit has been reached", None, "host_http"),
    ("HTTP 503 Service Unavailable", 503, "host_http"),
    ("Unexpected server error. Check server logs for details.", None, "host_error"),
    ("Error: Unexpected error\n\ndatabase is locked", None, "host_state_busy"),  # opencode lanes sharing one session database
    ("SQLITE_BUSY: database is locked", None, "host_state_busy"),
    ('Failed query: select "credential" from "account" where "id" = ? params: acc_1', None, "host_state_busy"),  # not host_auth
])
def test_classify_names_the_cause(message, status, cause):
    assert hl.classify(message, status) == cause


# --- the call: what is run, with what stdin and environment ------------------------------------------------------

def test_opencode_call_uses_the_users_config_plus_one_injected_planner_agent(tmp_path):
    call = hl.build_call(_backend("opencode"), tmp_path, _messages(tmp_path), environ={"PATH": "/bin", "HOME": "/home/u"})
    assert call.argv == ["opencode", "run", "--pure", "--agent", "simplicio-planner", "--format", "json", "--title", "simplicio-turbo"]
    # The planner rule lives in the agent; the map and the task travel as the prompt, on stdin, verbatim.
    assert call.stdin.startswith("Mapper project map:\n{\"files\":[]}\n\nTasks:\n1. Fix the two bugs in inventory.py.")
    assert turbo._PLANNER_SYSTEM not in call.stdin
    state = tmp_path / ".simplicio-loop" / "host-llm"
    assert call.env["OPENCODE_CONFIG"] == str(state / "opencode.json")
    assert call.env["OPENCODE_DB"] == str(state / "db" / "slot-0.db")  # one session database per concurrency slot
    assert call.env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1" and call.env["OPENCODE_PERMISSION"] == '{"*":"deny"}'
    assert call.env["SIMPLICIO_TURBO_NESTED"] == "1" and call.env["HOME"] == "/home/u"  # the user's environment, untouched
    assert call.cwd == tmp_path
    config = json.loads((state / "opencode.json").read_text(encoding="utf-8"))
    agent = config["agent"]["simplicio-planner"]
    assert agent["prompt"] == turbo._PLANNER_SYSTEM and agent["permission"] == {"*": "deny"} and agent["mode"] == "primary"
    assert "model" not in agent and "model" not in config  # OpenCode's own default model resolution applies
    assert config["provider"]["openrouter"]["models"] == {
        "deepseek/deepseek-v4.1-flash": {"options": {"reasoning": {"enabled": False}}}}


def test_opencode_call_never_writes_outside_the_repo_state_dir(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    users = home / ".config" / "opencode" / "opencode.json"
    users.write_text('{"model": "anthropic/claude-x"}', encoding="utf-8")
    hl.build_call(_backend("opencode"), tmp_path / "repo", _messages(), environ={"HOME": str(home)})
    assert users.read_text(encoding="utf-8") == '{"model": "anthropic/claude-x"}'
    assert sorted(p.name for p in (tmp_path / "repo" / ".simplicio-loop" / "host-llm").iterdir()) == ["db", "opencode.json"]


def test_a_model_override_is_passed_to_the_host_and_reasoning_off_follows_an_openrouter_model(tmp_path):
    call = hl.build_call(_backend("opencode", model="openrouter/acme/fast-1"), tmp_path, _messages(), environ={})
    assert call.argv[-2:] == ["-m", "openrouter/acme/fast-1"]
    config = json.loads(Path(call.env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))
    assert set(config["provider"]["openrouter"]["models"]) == {"deepseek/deepseek-v4.1-flash", "acme/fast-1"}
    other = hl.build_call(_backend("opencode", model="anthropic/claude-x"), tmp_path, _messages(), environ={})
    assert other.argv[-2:] == ["-m", "anthropic/claude-x"]
    config = json.loads(Path(other.env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))
    assert set(config["provider"]["openrouter"]["models"]) == {"deepseek/deepseek-v4.1-flash"}  # nothing added for another provider


def test_an_opencode_config_the_user_already_names_is_kept_but_never_their_database(tmp_path):
    call = hl.build_call(_backend("opencode"), tmp_path, _messages(),
                         environ={"OPENCODE_CONFIG": "/home/u/mine.json", "OPENCODE_DB": "/home/u/mine.db"}, slot=2)
    assert call.env["OPENCODE_CONFIG"] == "/home/u/mine.json"
    # Lanes that share one OpenCode database fail with "database is locked": each slot has its own, whatever the user exports.
    assert call.env["OPENCODE_DB"] == str(tmp_path / ".simplicio-loop" / "host-llm" / "db" / "slot-2.db")
    merged = json.loads(call.env["OPENCODE_CONFIG_CONTENT"])  # the planner agent rides on top, as inline content
    assert merged["agent"]["simplicio-planner"]["permission"] == {"*": "deny"}


def test_claude_call_passes_the_system_text_as_a_flag_and_the_prompt_on_stdin(tmp_path):
    call = hl.build_call(_backend("claude-code"), tmp_path, _messages(tmp_path), environ={})
    assert call.argv[:6] == ["claude", "-p", "--output-format", "json", "--safe-mode", "--system-prompt"]
    assert call.argv[6].startswith(turbo._PLANNER_SYSTEM) and "Mapper project map:" in call.argv[6]
    assert call.argv[7:9] == ["--tools", ""] and "--no-session-persistence" in call.argv
    assert call.stdin.startswith("Tasks:\n1. Fix the two bugs") and call.env["SIMPLICIO_TURBO_NESTED"] == "1"
    assert "OPENCODE_CONFIG" not in call.env


def test_a_host_without_a_system_flag_gets_one_prompt_argument_and_no_stdin(tmp_path):
    call = hl.build_call(_backend("hermes"), tmp_path, _messages(tmp_path), environ={})
    assert call.argv[:2] == ["hermes", "-z"] and call.stdin is None
    assert call.argv[2].startswith(turbo._PLANNER_SYSTEM) and "Tasks:\n1. Fix the two bugs" in call.argv[2]


def test_a_retry_conversation_is_flattened_with_role_labels(tmp_path):
    messages = [*_messages(tmp_path), {"role": "assistant", "content": "{}"},
                {"role": "user", "content": "dev-cli rejected the plan:\nfind did not match\nReturn a corrected JSON plan."}]
    call = hl.build_call(_backend("opencode"), tmp_path, messages, environ={})
    assert "[assistant]\n{}" in call.stdin and call.stdin.rstrip().endswith("Return a corrected JSON plan.")


# --- the process: the fake host CLI runs for real ------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "inventory.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_complete_runs_the_cli_and_returns_the_reply_the_engine_records(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN, cost=0.0006)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] is True and reply["content"] == PLAN and reply["finish_reason"] == "stop"
    assert (reply["prompt_tokens"], reply["cached_tokens"], reply["completion_tokens"], reply["reasoning_tokens"]) == (970, 0, 255, 0)
    assert reply["cost"] == reply["cost_usd"] == 0.0006 and reply["host"] == "opencode" and reply["latency_s"] >= 0
    (seen,) = fakes.log(bin_dir, "opencode")
    assert seen["argv"][:5] == ["run", "--pure", "--agent", "simplicio-planner", "--format"]
    assert seen["stdin"].startswith("Mapper project map:") and seen["cwd"] == str(repo.resolve())
    assert seen["env"]["SIMPLICIO_TURBO_NESTED"] == "1"
    assert json.loads(seen["agent_file"])["agent"]["simplicio-planner"]["permission"] == {"*": "deny"}


@pytest.mark.parametrize("call, cause", [
    ({"mode": "text", "stdout_file": str(fakes.FIXTURES / "opencode_error_auth.jsonl"), "exit": 1}, "host_auth"),
    ({"mode": "text", "stdout_file": str(fakes.FIXTURES / "opencode_error_network.jsonl"), "exit": 1}, "network"),
    ({"mode": "text", "stdout": "", "stderr": "kaboom", "exit": 3}, "host_error"),
])
def test_complete_returns_a_typed_fatal_error_when_the_cli_fails(tmp_path, repo, monkeypatch, call, cause):
    bin_dir = fakes.install(tmp_path, "opencode", **call)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == cause and reply["error"]


def test_the_agent_fallback_warning_is_fatal_because_the_planner_did_not_load(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN,
                            stderr='! agent "simplicio-planner" not found. Falling back to default agent\n')
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "host_error"
    assert "planner agent" in reply["error"]


def test_complete_kills_a_cli_that_outlives_its_timeout(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN, sleep=30)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    started = time.monotonic()
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo, timeout=1.0)
    assert time.monotonic() - started < 10
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "host_timeout"
    (seen,) = fakes.log(bin_dir, "opencode")
    with pytest.raises(ProcessLookupError):  # no orphan is left behind
        os.kill(seen["pid"], 0)


def test_complete_does_not_start_a_cli_once_the_budget_is_spent(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo, deadline=time.monotonic() - 1)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "budget"
    assert fakes.log(bin_dir, "opencode") == []


def test_complete_reports_a_missing_cli_as_a_typed_error(tmp_path, repo, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "host_cli_missing"


def test_complete_runs_claude_with_the_flags_recorded_from_the_real_cli(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "claude", mode="claude", reply=PLAN)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("claude-code"), root=repo)
    assert reply["ok"] and reply["content"] == PLAN and reply["prompt_tokens"] == 500 and reply["cached_tokens"] == 80
    (seen,) = fakes.log(bin_dir, "claude")
    assert "--safe-mode" in seen["argv"] and seen["argv"][seen["argv"].index("--tools") + 1] == ""
    assert seen["stdin"].startswith("Tasks:")


def test_complete_runs_pi_and_a_model_error_on_exit_zero_is_fatal(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "pi", mode="pi", reply=PLAN)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("pi"), root=repo)
    assert reply["ok"] and reply["content"] == PLAN and reply["model"] == "test/model"
    failed = fakes.install(tmp_path / "f", "pi", stdout_file=str(fakes.FIXTURES / "pi_error_usage_limit.jsonl"))
    monkeypatch.setenv("PATH", fakes.path_with(failed))
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("pi"), root=repo)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "host_http"


def test_complete_limits_how_many_host_processes_run_at_once(tmp_path, repo, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN, sleep=0.3)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv("SIMPLICIO_TURBO_HOST_PARALLEL", "2")
    monkeypatch.setattr(hl, "_slots", None)  # re-read the limit
    started = time.monotonic()
    with ThreadPoolExecutor(6) as pool:
        replies = list(pool.map(lambda _: hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo), range(6)))
    assert all(r["ok"] for r in replies)
    assert time.monotonic() - started >= 0.9  # 6 calls of 0.3 s, two at a time: at least 3 rounds


def test_the_default_number_of_host_processes_is_the_cpu_count_capped_at_eight(monkeypatch):
    assert hl.DEFAULT_PARALLEL == min(8, os.cpu_count() or 4)
    monkeypatch.delenv(hl.PARALLEL_ENV, raising=False)
    monkeypatch.setattr(hl, "_slots", None)
    assert hl._slot_pool().qsize() == hl.DEFAULT_PARALLEL
    monkeypatch.setenv(hl.PARALLEL_ENV, "3")
    monkeypatch.setattr(hl, "_slots", None)
    assert hl._slot_pool().qsize() == 3


def test_a_call_that_waited_for_a_slot_past_the_deadline_never_starts_the_cli(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv(hl.PARALLEL_ENV, "1")
    monkeypatch.setattr(hl, "_slots", None)
    pool = hl._slot_pool()
    taken = pool.get()  # the only slot is taken: the call below has to wait for it
    result: dict = {}
    call = threading.Thread(target=lambda: result.update(hl.complete(
        "simplicio", _messages(repo), backend=_backend("opencode"), root=repo, deadline=time.monotonic() + 1.5)))
    call.start()
    time.sleep(0.8)  # the budget runs down while it waits: less than the 1 s a call needs is left
    pool.put(taken)
    call.join(10)
    assert result["ok"] is False and result["fatal"] is True and result["reason_code"] == "budget"
    assert fakes.log(bin_dir, "opencode") == []  # nothing was spawned


def test_concurrent_lanes_never_share_an_opencode_database_and_slots_reuse_theirs(tmp_path, repo, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN, sleep=0.4)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv(hl.PARALLEL_ENV, "3")
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "the-users.db"))  # exported by the user: not used by any lane
    monkeypatch.setattr(hl, "_slots", None)
    with ThreadPoolExecutor(6) as pool:
        replies = list(pool.map(lambda _: hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo), range(6)))
    assert all(r["ok"] for r in replies)
    runs = [(r["env"]["OPENCODE_DB"], r["start"], r["start"] + r["sleep"]) for r in fakes.log(bin_dir, "opencode")]
    assert len(runs) == 6
    databases = {db for db, _, _ in runs}
    state = repo / ".simplicio-loop" / "host-llm" / "db"
    assert databases == {str(state / f"slot-{k}.db") for k in range(3)}  # 6 calls, 3 slots: each database reused
    for db, start, end in runs:  # no two live processes share a database
        assert not [1 for other, s2, e2 in runs if other == db and (other, s2, e2) != (db, start, end) and s2 < end and start < e2]


def test_calls_that_follow_each_other_reuse_the_first_slots_database(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setenv(hl.PARALLEL_ENV, "4")
    monkeypatch.setattr(hl, "_slots", None)
    for _ in range(3):
        assert hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)["ok"]
    assert {r["env"]["OPENCODE_DB"] for r in fakes.log(bin_dir, "opencode")} == {str(repo / ".simplicio-loop" / "host-llm" / "db" / "slot-0.db")}


BUSY = {"exit": 1, "stderr": "\x1b[91m\x1b[1mError: \x1b[0mUnexpected error\n\ndatabase is locked\n"}


def test_a_lane_whose_host_state_was_busy_is_retried_once_after_a_pause(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", calls=[BUSY, {"mode": "opencode", "reply": PLAN}])
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setattr(hl, "BUSY_BACKOFF_S", 0.3)
    started = time.monotonic()
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] and reply["content"] == PLAN and len(fakes.log(bin_dir, "opencode")) == 2
    assert time.monotonic() - started >= 0.3  # it waited before the second run


def test_a_host_state_that_stays_busy_is_typed_after_the_one_retry(tmp_path, repo, monkeypatch):
    bin_dir = fakes.install(tmp_path, "opencode", **BUSY)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    monkeypatch.setattr(hl, "BUSY_BACKOFF_S", 0.0)
    reply = hl.complete("simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
    assert reply["ok"] is False and reply["fatal"] is True and reply["reason_code"] == "host_state_busy"
    assert len(fakes.log(bin_dir, "opencode")) == 2  # once more, not forever


# --- which host is this, and can it be used ---------------------------------------------------------------------------

def test_detect_reads_the_env_markers_a_tool_subprocess_of_the_host_sees():
    assert hl.detect(environ={"OPENCODE": "1", "AGENT": "1"}, ancestors=[])["id"] == "opencode"
    assert hl.detect(environ={"OPENCODE_PID": "4242"}, ancestors=[])["id"] == "opencode"  # set = present
    assert hl.detect(environ={"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"}, ancestors=[])["id"] == "claude-code"
    assert hl.detect(environ={"OPENCODE": "0"}, ancestors=[]) is None  # NAME=value needs that value
    assert hl.detect(environ={"HOME": "/home/u"}, ancestors=[]) is None


def test_detect_falls_back_to_the_process_names_among_the_ancestors():
    assert hl.detect(environ={}, ancestors=["zsh", "opencode", "Terminal"])["id"] == "opencode"
    assert hl.detect(environ={}, ancestors=["/usr/local/bin/OpenCode.exe"])["id"] == "opencode"
    assert hl.detect(environ={}, ancestors=["zsh", "launchd"]) is None


def test_the_nearest_host_wins_when_two_are_in_the_chain():
    both = {"CLAUDECODE": "1", "OPENCODE": "1"}  # OpenCode was started from a Claude Code session
    assert hl.detect(environ=both, ancestors=["zsh", "opencode", "zsh", "claude"])["id"] == "opencode"
    assert hl.detect(environ=both, ancestors=["zsh", "claude", "zsh", "opencode"])["id"] == "claude-code"
    assert hl.detect(environ=both, ancestors=[])["id"] in ("opencode", "claude-code")  # no chain: catalog order, still a host


ENTRIES = [
    {"id": "alpha", "name": "Alpha", "aliases": ["a1"], "detect": {"env": ["ALPHA=1"], "process": ["alpha"]},
     "llm": {"status": "verified", "argv": ["alpha-cli", "{prompt}"], "prompt": "arg", "system": "prompt", "parse": "text",
             "probe": ["127.0.0.1:9"], "network_env": ["ALPHA_NO_NET"]}},
    {"id": "beta", "name": "Beta", "aliases": [], "detect": {"env": ["BETA"]}, "llm": {"status": "host-mode"}},
    {"id": "delta", "name": "Delta", "aliases": [], "detect": {"env": ["DELTA"]},
     "llm": {"status": "verified", "argv": ["delta-cli", "{prompt}"], "prompt": "arg", "system": "prompt", "parse": "text", "auto": False}},
    {"id": "gamma", "name": "Gamma", "aliases": [], "detect": None, "llm": {"status": "host-mode"}},
]


def _resolve(environ, **kwargs):
    kwargs.setdefault("ancestors", [])
    kwargs.setdefault("entries", ENTRIES)
    kwargs.setdefault("which", lambda name, **kw: f"/bin/{name}")
    kwargs.setdefault("probe", lambda targets, environ=None: True)
    return hl.resolve(environ=environ, **kwargs)


def test_resolve_picks_the_detected_host_and_reads_the_model_override():
    choice = _resolve({"ALPHA": "1", hl.MODEL_ENV: "prov/model-1"})
    assert choice.cause is None and choice.backend.id == "alpha" and choice.backend.model == "prov/model-1"
    assert choice.backend.forced is False


@pytest.mark.parametrize("environ, kwargs, cause", [
    ({}, {}, "no_host_detected"),
    ({"BETA": "1"}, {}, "host_mode_only"),                                   # detected, but no headless one-shot
    ({"ALPHA": "1"}, {"which": lambda name, **kw: None}, "host_cli_missing"),
    ({"ALPHA": "1"}, {"probe": lambda targets, environ=None: False}, "network"),
    ({"ALPHA": "1", "ALPHA_NO_NET": "1"}, {}, "network"),                     # the host's own sandbox says so
    ({"ALPHA": "1", hl.NESTED_ENV: "1"}, {}, "nested"),                       # the recursion guard
    ({"ALPHA": "1", hl.LLM_ENV: "host"}, {}, "forced_host"),
    ({"ALPHA": "1", hl.LLM_ENV: "nope"}, {}, "unknown_llm"),
    ({"DELTA": "1"}, {}, "opt_in"),                                           # its run may keep its tools: never auto-selected
])
def test_resolve_names_why_the_hybrid_backend_cannot_be_used(environ, kwargs, cause):
    choice = _resolve(environ, **kwargs)
    assert choice.backend is None and choice.cause == cause and choice.reason == f"hybrid_unavailable: {cause}"


def test_llm_env_forces_an_entry_by_id_or_alias_even_without_its_markers_and_skips_the_network_probe():
    for value in ("alpha", "a1", "ALPHA"):
        choice = _resolve({hl.LLM_ENV: value}, probe=lambda targets, environ=None: False)
        assert choice.cause is None and choice.backend.id == "alpha" and choice.backend.forced is True
    assert _resolve({hl.LLM_ENV: "provider"}).provider is True
    assert _resolve({hl.LLM_ENV: "auto", "ALPHA": "1"}).backend.id == "alpha"


def test_an_entry_that_may_keep_its_tools_is_only_used_when_forced_by_name():
    choice = _resolve({"DELTA": "1"})
    assert choice.backend is None and choice.cause == "opt_in" and choice.reason == "hybrid_unavailable: opt_in"
    assert f"{hl.LLM_ENV}=delta" in choice.detail and "trusted repository" in choice.detail
    forced = _resolve({hl.LLM_ENV: "delta"})
    assert forced.cause is None and forced.backend.id == "delta" and forced.backend.forced is True
    real = hl.resolve(environ={}, ancestors=["zsh", "hermes"], which=lambda name, **kw: "/x/" + name)  # the real catalog
    assert real.cause == "opt_in" and "Hermes" in real.detail


def test_the_nested_guard_beats_a_forced_entry():
    choice = _resolve({hl.LLM_ENV: "alpha", hl.NESTED_ENV: "1"})
    assert choice.backend is None and choice.cause == "nested"


def test_the_real_catalog_detects_opencode_and_falls_back_without_a_marker(monkeypatch):
    choice = hl.resolve(environ={"OPENCODE": "1"}, ancestors=[], which=lambda name, **kw: "/x/" + name,
                        probe=lambda targets, environ=None: True)
    assert choice.backend.id == "opencode"
    assert hl.resolve(environ={}, ancestors=[]).cause == "no_host_detected"


def test_probe_network_connects_to_any_target_within_its_budget():
    import socket
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(32)  # nobody accepts: every probe connection just waits in the backlog
    try:
        port = server.getsockname()[1]
        assert hl.probe_network([f"127.0.0.1:{port}"], budget=2.0, environ={}) is True
        assert hl.probe_network(["127.0.0.1:1", f"127.0.0.1:{port}"], budget=2.0, environ={}) is True  # one is enough
        # a proxy in the environment is what the CLI goes through, so that is what is probed
        assert hl.probe_network(["nonexistent.invalid:443"], budget=2.0, environ={"HTTPS_PROXY": f"http://127.0.0.1:{port}"}) is True
    finally:
        server.close()
    started = time.monotonic()
    assert hl.probe_network(["127.0.0.1:1"], budget=2.0, environ={}) is False
    assert hl.probe_network(["nonexistent.invalid:443"], budget=2.0, environ={}) is False
    assert time.monotonic() - started < 6
    assert hl.probe_network(["127.0.0.1:1"], budget=2.0, environ={hl.PROBE_ENV: "0"}) is True  # the escape hatch


def test_ancestor_names_lists_this_processes_parents_nearest_first():
    names = hl.ancestor_names()
    assert isinstance(names, list) and all(isinstance(n, str) for n in names)


def test_kill_active_stops_a_running_cli(tmp_path, repo, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    bin_dir = fakes.install(tmp_path, "opencode", mode="opencode", reply=PLAN, sleep=30)
    monkeypatch.setenv("PATH", fakes.path_with(bin_dir))
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(hl.complete, "simplicio", _messages(repo), backend=_backend("opencode"), root=repo)
        for _ in range(100):
            if fakes.log(bin_dir, "opencode"):
                break
            time.sleep(0.05)
        hl.kill_active()
        reply = future.result(timeout=10)
    assert reply["ok"] is False and reply["fatal"] is True
