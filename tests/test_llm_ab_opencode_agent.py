"""TDD unit tests for bench/llm_ab/opencode_agent.py -- the real OpenCode
agent driver that replaced the Python tool-calling loop (``agent.py``,
deleted, issue #1325).

Covers, with no live process/network calls:

- parsing a recorded ``opencode run --format json`` event stream (this
  repo's own fixture, ``tests/fixtures/opencode/run_events.jsonl``, captured
  from one real ``opencode run`` against the actual cadastro-create task
  text -- see the fixture's own header comment for provenance) into the
  same per-task totals shape ``run.py``/``aggregate.py``/``report.py``
  already consume;
- the real-billed-cost key-usage delta (fake ``urlopen``, no network);
- the command line and environment built for each arm (skill only in
  simplicio; the OpenRouter key only ever reaches the child process via an
  environment variable, never a CLI argument).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import opencode_agent as oc  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "opencode", "run_events.jsonl")


def _load_fixture_events() -> list[dict]:
    with open(FIXTURE) as f:
        return [json.loads(line) for line in f if line.strip()]


# -- classify_command / truncate_tail (ported from agent.py, agent.py itself
#    is retired) --------------------------------------------------------------

def test_classify_command_true_for_simplicio_binaries():
    assert oc.classify_command("simplicio-loop orient --task foo --json") is True
    assert oc.classify_command("simplicio-mapper scan .") is True
    assert oc.classify_command("cd /tmp && simplicio-dev-cli edit --plan p.json") is True


def test_classify_command_false_for_plain_commands():
    assert oc.classify_command("cat > cadastro.html <<'EOF'") is False
    assert oc.classify_command(None) is False
    assert oc.classify_command("") is False


def test_truncate_tail_keeps_only_last_n_chars():
    text = "a" * 100 + "b" * 20
    assert oc.truncate_tail(text, limit=20) == "b" * 20


def test_truncate_tail_tolerates_none():
    assert oc.truncate_tail(None) == ""


# -- build_prompt / install_skill --------------------------------------------

def test_build_prompt_normal_arm_is_unprefixed():
    assert oc.build_prompt("normal", "do the thing") == "do the thing"


def test_build_prompt_simplicio_arm_is_prefixed():
    assert oc.build_prompt("simplicio", "do the thing") == "/simplicio-loop do the thing"


def test_install_skill_copies_skill_md_into_dot_claude_skills(tmp_path):
    dst = oc.install_skill(str(tmp_path))
    assert os.path.isfile(os.path.join(dst, "SKILL.md"))
    assert dst == os.path.join(str(tmp_path), ".claude", "skills", "simplicio-loop")


def test_install_skill_is_idempotent(tmp_path):
    first = oc.install_skill(str(tmp_path))
    # A second call must not raise (shutil.copytree would raise on an
    # existing destination) and must return the same path.
    second = oc.install_skill(str(tmp_path))
    assert first == second
    assert os.path.isfile(os.path.join(second, "SKILL.md"))


# -- build_env / build_command: per-arm command-line & env construction -----

def test_build_env_carries_the_key_only_via_environment():
    env = oc.build_env("normal", "sk-or-secret-123", "/tmp/oc-home", base_env={"PATH": "/usr/bin"})
    assert env["OPENROUTER_API_KEY"] == "sk-or-secret-123"
    assert env["HOME"] == "/tmp/oc-home"
    assert env["XDG_CONFIG_HOME"] == os.path.join("/tmp/oc-home", ".config")
    assert env["XDG_DATA_HOME"] == os.path.join("/tmp/oc-home", ".local", "share")


def test_build_env_prepends_extra_path_for_simplicio_binaries():
    env = oc.build_env("simplicio", "k", "/tmp/oc-home", base_env={"PATH": "/usr/bin"},
                        extra_path="/venv/bin")
    assert env["PATH"].startswith("/venv/bin" + os.pathsep)
    assert env["PATH"].endswith("/usr/bin")


def test_build_command_never_puts_the_key_on_the_command_line():
    cmd = oc.build_command("/bin/opencode", "/repo", "do the thing")
    assert "sk-or" not in " ".join(cmd)
    assert "/repo" in cmd
    assert "do the thing" in cmd
    assert "--format" in cmd and "json" in cmd
    assert "--auto" in cmd
    assert cmd[0] == "/bin/opencode"
    assert cmd[1] == "run"


def test_build_command_model_is_openrouter_prefixed():
    cmd = oc.build_command("/bin/opencode", "/repo", "x")
    idx = cmd.index("--model")
    assert cmd[idx + 1] == oc.OPENCODE_MODEL
    assert cmd[idx + 1].startswith("openrouter/")


# -- parse_run_events: the recorded fixture ----------------------------------

def test_parse_run_events_turn_count_matches_step_finish_events():
    parsed = oc.parse_run_events(_load_fixture_events())
    assert parsed["turns"] == 2
    assert len(parsed["llm_calls"]) == 2


def test_parse_run_events_first_call_tokens_and_cost():
    parsed = oc.parse_run_events(_load_fixture_events())
    call = parsed["llm_calls"][0]
    assert call["ok"] is True
    assert call["prompt_tokens"] == 5674 + 1792  # input + cache.read (no cache.write)
    assert call["cached_tokens"] == 1792
    assert call["completion_tokens"] == 231 + 70  # output + reasoning
    assert call["reasoning_tokens"] == 70
    assert call["cost_usd"] == 0.002074152
    assert call["finish_reason"] == "tool-calls"
    assert call["reasoning_effort"] is None  # OpenCode does not expose per-call effort


def test_parse_run_events_second_call_tokens_and_cost():
    parsed = oc.parse_run_events(_load_fixture_events())
    call = parsed["llm_calls"][1]
    assert call["prompt_tokens"] == 100 + 7680
    assert call["cached_tokens"] == 7680
    assert call["completion_tokens"] == 8
    assert call["cost_usd"] == 8.568e-05
    assert call["finish_reason"] == "stop"


def test_parse_run_events_extracts_the_one_bash_command():
    parsed = oc.parse_run_events(_load_fixture_events())
    assert len(parsed["commands"]) == 1
    cmd = parsed["commands"][0]
    assert cmd["turn"] == 1
    assert cmd["command"].startswith("cat > cadastro.html")
    assert cmd["returncode"] == 0
    assert cmd["is_simplicio"] is False
    assert cmd["wall_s"] is not None and cmd["wall_s"] >= 0


def test_parse_run_events_final_text_is_the_last_text_part():
    parsed = oc.parse_run_events(_load_fixture_events())
    assert parsed["final_text"] == "Created `cadastro.html`."


def test_parse_run_events_ignores_unknown_event_types():
    events = _load_fixture_events() + [{"type": "something_new", "part": {}}]
    parsed = oc.parse_run_events(events)
    assert parsed["turns"] == 2  # unaffected


# -- summarize: totals aggregation, same shape as agent.summarize -----------

def test_summarize_totals_over_the_fixture():
    parsed = oc.parse_run_events(_load_fixture_events())
    totals = oc.summarize(parsed["llm_calls"], parsed["commands"])
    assert totals["prompt_tokens"] == (5674 + 1792) + (100 + 7680)
    assert totals["completion_tokens"] == (231 + 70) + 8
    assert totals["reasoning_tokens"] == 70
    assert totals["cached_tokens"] == 1792 + 7680
    assert totals["cost_usd"] == round(0.002074152 + 8.568e-05, 6)
    assert totals["cost_source"] == "opencode-reported"
    assert totals["n_commands"] == 1
    assert totals["n_simplicio_commands"] == 0


def test_summarize_empty_is_all_zeros():
    totals = oc.summarize([], [])
    assert totals["prompt_tokens"] == 0
    assert totals["cost_usd"] == 0
    assert totals["n_commands"] == 0


# -- real billed cost: OpenRouter key-usage delta (fake urlopen, no network) -

class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _usage_body(usage: float) -> bytes:
    return json.dumps({"data": {"usage": usage}}).encode("utf-8")


def test_fetch_key_usage_usd_parses_the_data_usage_field(monkeypatch):
    monkeypatch.setattr(
        oc.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(_usage_body(7.5))
    )
    assert oc.fetch_key_usage_usd("sk-or-x") == 7.5


def test_fetch_key_usage_usd_returns_none_on_bad_status(monkeypatch):
    import urllib.error

    def raise_http_error(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(oc.urllib.request, "urlopen", raise_http_error)
    assert oc.fetch_key_usage_usd("bad-key") is None


def test_poll_billed_delta_returns_the_first_observed_increase():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return 10.0 if calls["n"] < 2 else 10.0007

    delta = oc.poll_billed_delta(
        fetch, usage_before=10.0, timeout_s=10, interval_s=1,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3],
    )
    assert round(delta, 4) == 0.0007


def test_poll_billed_delta_gives_up_after_timeout_and_returns_none():
    delta = oc.poll_billed_delta(
        lambda: 10.0,  # usage never changes
        usage_before=10.0, timeout_s=5, interval_s=1,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3, 4, 5, 6],
    )
    assert delta is None


def test_poll_billed_delta_returns_none_when_no_baseline_usage():
    delta = oc.poll_billed_delta(lambda: 1.0, usage_before=None)
    assert delta is None
