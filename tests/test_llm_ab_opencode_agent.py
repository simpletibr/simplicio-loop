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


def test_build_env_isolated_path_replaces_path_entirely():
    """``isolated_path`` (issue #1337 ablation arms) REPLACES PATH outright --
    it must never be appended to the inherited PATH, or a binary excluded
    from the isolated path could still be found further down the chain."""
    env = oc.build_env("mapper", "k", "/tmp/oc-home", base_env={"PATH": "/usr/local/bin:/venv/bin"},
                        isolated_path="/shim:/usr/bin:/bin")
    assert env["PATH"] == "/shim:/usr/bin:/bin"
    assert "/usr/local/bin" not in env["PATH"]
    assert "/venv/bin" not in env["PATH"]


def test_build_env_isolated_path_wins_over_extra_path():
    env = oc.build_env("mapper", "k", "/tmp/oc-home", base_env={"PATH": "/usr/bin"},
                        extra_path="/venv/bin", isolated_path="/shim")
    assert env["PATH"] == "/shim"


# -- install_skills / build_shim_dir / build_arm_path (issue #1337) ---------

def test_install_skills_copies_each_named_skill(tmp_path):
    dsts = oc.install_skills(str(tmp_path), ["simplicio-mapper", "simplicio-fast"])
    assert len(dsts) == 2
    for d in dsts:
        assert os.path.isfile(os.path.join(d, "SKILL.md"))
    assert os.path.isdir(os.path.join(str(tmp_path), ".claude", "skills", "simplicio-mapper"))
    assert os.path.isdir(os.path.join(str(tmp_path), ".claude", "skills", "simplicio-fast"))


def test_install_skills_empty_list_installs_nothing(tmp_path):
    dsts = oc.install_skills(str(tmp_path), [])
    assert dsts == []
    assert not os.path.isdir(os.path.join(str(tmp_path), ".claude"))


def test_install_skills_is_idempotent(tmp_path):
    first = oc.install_skills(str(tmp_path), ["simplicio-dev-cli"])
    second = oc.install_skills(str(tmp_path), ["simplicio-dev-cli"])
    assert first == second


# -- provider stickiness: stable session id + opencode.json config (#1336) --


def test_session_id_for_arm_is_stable_across_calls():
    assert oc.session_id_for_arm("simplicio") == oc.session_id_for_arm("simplicio")


def test_session_id_for_arm_differs_per_arm():
    assert oc.session_id_for_arm("simplicio") != oc.session_id_for_arm("normal")


def test_write_opencode_provider_config_sets_openrouter_session_header(tmp_path):
    path = oc.write_opencode_provider_config(str(tmp_path), "simplicio")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    headers = data["provider"]["openrouter"]["options"]["headers"]
    assert headers["x-session-id"] == oc.session_id_for_arm("simplicio")


def test_write_opencode_provider_config_is_idempotent(tmp_path):
    first = oc.write_opencode_provider_config(str(tmp_path), "simplicio")
    second = oc.write_opencode_provider_config(str(tmp_path), "simplicio")
    assert first == second
    with open(first, encoding="utf-8") as f:
        data = json.load(f)
    assert data["provider"]["openrouter"]["options"]["headers"]["x-session-id"] == (
        oc.session_id_for_arm("simplicio")
    )


def test_write_opencode_provider_config_preserves_unrelated_existing_keys(tmp_path):
    config_path = os.path.join(str(tmp_path), ".config", "opencode", "opencode.json")
    os.makedirs(os.path.dirname(config_path))
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"theme": "dark", "provider": {"anthropic": {"options": {"apiKey": "x"}}}}, f)

    oc.write_opencode_provider_config(str(tmp_path), "simplicio")

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["theme"] == "dark"
    assert data["provider"]["anthropic"]["options"]["apiKey"] == "x"
    assert data["provider"]["openrouter"]["options"]["headers"]["x-session-id"] == (
        oc.session_id_for_arm("simplicio")
    )


def test_write_opencode_provider_config_different_arms_get_different_ids(tmp_path):
    p1 = oc.write_opencode_provider_config(str(tmp_path / "a"), "normal")
    p2 = oc.write_opencode_provider_config(str(tmp_path / "b"), "simplicio")
    with open(p1, encoding="utf-8") as f:
        h1 = json.load(f)["provider"]["openrouter"]["options"]["headers"]["x-session-id"]
    with open(p2, encoding="utf-8") as f:
        h2 = json.load(f)["provider"]["openrouter"]["options"]["headers"]["x-session-id"]
    assert h1 != h2


def test_run_opencode_writes_the_arm_provider_config(monkeypatch, tmp_path):
    monkeypatch.setattr(oc.measure, "run_subprocess", _fake_run_subprocess_factory(_load_fixture_events()))
    monkeypatch.setattr(oc, "fetch_key_usage_usd", lambda key, timeout=15: None)

    config_dir = str(tmp_path / "oc-home")
    oc.run_opencode(
        "simplicio", "do the thing", str(tmp_path / "repo"), key="sk-or-x", config_dir=config_dir,
        bin_path="/bin/opencode",
    )
    config_path = os.path.join(config_dir, ".config", "opencode", "opencode.json")
    assert os.path.isfile(config_path)
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["provider"]["openrouter"]["options"]["headers"]["x-session-id"] == (
        oc.session_id_for_arm("simplicio")
    )


def test_build_shim_dir_symlinks_only_the_requested_bins(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    for name in ("simplicio-mapper", "simplicio-fast", "simplicio-dev-cli", "simplicio-loop"):
        (venv_bin / name).write_text("#!/bin/sh\necho fake\n")
        os.chmod(venv_bin / name, 0o755)
    shim = oc.build_shim_dir(["simplicio-mapper"], venv_bin=str(venv_bin))
    entries = sorted(os.listdir(shim))
    assert entries == ["simplicio-mapper"]
    assert os.path.realpath(os.path.join(shim, "simplicio-mapper")) == str(venv_bin / "simplicio-mapper")


def test_build_shim_dir_skips_a_missing_binary(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    (venv_bin / "simplicio-mapper").write_text("#!/bin/sh\n")
    shim = oc.build_shim_dir(["simplicio-mapper", "simplicio-does-not-exist"], venv_bin=str(venv_bin))
    assert os.listdir(shim) == ["simplicio-mapper"]


def test_build_shim_dir_empty_bins_yields_an_empty_dir(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    shim = oc.build_shim_dir([], venv_bin=str(venv_bin))
    assert os.listdir(shim) == []


def test_build_arm_path_is_shim_plus_fixed_system_dirs(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    (venv_bin / "simplicio-mapper").write_text("#!/bin/sh\n")
    path = oc.build_arm_path(["simplicio-mapper"], venv_bin=str(venv_bin))
    parts = path.split(os.pathsep)
    assert parts[1:] == list(oc.SYSTEM_PATH_DIRS)
    assert os.path.isfile(os.path.join(parts[0], "simplicio-mapper"))


def test_build_arm_path_never_includes_venv_bin_or_usr_local_bin(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    path = oc.build_arm_path(["simplicio-mapper"], venv_bin=str(venv_bin))
    assert str(venv_bin) not in path
    assert "/usr/local/bin" not in path


def test_arm_path_resolves_exactly_the_allowed_bins_via_shutil_which(tmp_path):
    """The isolation contract from a caller's point of view: under the
    arm's PATH, ``shutil.which`` finds exactly the allowed simplicio-*
    binaries and none of the disallowed ones, even when a disallowed one
    also exists in ``/usr/local/bin`` on the real system PATH (never
    included in the isolated path at all)."""
    import shutil as _shutil

    venv_bin = tmp_path / "venv-bin"
    venv_bin.mkdir()
    all_bins = ["simplicio-mapper", "simplicio-fast", "simplicio-dev-cli", "simplicio-loop"]
    for name in all_bins:
        p = venv_bin / name
        p.write_text("#!/bin/sh\n")
        os.chmod(p, 0o755)

    allowed = ["simplicio-mapper", "simplicio-dev-cli"]
    path = oc.build_arm_path(allowed, venv_bin=str(venv_bin))

    for name in allowed:
        assert _shutil.which(name, path=path) is not None
    for name in set(all_bins) - set(allowed):
        assert _shutil.which(name, path=path) is None


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


# -- real billed cost: settled key-usage delta (fake urlopen/clock, no network) -

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


def test_poll_settled_usage_returns_the_full_delta_not_the_first_step():
    # Staircase: usage climbs in several increments before settling -- the
    # settled value must be the LAST plateau (10.0007), not the first
    # movement off the baseline (10.0002).
    series = iter([10.0002, 10.0005, 10.0007, 10.0007, 10.0007])

    def fetch():
        return next(series)

    settled = oc.poll_settled_usage(
        fetch, reads=3, interval_s=1, max_wait_s=60,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3, 4, 5, 6],
    )
    assert settled["settled"] is True
    assert round(settled["value"], 4) == 10.0007


def test_poll_settled_usage_never_settling_reports_settled_false():
    # Usage keeps drifting for the entire window -- N consecutive equal
    # reads never happen, so the caller must fall back to computed cost.
    series = iter([10.0001, 10.0002, 10.0003, 10.0004, 10.0005, 10.0006])

    def fetch():
        return next(series)

    settled = oc.poll_settled_usage(
        fetch, reads=3, interval_s=1, max_wait_s=7,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3, 4, 5, 6],
    )
    assert settled["settled"] is False
    assert settled["value"] == 10.0006  # last observed reading, never fabricated


def test_poll_settled_usage_no_successful_reads_returns_none_value():
    settled = oc.poll_settled_usage(
        lambda: None, reads=3, interval_s=1, max_wait_s=5,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3, 4, 5, 6],
    )
    assert settled["settled"] is False
    assert settled["value"] is None


def test_poll_settled_usage_settles_immediately_when_first_reads_already_equal():
    def fetch():
        return 5.0

    settled = oc.poll_settled_usage(
        fetch, reads=3, interval_s=1, max_wait_s=60,
        sleep=lambda s: None, clock_values=[0, 1, 2, 3],
    )
    assert settled == {"value": 5.0, "settled": True}


# -- run_opencode: wires the settle loop into totals["cost_usd"]/["cost_source"] --

def _fake_run_subprocess_factory(events: list[dict]):
    payload = "\n".join(json.dumps(ev) for ev in events)

    def fake(cmd, cwd=None, timeout=None, env=None):
        return payload, {"returncode": 0}

    return fake


def test_run_opencode_uses_settled_delta_as_billed_cost(monkeypatch):
    monkeypatch.setattr(oc.measure, "run_subprocess", _fake_run_subprocess_factory(_load_fixture_events()))
    # Usage climbs in steps after the run, then settles at the LAST value.
    usage_series = iter([10.0001, 10.0007, 10.0007, 10.0007])
    monkeypatch.setattr(oc, "fetch_key_usage_usd", lambda key, timeout=15: next(usage_series))

    result = oc.run_opencode(
        "normal", "do the thing", "/tmp/repo", key="sk-or-x", config_dir="/tmp/oc-home",
        bin_path="/bin/opencode", usage_baseline=10.0, settle_reads=3, settle_interval_s=0.01,
        settle_max_wait_s=5, sleep=lambda s: None,
    )
    totals = result["totals"]
    assert totals["cost_source"] == "billed-settled"
    assert round(totals["cost_usd"], 4) == 0.0007  # full settled delta, not the first step
    assert totals["billed_cost_usd"] == totals["cost_usd"]
    assert round(result["usage_settled_value"], 4) == 10.0007


def test_run_opencode_falls_back_to_opencode_reported_cost_when_usage_never_settles(monkeypatch):
    monkeypatch.setattr(oc.measure, "run_subprocess", _fake_run_subprocess_factory(_load_fixture_events()))
    usage_series = iter([10.0001, 10.0002, 10.0003, 10.0004, 10.0005, 10.0006])

    def fetch(key, timeout=15):
        return next(usage_series)

    monkeypatch.setattr(oc, "fetch_key_usage_usd", fetch)

    # Deterministic clock: exactly 6 loop iterations (matching the 6-item,
    # never-repeating series) before the settle window closes -- with a real
    # clock and a no-op `sleep`, a strictly-increasing series that later fell
    # back to a constant would eventually satisfy 3-in-a-row and falsely
    # "settle"; the fake clock proves the never-settling case without racing
    # real time.
    result = oc.run_opencode(
        "normal", "do the thing", "/tmp/repo", key="sk-or-x", config_dir="/tmp/oc-home",
        bin_path="/bin/opencode", usage_baseline=10.0, settle_reads=3, settle_interval_s=1,
        settle_max_wait_s=7, sleep=lambda s: None, clock_values=[0, 1, 2, 3, 4, 5, 6],
    )
    totals = result["totals"]
    assert totals["billed_cost_usd"] is None
    assert totals["cost_source"] == "opencode-reported"  # unchanged -- caller falls back to computed cost
    # the last observed (unsettled) reading is still carried, for the next task's baseline
    assert result["usage_settled_value"] == 10.0006
