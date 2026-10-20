"""Regression tests for Issue #1808:
[install] dry-run output repeats paths and is unclear; stale project-scope copies are kept.

Verifies:
- Paths in `owned ->` are deduplicated.
- Explanations of `stale` and `resynced` with per-host counts.
- Long lists of files (`left alone`) are truncated at clean word/path boundaries.
- Support for `--prune-project-copies` in `install --global` to detect and remove
  obsolete project-scope copies while preserving foreign user files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, setup_cli
from simplicio_loop.cli_impl import _install_lines, install
from simplicio_loop.install import planner


def test_owned_paths_deduplicated_in_planner_and_install_lines(tmp_path):
    """Verify that apply_plan and _install_lines deduplicate owned files."""
    plan = {
        "target": str(tmp_path),
        "version": "1.0.0",
        "digest": "sha256:fake",
        "actions": [
            # Two actions pointing to the same destination (e.g. multi-host layout)
            {"host": "claude", "kind": "entry", "destination": "AGENTS.md"},
            {"host": "grok", "kind": "entry", "destination": "AGENTS.md"},
        ],
    }
    (tmp_path / "skills").mkdir()
    (tmp_path / "hooks").mkdir()
    result = planner.apply_plan(plan, dry_run=True, bundle=tmp_path)
    # Planner output should have deduplicated owned list (the state folder's .gitignore is owned too)
    assert result["owned"] == [".simplicio-loop/.gitignore", "AGENTS.md"]

    # Even if result had duplicates injected, _install_lines deduplicates
    result_with_dups = {
        "owned": ["AGENTS.md", "AGENTS.md", "file2.txt", "file2.txt"],
        "changes": {"created": ["AGENTS.md"], "updated": [], "unchanged": 0, "left_alone": []},
    }
    lines = _install_lines(result_with_dups, "all", "dry_run (nothing written)", None)
    owned_line = next(line for line in lines if "owned  ->" in line)
    assert "owned  -> 2 files" in owned_line


def test_stale_explanation_and_per_host_counts_in_dry_run():
    """Verify that dry-run/check explains 'stale' meaning and displays per-host count."""
    result = {
        "owned": ["f1.txt"],
        "changes": {"created": [], "updated": [], "unchanged": 1, "left_alone": []},
    }
    resync = {
        "skills": ["claude", "cursor"],
        "rules": ["claude_rules"],
        "skills_counts": {"claude": 2, "cursor": 1},
        "rules_counts": {"claude_rules": 1},
        "errors": [],
    }
    lines = _install_lines(result, "claude", "dry_run (nothing written)", resync)
    stale_line = next(line for line in lines if "stale (" in line)

    # Explanation must clarify what stale means
    assert "installed host copies differing from package, pending update" in stale_line
    # Count per host must be shown
    assert "claude (2)" in stale_line
    assert "cursor (1)" in stale_line
    assert "claude_rules (1)" in stale_line


def test_resynced_explanation_and_per_host_counts_on_install():
    """Verify that applied install explains 'resynced' meaning and displays per-host count."""
    result = {
        "owned": ["f1.txt"],
        "changes": {"created": ["f1.txt"], "updated": [], "unchanged": 0, "left_alone": []},
    }
    resync = {
        "skills": ["claude"],
        "rules": ["claude_rules"],
        "skills_counts": {"claude": 3},
        "rules_counts": {"claude_rules": 1},
        "errors": [],
    }
    lines = _install_lines(result, "claude", "installed", resync)
    resynced_line = next(line for line in lines if "resynced (" in line)

    # Explanation must clarify what resynced means
    assert "installed host copies refreshed to match package" in resynced_line
    assert "claude (3)" in resynced_line
    assert "claude_rules (1)" in resynced_line


def test_left_alone_clean_word_limit_truncation():
    """Verify that long lists of left_alone files are truncated cleanly on path boundaries."""
    left_alone = [
        "some/deeply/nested/custom_user_skill_number_one/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_two/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_three/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_four/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_five/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_six/SKILL.md",
        "some/deeply/nested/custom_user_skill_number_seven/SKILL.md",
    ]
    result = {
        "owned": ["f1.txt"],
        "changes": {"created": [], "updated": [], "unchanged": 1, "left_alone": left_alone},
    }
    lines = _install_lines(result, "claude", "dry_run (nothing written)", None)
    left_line = next(line for line in lines if "left alone ->" in line)

    # Check total count
    assert "7 not owned by Loop" in left_line
    # Must have (+N more) truncation
    assert "(+" in left_line and "more)" in left_line
    # Path names must never be split in the middle of words
    assert not left_line.endswith("custom_user_skil...")


def test_prune_project_copies_dry_run_and_apply(tmp_path):
    """Verify prune_project_copies detects and cleans legacy copies while preserving foreign files."""
    project = tmp_path / "my_project"
    project.mkdir()

    # Create stale project-scope Loop files
    skill_dir = project / ".claude" / "skills" / "simplicio-loop"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("old skill")

    rule_dir = project / ".claude" / "rules"
    rule_dir.mkdir(parents=True)
    (rule_dir / "simplicio-loop-operator-flow.md").write_text("old rule")

    hook_dir = project / "hooks"
    hook_dir.mkdir(parents=True)
    (hook_dir / "loop_stop.py").write_text("# old hook")

    simplicio_dir = project / ".simplicio-loop"
    simplicio_dir.mkdir(parents=True)
    (simplicio_dir / "install-ownership.json").write_text(json.dumps({
        "schema": "simplicio.loop-install-ownership/v2",
        "owner": "simplicio-loop",
        "paths": [".claude/skills/simplicio-loop/SKILL.md"],
        "dirs": [".claude/skills/simplicio-loop"],
    }))

    # Create a FOREIGN user file that must be preserved
    (project / ".claude" / "settings.json").write_text('{"user": "config"}')
    (project / "hooks" / "my_custom_hook.py").write_text("# keep me")

    # 1. Dry run: detects files without deleting
    dry_result = planner.prune_project_copies(project, dry_run=True)
    assert dry_result["status"] == "dry_run"
    assert ".claude/skills/simplicio-loop/SKILL.md" in dry_result["removed"]
    assert ".claude/rules/simplicio-loop-operator-flow.md" in dry_result["removed"]
    assert "hooks/loop_stop.py" in dry_result["removed"]
    assert ".simplicio-loop/install-ownership.json" in dry_result["removed"]

    # Files must still exist on disk after dry run
    assert (skill_dir / "SKILL.md").is_file()
    assert (rule_dir / "simplicio-loop-operator-flow.md").is_file()

    # 2. Applied run: removes stale copies
    apply_result = planner.prune_project_copies(project, dry_run=False)
    assert apply_result["status"] == "removed"
    assert not (skill_dir / "SKILL.md").exists()
    assert not (rule_dir / "simplicio-loop-operator-flow.md").exists()
    assert not (hook_dir / "loop_stop.py").exists()
    assert not (simplicio_dir / "install-ownership.json").exists()

    # Foreign user files must remain intact!
    assert (project / ".claude" / "settings.json").is_file()
    assert (project / "hooks" / "my_custom_hook.py").is_file()
    assert "hooks" in apply_result["kept"]
    assert ".claude" in apply_result["kept"]


def test_install_global_prune_project_copies_integration(tmp_path, monkeypatch, capsys):
    """Verify install --global --prune-project-copies runs prune and outputs summary."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(cli_impl.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("HOME", str(fake_home))  # the setup that install ends with reads HOME, not Path.home()
    monkeypatch.setattr(setup_cli, "after_install", lambda **kw: 0)  # the setup is tested in tests/setup_wizard

    fake_bundle = tmp_path / "bundle"
    (fake_bundle / "skills" / "simplicio-loop").mkdir(parents=True)
    (fake_bundle / "skills" / "simplicio-loop" / "SKILL.md").write_text("v2", encoding="utf-8")
    (fake_bundle / "hooks").mkdir(parents=True)
    (fake_bundle / "hooks" / "loop_stop.py").write_text("# v2", encoding="utf-8")
    monkeypatch.setattr(cli_impl, "BUNDLE", fake_bundle)

    project = tmp_path / "project"
    project.mkdir()
    stale_skill = project / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
    stale_skill.parent.mkdir(parents=True)
    stale_skill.write_text("v1 old")

    # Run with prune_project_copies=True
    rc = install(project, globally=True, dry_run=False, prune_project_copies=True)
    assert rc == 0
    out = capsys.readouterr().out

    # Global installation happened
    assert (fake_home / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    # Project stale copy was pruned
    assert not stale_skill.exists()
    assert "pruned project copies" in out
