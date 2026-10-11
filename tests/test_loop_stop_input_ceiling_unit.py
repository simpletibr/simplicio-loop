"""The Stop hook warns the agent to hand off at the soft share of the input ceiling (#1608, part D)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HOOK = Path(__file__).parents[1] / "hooks" / "loop_stop.py"
CEILING = 98_000
SOFT = 88_200  # 90 % of CEILING


def load_hook():
    spec = importlib.util.spec_from_file_location("loop_stop_input_ceiling", HOOK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ceiling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_AGENT_INPUT_TOKEN_CEILING", str(CEILING))


def transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return str(path)


def assistant_usage(input_tokens):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                                              "usage": {"input_tokens": input_tokens, "cache_read_input_tokens": 0,
                                                        "cache_creation_input_tokens": 0, "output_tokens": 5}}}


def test_measured_input_at_the_soft_share_warns(tmp_path, ceiling):
    path = transcript(tmp_path, [assistant_usage(SOFT)])
    hint = load_hook().input_ceiling_hint({"transcript_path": path})
    assert "MEASURED" in hint
    assert "%d of %d tokens" % (SOFT, CEILING) in hint
    assert "at least 90% of the ceiling" in hint
    assert "simplicio-loop handoff write" in hint


def test_measured_input_below_the_soft_share_does_not_warn(tmp_path, ceiling):
    path = transcript(tmp_path, [assistant_usage(SOFT - 1)])
    assert load_hook().input_ceiling_hint({"transcript_path": path}) == ""


def test_a_host_without_measured_usage_warns_as_estimated(tmp_path, ceiling):
    long_turn = {"type": "user", "message": {"role": "user", "content": "hello " * 80_000}}
    path = transcript(tmp_path, [long_turn])
    hint = load_hook().input_ceiling_hint({"transcript_path": path})
    assert "ESTIMATED" in hint
    assert "no measured usage" in hint
    assert "MEASURED" not in hint
    assert "simplicio-loop handoff write" in hint
