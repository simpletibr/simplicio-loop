"""Unit coverage for issue #1328 bug 3.

``_extract_repo_file_hints`` hard-excluded any path starting with ``.claude/``
(``runner.py`` -- the same guard also lived, for the mapper-derived candidate
path, near ``_task_context_plan_data``/``_candidate_targets``). A task whose
only real target is a skill file (``.claude/skills/<name>/SKILL.md``) could
never get an authorized target, and blocked with ``no_authorized_target``
before any operator ever ran (measured in the #1323 wave, task 3).

``.claude/skills/**`` (and its ``plugin/`` / ``simplicio_loop/_bundle/``
mirrors) must be authorized targets when the task text names them explicitly.
Every other ``.claude/`` internal (hooks, settings.json, scripts) stays
excluded -- this is not a blanket lift of the guard.
"""
from __future__ import annotations

from pathlib import Path

from simplicio_loop import runner as runner_mod


def _write_skill_tree(repo: Path) -> None:
    skill = repo / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("# simplicio-loop\n", encoding="utf-8")

    plugin_skill = repo / "plugin" / "skills" / "simplicio-loop" / "SKILL.md"
    plugin_skill.parent.mkdir(parents=True, exist_ok=True)
    plugin_skill.write_text("# simplicio-loop (plugin mirror)\n", encoding="utf-8")

    bundle_skill = repo / "simplicio_loop" / "_bundle" / "skills" / "simplicio-loop" / "SKILL.md"
    bundle_skill.parent.mkdir(parents=True, exist_ok=True)
    bundle_skill.write_text("# simplicio-loop (bundle mirror)\n", encoding="utf-8")

    settings = repo / ".claude" / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")


def test_explicit_claude_skill_path_is_authorized(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill_tree(repo)

    hints = runner_mod._extract_repo_file_hints(
        "Fix a typo in .claude/skills/simplicio-loop/SKILL.md",
        repo,
    )
    assert hints == [".claude/skills/simplicio-loop/SKILL.md"]


def test_explicit_plugin_and_bundle_skill_mirrors_are_authorized(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill_tree(repo)

    hints = runner_mod._extract_repo_file_hints(
        "Sync plugin/skills/simplicio-loop/SKILL.md and "
        "simplicio_loop/_bundle/skills/simplicio-loop/SKILL.md",
        repo,
    )
    assert hints == [
        "plugin/skills/simplicio-loop/SKILL.md",
        "simplicio_loop/_bundle/skills/simplicio-loop/SKILL.md",
    ]


def test_other_dot_claude_internals_stay_excluded(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill_tree(repo)

    hints = runner_mod._extract_repo_file_hints(
        "Edit .claude/settings.json and .claude/skills/simplicio-loop/SKILL.md",
        repo,
    )
    assert hints == [".claude/skills/simplicio-loop/SKILL.md"]
