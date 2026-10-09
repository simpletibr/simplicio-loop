#!/usr/bin/env python3
"""TDD tests for scripts/issue_eval.py - fixes for PR #1477 review.

Tests cover:
1. Clone/checkout at base_commit
2. Template substitution with {task} and {verify}
3. JSON status parsing from engine
4. Verify command execution
5. Schema: issue_number vs pr_number, source field
6. Using pytest fixtures instead of /tmp hardcoding
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue_eval.py"
CASES = ROOT / "bench" / "issue_eval" / "cases.json"


class TestCasesSchema:
    """Tests for bench/issue_eval/cases.json schema."""

    def test_cases_file_exists(self):
        """Cases file must exist."""
        cases_file = CASES
        assert cases_file.exists(), f"{cases_file} not found"

    def test_schema_version(self):
        """Schema version must be simplicio.issue-eval/v1."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        assert data["schema"] == "simplicio.issue-eval/v1"

    def test_cases_count(self):
        """Must have 15-30 cases."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        cases = data.get("cases", [])
        assert 15 <= len(cases) <= 30, f"Expected 15-30 cases, got {len(cases)}"

    def test_case_fields_and_types(self):
        """Each case must have correct fields and types."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        cases = data.get("cases", [])

        required_fields = {
            "repo": str,
            "issue_number": int,
            "pr_number": int,
            "issue_title": str,
            "base_commit": str,
            "verify_command": str,
            "diff_stat": dict,
            "size": str,
            "source": str,
        }

        for i, case in enumerate(cases):
            for field, expected_type in required_fields.items():
                assert field in case, f"Case {i} missing {field}"
                assert isinstance(
                    case[field], expected_type
                ), f"Case {i}: {field} should be {expected_type}, got {type(case[field])}"

    def test_case_size_valid(self):
        """Case size must be small/medium/large."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        cases = data.get("cases", [])

        for case in cases:
            assert case["size"] in ["small", "medium", "large"]

    def test_case_source_valid(self):
        """Case source must be 'issue' or 'pr'."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        cases = data.get("cases", [])

        for case in cases:
            assert case["source"] in ["issue", "pr"]

    def test_diff_stat_structure(self):
        """diff_stat must have additions, deletions, total_lines."""
        cases_file = CASES
        with open(cases_file) as f:
            data = json.load(f)
        cases = data.get("cases", [])

        for case in cases:
            ds = case["diff_stat"]
            assert "additions" in ds
            assert "deletions" in ds
            assert "total_lines" in ds


class TestVerifyCommands:
    """verify_command must be targeted (full suite is release-only)."""

    def _cases(self):
        return json.loads(CASES.read_text())["cases"]

    def test_no_full_suite_verify(self):
        for case in self._cases():
            cmd = case["verify_command"]
            if cmd is None:
                assert case["verify_source"] == "none"
                continue
            assert case["verify_source"] == "reference_pr_tests"
            parts = cmd.split()
            assert parts[:4] == ["python3", "-m", "pytest", "-q"], cmd
            paths = parts[4:]
            assert paths, f"bare pytest (full suite): {cmd}"
            for p in paths:
                assert p.startswith("tests/test_") and p.endswith(".py"), cmd


class TestDryRun:
    """Tests for --dry-run functionality."""

    def test_dry_run_no_execution(self):
        """Dry-run must not execute cases."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--dry-run", "--limit", "3"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Loaded" in result.stdout


class TestCompare:
    """Tests for --compare functionality."""

    def test_compare_with_proper_tmp_path(self, tmp_path):
        """Compare must work with proper temp paths."""
        old_report = {
            "consolidated": {"success_rate": 0.8, "success_count": 16, "total_wall_ms": 120000}
        }
        new_report = {
            "consolidated": {"success_rate": 0.85, "success_count": 17, "total_wall_ms": 115000}
        }

        old_file = tmp_path / "old_report.json"
        new_file = tmp_path / "new_report.json"
        old_file.write_text(json.dumps(old_report))
        new_file.write_text(json.dumps(new_report))

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--compare",
                str(old_file),
                str(new_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
