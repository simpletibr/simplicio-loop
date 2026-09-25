from __future__ import annotations

from importlib import util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_415_verification_benchmark.py"


def test_issue_415_benchmark_has_all_pack_sizes_and_writer_lanes():
    spec = util.spec_from_file_location("issue_415_verification_benchmark", SCRIPT)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_benchmark()
    assert report["schema"] == "simplicio.dev-cli.issue-415-verification-benchmark/v1"
    assert report["repeats"] == 10
    assert {(row["pack"], row["writers"]) for row in report["rows"]} == {
        (pack, writers) for pack in ("small", "medium", "large") for writers in (1, 5, 10)
    }
    assert all(row["worktrees"] == row["writers"] for row in report["rows"])
    assert all(row["causal"]["files_hashed"] == 1 for row in report["rows"])
    assert all(row["causal_concurrent"]["files_hashed"] == row["worktrees"] for row in report["rows"])
