"""TDD unit tests for bench/llm_ab/verdict.py.

The verdict text must be computed purely from the `results` dict handed to
it -- these tests plant distinctive numbers and assert they, and only they,
show up (guards against a hardcoded verdict string creeping back in).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import verdict as bench_verdict  # noqa: E402


def _results(arms):
    return {"arms": arms}


def test_verdict_mentions_every_arm_name():
    results = _results({
        "normal": {"tasks": [{"success": True, "attempts": []}], "total_wall_s": 1.0},
        "simplicio-files": {"tasks": [{"success": True, "attempts": []}], "total_wall_s": 2.0},
        "simplicio-fast": {"tasks": [{"success": True, "attempts": []}], "total_wall_s": 3.0},
    })
    text = bench_verdict.compute_verdict(results)
    for name in ("normal", "simplicio-files", "simplicio-fast"):
        assert name in text


def test_verdict_reflects_actual_success_counts():
    results = _results({
        "arm-a": {"tasks": [{"success": True, "attempts": []}, {"success": False, "attempts": []}],
                  "total_wall_s": 9.0},
    })
    text = bench_verdict.compute_verdict(results)
    assert "1/2" in text


def test_verdict_reflects_actual_wall_time():
    results = _results({
        "arm-a": {"tasks": [{"success": True, "attempts": []}], "total_wall_s": 42.7},
    })
    text = bench_verdict.compute_verdict(results)
    assert "42.7" in text


def test_verdict_reflects_actual_cost():
    results = _results({
        "arm-a": {
            "tasks": [{
                "success": True,
                "attempts": [{"llm_call": {"cost_usd": 0.01234}}],
            }],
            "total_wall_s": 1.0,
        },
    })
    text = bench_verdict.compute_verdict(results)
    assert "0.01234" in text


def test_verdict_changes_when_data_changes():
    a = _results({"arm-a": {"tasks": [{"success": True, "attempts": []}], "total_wall_s": 1.0}})
    b = _results({"arm-a": {"tasks": [{"success": False, "attempts": []}], "total_wall_s": 99.0}})
    assert bench_verdict.compute_verdict(a) != bench_verdict.compute_verdict(b)


def test_verdict_handles_no_arms():
    assert bench_verdict.compute_verdict({"arms": {}}) == "sem dados suficientes para veredito"


def test_verdict_handles_missing_wall_time_gracefully():
    results = _results({"arm-a": {"tasks": [{"success": True, "attempts": []}]}})
    text = bench_verdict.compute_verdict(results)
    assert "n/d" in text
