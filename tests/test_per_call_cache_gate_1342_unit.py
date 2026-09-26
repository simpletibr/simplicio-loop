"""issue #1342: the bench fails a simplicio run when any call after the first
of a task has ``cached_tokens == 0``, naming the first cold call."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench" / "llm_ab"))

import report  # noqa: E402
import standard  # noqa: E402


def _arms(calls):
    return {"simplicio": {"tasks": [{"index": 1, "llm_calls": calls}]}}


def test_warm_calls_after_the_first_pass():
    arms = _arms([
        {"turn": 1, "prompt_tokens": 9000, "cached_tokens": 0},
        {"turn": 2, "prompt_tokens": 9500, "cached_tokens": 8000},
    ])
    assert report.first_cold_call(arms) is None
    assert "OK" in report.build_cold_call_note(arms)


def test_cold_call_after_turn_one_fails_and_is_named():
    arms = _arms([
        {"turn": 1, "prompt_tokens": 9000, "cached_tokens": 0},
        {"turn": 2, "prompt_tokens": 9500, "cached_tokens": 8000},
        {"turn": 3, "prompt_tokens": 9700, "cached_tokens": 0},
    ])
    cold = report.first_cold_call(arms)
    assert cold["task"] == 1 and cold["turn"] == 3
    assert "FALHOU" in report.build_cold_call_note(arms)


def test_standard_gate_exits_nonzero_on_a_cold_call(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"arms": _arms([
        {"turn": 1, "prompt_tokens": 9000, "cached_tokens": 0},
        {"turn": 2, "prompt_tokens": 9500, "cached_tokens": 0},
    ])}), encoding="utf-8")
    assert standard.per_call_cache_gate([("t1-seq", str(path))]) == 3


def test_standard_gate_passes_when_warm(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"arms": _arms([
        {"turn": 1, "prompt_tokens": 9000, "cached_tokens": 0},
        {"turn": 2, "prompt_tokens": 9500, "cached_tokens": 9000},
    ])}), encoding="utf-8")
    assert standard.per_call_cache_gate([("t1-seq", str(path))]) == 0
