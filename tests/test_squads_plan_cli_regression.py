"""Regression tests for Issue #1803: squads plan --issues input formats.

Proves:
1. `simplicio-loop squads plan --issues <file.json>` successfully reads from a file path.
2. Accepts `{"issues": [...]}` or `[...]` inside the file.
3. Still supports stdin '-' and inline JSON strings.
4. When parsing fails or format is invalid, provides a clear error message explaining
   the accepted formats (`file path, '-' for stdin, or inline JSON`) and the expected
   fields (`number`, `title`, `body`, `labels`, `depends_on`, `paths`).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from simplicio_loop import cli_impl

ISSUES_SAMPLE = [
    {"number": 101, "title": "Setup db", "body": "initial migrations", "labels": ["backend"], "paths": ["db/**"]},
    {"number": 102, "title": "Add api endpoints", "body": "depends on #101", "labels": ["api"], "depends_on": [101], "paths": ["api/**"]},
]


def _run(capsys, *argv):
    code = cli_impl.main(list(argv))
    out_text = capsys.readouterr().out
    try:
        data = json.loads(out_text)
    except Exception:
        data = out_text
    return code, data


def test_plan_from_file_path(tmp_path, capsys):
    """A .json file path passed to --issues is successfully read and planned."""
    issues_file = tmp_path / "issues.json"
    issues_file.write_text(json.dumps(ISSUES_SAMPLE), encoding="utf-8")

    code, out = _run(capsys, "squads", "plan", "--issues", str(issues_file), "--json")
    assert code == 0
    assert out["schema"] == "simplicio.squad-plan/v1"
    assert [m["issue"] for m in out["merge_order"]] == [101, 102]


def test_plan_from_file_path_wrapped_in_dict(tmp_path, capsys):
    """A .json file containing {'issues': [...]} is also accepted."""
    issues_file = tmp_path / "wrapped_issues.json"
    issues_file.write_text(json.dumps({"issues": ISSUES_SAMPLE}), encoding="utf-8")

    code, out = _run(capsys, "squads", "plan", "--issues", str(issues_file), "--json")
    assert code == 0
    assert out["schema"] == "simplicio.squad-plan/v1"
    assert [m["issue"] for m in out["merge_order"]] == [101, 102]


def test_plan_from_stdin(capsys, monkeypatch):
    """Using '-' reads issues from stdin."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(ISSUES_SAMPLE)))
    code, out = _run(capsys, "squads", "plan", "--issues", "-", "--json")
    assert code == 0
    assert out["schema"] == "simplicio.squad-plan/v1"
    assert [m["issue"] for m in out["merge_order"]] == [101, 102]


def test_plan_from_inline_json(capsys):
    """Inline JSON string continues to work."""
    code, out = _run(capsys, "squads", "plan", "--issues", json.dumps(ISSUES_SAMPLE), "--json")
    assert code == 0
    assert out["schema"] == "simplicio.squad-plan/v1"
    assert [m["issue"] for m in out["merge_order"]] == [101, 102]


def test_malformed_json_in_file_gives_clear_error(tmp_path, capsys):
    """When a file contains invalid JSON, the error clearly states accepted formats and expected fields."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json { broken", encoding="utf-8")

    code, out = _run(capsys, "squads", "plan", "--issues", str(bad_file), "--json")
    assert code == 2
    assert out["status"] == "BLOCKED"
    assert out["error"] == "SquadPlanError"
    reason = out["reason"]
    assert "file path, '-' for stdin, or inline JSON" in reason
    for field in ("number", "title", "body", "labels", "depends_on", "paths"):
        assert field in reason


def test_missing_json_file_gives_clear_error(tmp_path, capsys):
    """When a .json file does not exist, the error explains accepted formats and expected fields."""
    missing_file = tmp_path / "nonexistent_issues.json"

    code, out = _run(capsys, "squads", "plan", "--issues", str(missing_file), "--json")
    assert code == 2
    assert out["status"] == "BLOCKED"
    assert out["error"] == "SquadPlanError"
    reason = out["reason"]
    assert "file path, '-' for stdin, or inline JSON" in reason
    for field in ("number", "title", "body", "labels", "depends_on", "paths"):
        assert field in reason


def test_invalid_structure_gives_clear_error(capsys):
    """When JSON is valid but not a list of objects, the error explains expected fields."""
    code, out = _run(capsys, "squads", "plan", "--issues", json.dumps(["just", "strings"]), "--json")
    assert code == 2
    assert out["status"] == "BLOCKED"
    assert out["error"] == "SquadPlanError"
    reason = out["reason"]
    assert "file path, '-' for stdin, or inline JSON" in reason
    for field in ("number", "title", "body", "labels", "depends_on", "paths"):
        assert field in reason
