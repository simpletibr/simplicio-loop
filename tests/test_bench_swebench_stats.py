"""bench/swebench seeded bootstrap (#1819): the CI algorithm is fixed, documented and reproducible."""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench" / "swebench"))

import swe_stats as st


def _mean(units):
    return sum(u[0] for u in units) / len(units)


def _reference_ci(units, fn, seed, resamples, confidence):
    """Independent re-statement of the documented algorithm (random.Random(seed).random() only)."""
    rng = random.Random(seed)
    n = len(units)
    vals = []
    for _ in range(resamples):
        sample = [units[int(rng.random() * n)] for _ in range(n)]
        v = fn(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    m = len(vals)
    alpha = 1.0 - confidence
    lo = vals[math.floor(alpha / 2.0 * m)]
    hi = vals[min(m - 1, math.ceil((1.0 - alpha / 2.0) * m) - 1)]
    return lo, hi


UNITS = [(1.0,), (0.0,), (1.0,), (1.0,), (0.0,), (0.0,), (1.0,), (0.0,), (1.0,), (1.0,)]


def test_bootstrap_matches_the_documented_algorithm_exactly():
    got = st.bootstrap(UNITS, {"mean": _mean}, seed=7, resamples=500, confidence=0.95)["mean"]
    lo, hi = _reference_ci(UNITS, _mean, 7, 500, 0.95)
    assert (got["lo"], got["hi"]) == (lo, hi)
    assert got["est"] == pytest.approx(0.6)
    assert got["resamples"] == 500 and got["undefined"] == 0


def test_same_seed_same_ci_and_a_different_seed_moves_it():
    walls = [(float(i) ** 1.5,) for i in range(1, 21)]  # continuous statistic: bounds depend on the stream
    a = st.bootstrap(walls, {"m": _mean}, seed=1, resamples=300)["m"]
    b = st.bootstrap(walls, {"m": _mean}, seed=1, resamples=300)["m"]
    c = st.bootstrap(walls, {"m": _mean}, seed=2, resamples=300)["m"]
    assert a == b
    assert (a["lo"], a["hi"]) != (c["lo"], c["hi"])


def test_ci_brackets_the_point_estimate_and_stays_in_range_for_a_pass_rate():
    units = [(1.0,)] * 15 + [(0.0,)] * 15
    r = st.bootstrap(units, {"m": _mean}, seed=1819, resamples=2000)["m"]
    assert r["lo"] <= r["est"] <= r["hi"]
    assert 0.0 <= r["lo"] and r["hi"] <= 1.0
    # 15/30: the 95% percentile interval is roughly +-0.18; loose bounds guard against a broken resampler
    assert 0.28 < r["lo"] < 0.40 and 0.60 < r["hi"] < 0.72


def test_degenerate_samples_give_a_zero_width_interval():
    r = st.bootstrap([(1.0,)] * 30, {"m": _mean}, seed=3, resamples=200)["m"]
    assert (r["lo"], r["est"], r["hi"]) == (1.0, 1.0, 1.0)


def test_undefined_resamples_are_dropped_and_counted_never_zero_filled():
    # ratio of sums is undefined (None) when no unit in the resample has a solve
    def cps(units):
        solved = sum(u[0] for u in units)
        return None if solved == 0 else sum(u[1] for u in units) / solved

    units = [(1.0, 5.0)] + [(0.0, 5.0)] * 9
    r = st.bootstrap(units, {"cps": cps}, seed=11, resamples=400)["cps"]
    assert r["undefined"] > 0  # many resamples miss the single solve
    assert r["est"] == pytest.approx(50.0)
    assert r["lo"] is not None and r["lo"] > 0


def test_all_resamples_undefined_yields_none_bounds():
    r = st.bootstrap([(0.0, 1.0)] * 10, {"cps": lambda u: None}, seed=1, resamples=50)["cps"]
    assert r["est"] is None and r["lo"] is None and r["hi"] is None and r["undefined"] == 50


def test_several_statistics_share_one_resample_stream():
    both = st.bootstrap(UNITS, {"a": _mean, "b": _mean}, seed=9, resamples=200)
    assert both["a"] == both["b"]
    solo = st.bootstrap(UNITS, {"a": _mean}, seed=9, resamples=200)["a"]
    assert solo == both["a"]


def test_empty_input_is_an_error():
    with pytest.raises(ValueError):
        st.bootstrap([], {"m": _mean}, seed=1)


def test_confidence_must_be_between_zero_and_one():
    with pytest.raises(ValueError):
        st.bootstrap(UNITS, {"m": _mean}, seed=1, confidence=1.5)
