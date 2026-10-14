"""Real-git benchmark of serial integration vs the merge train (#1504, criterion 5)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_merge_train.py"


def _run(*args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repeats", "1", *args],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_green_schema_and_fewer_smoke_runs_in_train():
    report = _run("--n", "4")
    assert report["proof_kind"] == "MEASURED"
    assert "NOT escalation rate" in report["scope"] and "UNVERIFIED" in report["scope"]
    assert report["n"] == 4 and report["bad_prs"] == [] and report["repeats"] == 1
    for mode in ("serial", "train"):
        m = report[mode]
        assert len(m["wall_ms"]) == 1 and m["wall_ms"][0] > 0
        assert m["median_wall_ms"] == m["wall_ms"][0]
        assert m["merges"] == 4
        assert m["merged_prs"] == [1, 2, 3, 4] and m["unmerged_prs"] == []
        assert {"smoke_runs", "bisect_steps"} <= set(m)
    assert report["serial"]["smoke_runs"] == 4
    assert report["serial"]["bisect_steps"] == 0
    assert 1 <= report["train"]["smoke_runs"] < report["serial"]["smoke_runs"]
    assert report["train"]["bisect_steps"] == 0
    # speedup is derived only from the measured medians
    assert report["speedup"] == report["serial"]["median_wall_ms"] / report["train"]["median_wall_ms"]


def test_bad_pr_is_left_unmerged_by_train_and_serial():
    report = _run("--n", "4", "--bad", "1")
    (culprit,) = report["bad_prs"]
    good = [p for p in (1, 2, 3, 4) if p != culprit]
    for mode in ("serial", "train"):
        assert report[mode]["unmerged_prs"] == [culprit]
        assert report[mode]["merged_prs"] == good
        assert report[mode]["merges"] == 3
    assert report["serial"]["smoke_runs"] == 4
    assert report["train"]["bisect_steps"] >= 1
