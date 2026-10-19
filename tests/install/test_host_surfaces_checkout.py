"""The checkout installer (`scripts/install.sh <runtime>` -> `scripts/install_lib.py`) writes the three wave-B
surfaces that the packaged planner also writes, with the same reruns-are-no-ops rule.

- openclaw reads skills from `.agents/skills` (its docs list it; `.claude/skills` is not scanned), so the skill copy
  goes there as well as to the universal `.claude/skills`.
- aider loads a file only when `.aider.conf.yml` names it under `read:`; the installer creates that file, and an
  existing one is the user's and is left alone.
- continue reads `.continue/rules/*.md`, and its docs expect YAML frontmatter on a rule file.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL_LIB = REPO / "scripts" / "install_lib.py"
LOOP_SKILL_REF = ".claude/skills/simplicio-loop/SKILL.md"


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _install(runtime: str, target: Path, home: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), SIMPLICIO_HOME=str(home),
               SIMPLICIO_NO_BROWSER="1")
    return subprocess.run(
        [sys.executable, str(INSTALL_LIB), runtime, "--target", str(target), "--skip-operators", "--minimal"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(target),
        stdin=subprocess.DEVNULL, timeout=120, check=False)


def test_openclaw_skills_land_where_openclaw_scans_them(tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()
    result = _install("openclaw", target, home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / ".agents" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    assert (target / LOOP_SKILL_REF).is_file()


def test_aider_config_names_the_conventions_file_and_an_existing_config_is_left_alone(tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()
    result = _install("aider", target, home)
    assert result.returncode == 0, result.stdout + result.stderr
    config = (target / ".aider.conf.yml").read_text(encoding="utf-8")
    assert config.startswith("read:")
    assert "CONVENTIONS.md" in config and LOOP_SKILL_REF in config
    assert (target / "CONVENTIONS.md").read_text(encoding="utf-8").count("<!-- simplicio-loop:begin -->") == 1

    before = _tree(target)
    again = _install("aider", target, home)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _tree(target) == before

    own = tmp_path / "own"
    own.mkdir()
    (own / ".aider.conf.yml").write_text("model: gpt-5\n", encoding="utf-8")
    kept = _install("aider", own, home)
    assert kept.returncode == 0, kept.stdout + kept.stderr
    assert (own / ".aider.conf.yml").read_text(encoding="utf-8") == "model: gpt-5\n"


def test_continue_rule_file_carries_yaml_frontmatter_and_the_marker_block(tmp_path: Path) -> None:
    target, home = tmp_path / "project", tmp_path / "home"
    target.mkdir()
    home.mkdir()
    result = _install("continue", target, home)
    assert result.returncode == 0, result.stdout + result.stderr
    rule = (target / ".continue" / "rules" / "simplicio-loop.md").read_text(encoding="utf-8")
    assert rule.startswith("---\n") and "alwaysApply: true" in rule
    assert rule.count("<!-- simplicio-loop:begin -->") == 1 and rule.count("<!-- simplicio-loop:end -->") == 1

    before = _tree(target)
    again = _install("continue", target, home)
    assert again.returncode == 0, again.stdout + again.stderr
    assert _tree(target) == before
