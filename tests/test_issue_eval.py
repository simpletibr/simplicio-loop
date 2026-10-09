#!/usr/bin/env python3
"""Tests for scripts/issue_eval.py"""

import json
import subprocess
import sys
from pathlib import Path


def test_cases_schema():
    """Validate bench/issue_eval/cases.json schema."""
    cases_file = Path("bench/issue_eval/cases.json")
    assert cases_file.exists(), f"{cases_file} not found"

    with open(cases_file) as f:
        data = json.load(f)

    assert data["schema"] == "simplicio.issue-eval/v1"
    cases = data.get("cases", [])
    assert len(cases) >= 15, "Need at least 15 cases"
    assert len(cases) <= 30, "Too many cases"

    for case in cases:
        assert "repo" in case
        assert "issue_number" in case
        assert "pr_number" in case
        assert "issue_title" in case
        assert "base_commit" in case
        assert "verify_command" in case
        assert "diff_stat" in case
        assert "size" in case
        assert "source" in case
        assert case["size"] in ["small", "medium", "large"]
        assert case["source"] in ["issue", "pr"]
        assert isinstance(case["issue_number"], int)
        assert isinstance(case["pr_number"], int)

    sizes = [c["size"] for c in cases]
    assert "small" in sizes
    assert "medium" in sizes
    assert "large" in sizes
    print(f"PASS: {len(cases)} cases validated")


def test_dry_run():
    """Test dry-run functionality."""
    result = subprocess.run(
        [sys.executable, "scripts/issue_eval.py", "--dry-run", "--limit", "5"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    assert "Loaded" in result.stdout
    assert "small" in result.stdout or "medium" in result.stdout or "large" in result.stdout
    print("PASS: dry-run works")


def test_compare():
    """Test compare functionality with fake reports."""
    old_report = {
        "consolidated": {
            "success_rate": 0.8,
            "success_count": 16,
            "total_wall_ms": 120000,
        }
    }
    new_report = {
        "consolidated": {
            "success_rate": 0.85,
            "success_count": 17,
            "total_wall_ms": 115000,
        }
    }

    old_file = Path("/tmp/old_report.json")
    new_file = Path("/tmp/new_report.json")
    old_file.write_text(json.dumps(old_report))
    new_file.write_text(json.dumps(new_report))

    result = subprocess.run(
        [sys.executable, "scripts/issue_eval.py", "--compare", str(old_file), str(new_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "80.0%" in result.stdout or "0.8" in result.stdout
    assert "85.0%" in result.stdout or "0.85" in result.stdout
    print("PASS: compare works")


if __name__ == "__main__":
    test_cases_schema()
    test_dry_run()
    test_compare()
    print("All tests passed!")
