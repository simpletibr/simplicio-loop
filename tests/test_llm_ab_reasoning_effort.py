"""TDD unit tests for per-phase reasoning-effort support in the LLM A/B
benchmark harness (bench/llm_ab): `llm_client.chat`'s optional
`reasoning_effort` param, `agent.parse_effort_hint`'s hint extraction from a
simplicio tool output, and the hint-driven policy wired into `agent.run_agent`.
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import agent  # noqa: E402
import llm_client as lc  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_keys(tmp_path, monkeypatch):
    keys_file = tmp_path / "keys.env"
    keys_file.write_text("OR_KEY_NORMAL=k-normal\nOR_KEY_SIMPLICIO=k-simplicio\n")
    monkeypatch.setenv(lc.KEYS_PATH_ENV, str(keys_file))


def _capture_request_body(tmp_path, monkeypatch, **chat_kwargs):
    _install_keys(tmp_path, monkeypatch)
    captured = {}

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        resp_body = json.dumps({
            "id": "gen-1", "model": lc.MODEL, "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }).encode("utf-8")
        return FakeResponse(resp_body, 200)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    lc.chat("normal", [{"role": "user", "content": "hi"}], **chat_kwargs)
    return captured["body"]


def test_chat_omits_reasoning_field_when_effort_not_set(tmp_path, monkeypatch):
    body = _capture_request_body(tmp_path, monkeypatch)
    assert "reasoning" not in body


def test_chat_sends_reasoning_effort_when_set(tmp_path, monkeypatch):
    body = _capture_request_body(tmp_path, monkeypatch, reasoning_effort="high")
    assert body["reasoning"] == {"effort": "high"}


def test_chat_omits_reasoning_field_for_none_explicitly(tmp_path, monkeypatch):
    body = _capture_request_body(tmp_path, monkeypatch, reasoning_effort=None)
    assert "reasoning" not in body


# -- agent.parse_effort_hint --------------------------------------------------

def test_parse_effort_hint_none_for_plain_text():
    assert agent.parse_effort_hint("no output here") is None
    assert agent.parse_effort_hint(None) is None
    assert agent.parse_effort_hint("") is None


def test_parse_effort_hint_from_orient_brief_effort_plan():
    text = json.dumps({"schema": "simplicio.loop-orient-brief/v1",
                        "effort": {"plan": "high", "execute": "low", "review": "medium"}})
    assert agent.parse_effort_hint(text) == "high"


def test_parse_effort_hint_from_apply_next_effort():
    text = json.dumps({"schema": "simplicio.loop-apply/v1", "status": "PASS", "next_effort": "medium"})
    assert agent.parse_effort_hint(text) == "medium"


def test_parse_effort_hint_next_effort_takes_priority_over_effort_plan():
    text = json.dumps({"next_effort": "low", "effort": {"plan": "high"}})
    assert agent.parse_effort_hint(text) == "low"


def test_parse_effort_hint_ignores_invalid_effort_values():
    text = json.dumps({"next_effort": "extreme"})
    assert agent.parse_effort_hint(text) is None


def test_parse_effort_hint_tolerates_json_embedded_in_other_text():
    text = "wrote ops.json\n" + json.dumps({"next_effort": "low"}) + "\ndone"
    assert agent.parse_effort_hint(text) == "low"


def test_parse_effort_hint_none_for_malformed_json():
    assert agent.parse_effort_hint("{not json}") is None


# -- agent.run_agent honoring hints -------------------------------------------

def test_run_agent_hints_policy_sends_no_reasoning_until_a_hint_is_seen(monkeypatch, tmp_path):
    """No simplicio-shaped tool output yet -> no reasoning param sent (model
    default) -- the normal arm's natural path."""
    seen_efforts = []

    def fake_chat(arm, messages, temperature=0, tools=None, reasoning_effort=None):
        seen_efforts.append(reasoning_effort)
        return {
            "ok": True, "id": "g1", "message": {"role": "assistant", "content": "DONE"},
            "latency_s": 0.01, "prompt_tokens": 1, "completion_tokens": 1,
            "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": "stop",
        }

    monkeypatch.setattr(agent.lc, "chat", fake_chat)
    agent.run_agent("normal", "sys", "task", str(tmp_path), max_turns=3, cmd_timeout=5)
    assert seen_efforts == [None]


def test_run_agent_hints_policy_uses_the_most_recent_hint_from_tool_output(monkeypatch, tmp_path):
    """Turn 1: no hint yet. Turn 1's bash tool prints an orient --brief
    payload with effort.plan=high. Turn 2's LLM call must then be asked at
    ``high``."""
    seen_efforts = []
    turn = {"n": 0}

    def fake_chat(arm, messages, temperature=0, tools=None, reasoning_effort=None):
        turn["n"] += 1
        seen_efforts.append(reasoning_effort)
        if turn["n"] == 1:
            return {
                "ok": True, "id": "g1", "message": {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "function": {
                        "name": "bash", "arguments": '{"command": "simplicio-loop orient --brief --task x --json"}',
                    }}],
                },
                "latency_s": 0.01, "prompt_tokens": 1, "completion_tokens": 1,
                "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": "tool_calls",
            }
        return {
            "ok": True, "id": "g2", "message": {"role": "assistant", "content": "DONE"},
            "latency_s": 0.01, "prompt_tokens": 1, "completion_tokens": 1,
            "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": "stop",
        }

    def fake_run_subprocess(cmd, cwd, timeout, env):
        payload = json.dumps({"schema": "simplicio.loop-orient-brief/v1",
                               "effort": {"plan": "high", "execute": "low", "review": "medium"}})
        return payload, {"returncode": 0, "wall_s": 0.01, "cpu_s": 0.01, "peak_rss_mb": None}

    monkeypatch.setattr(agent.lc, "chat", fake_chat)
    monkeypatch.setattr(agent.measure, "run_subprocess", fake_run_subprocess)
    result = agent.run_agent("simplicio", "sys", "/simplicio-loop task", str(tmp_path), max_turns=5, cmd_timeout=5)
    assert seen_efforts == [None, "high"]
    assert result["llm_calls"][0]["reasoning_effort"] is None
    assert result["llm_calls"][1]["reasoning_effort"] == "high"


def test_run_agent_effort_policy_none_never_sends_a_hint(monkeypatch, tmp_path):
    seen_efforts = []
    turn = {"n": 0}

    def fake_chat(arm, messages, temperature=0, tools=None, reasoning_effort=None):
        turn["n"] += 1
        seen_efforts.append(reasoning_effort)
        if turn["n"] == 1:
            return {
                "ok": True, "id": "g1", "message": {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": '{"command": "x"}'}}],
                },
                "latency_s": 0.01, "prompt_tokens": 1, "completion_tokens": 1,
                "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": "tool_calls",
            }
        return {
            "ok": True, "id": "g2", "message": {"role": "assistant", "content": "DONE"},
            "latency_s": 0.01, "prompt_tokens": 1, "completion_tokens": 1,
            "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "finish_reason": "stop",
        }

    def fake_run_subprocess(cmd, cwd, timeout, env):
        payload = json.dumps({"next_effort": "medium"})
        return payload, {"returncode": 0, "wall_s": 0.01, "cpu_s": 0.01, "peak_rss_mb": None}

    monkeypatch.setattr(agent.lc, "chat", fake_chat)
    monkeypatch.setattr(agent.measure, "run_subprocess", fake_run_subprocess)
    agent.run_agent("simplicio", "sys", "task", str(tmp_path), max_turns=5, cmd_timeout=5, effort_policy="none")
    assert seen_efforts == [None, None]
