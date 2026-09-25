"""Unit coverage for simplicio/scratch/skill_opt.py (previously 26%)."""

from __future__ import annotations

import pytest

from simplicio.scratch import skill_opt


def test_skills_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_SKILLS_DIR", str(tmp_path / "custom-skills"))
    assert skill_opt._skills_root() == tmp_path / "custom-skills"


def test_skills_root_finds_cwd_skills(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_SKILLS_DIR", raising=False)
    (tmp_path / ".skills").mkdir()
    monkeypatch.chdir(tmp_path)
    assert skill_opt._skills_root() == tmp_path / ".skills"


def test_skills_root_walks_up_parents(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_SKILLS_DIR", raising=False)
    (tmp_path / ".skills").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert skill_opt._skills_root() == tmp_path / ".skills"


def test_skills_root_defaults_to_cwd_when_none_found(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert skill_opt._skills_root() == tmp_path / ".skills"


def test_list_existing_skills_missing_root(tmp_path):
    assert skill_opt._list_existing_skills(tmp_path / "nope") == []


def test_list_existing_skills_lists_dirs_and_skips_underscore(tmp_path):
    (tmp_path / "foo").mkdir()
    (tmp_path / "bar").mkdir()
    (tmp_path / "_template").mkdir()
    (tmp_path / "not-a-dir.txt").write_text("x", encoding="utf-8")
    result = skill_opt._list_existing_skills(tmp_path)
    assert result == ["bar", "foo"]


def test_extract_slug_found():
    text = "---\nname: my-skill\ndescription: x\n---\n"
    assert skill_opt._extract_slug(text) == "my-skill"


def test_extract_slug_missing():
    assert skill_opt._extract_slug("no frontmatter here") is None


def test_has_review_gate_true():
    assert skill_opt._has_review_gate("review_required: true") is True


def test_has_review_gate_false():
    assert skill_opt._has_review_gate("review_required: false") is False


VALID_SKILL_DOC = """---
name: my-new-skill
description: does a thing
trigger: when needed
auto_generated:
  by: skill-opt
  date: 2026-01-01
  source_goal: do a thing
  planner_model: test-model
  review_required: true
---

# My New Skill

## When to use
Always.

## Steps
1. Do it.

## DoD
- [ ] done

## Anti-patterns
- none
"""


def test_generate_skill_doc_success(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    slug, text = skill_opt.generate_skill_doc("do a thing", skills_root=tmp_path)
    assert slug == "my-new-skill"
    assert "review_required: true" in text


def test_generate_skill_doc_empty_response_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: "")
    with pytest.raises(skill_opt.SkillOptError, match="empty response"):
        skill_opt.generate_skill_doc("do a thing", skills_root=tmp_path)


def test_generate_skill_doc_missing_slug_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: "no frontmatter at all")
    with pytest.raises(skill_opt.SkillOptError, match="missing a valid"):
        skill_opt.generate_skill_doc("do a thing", skills_root=tmp_path)


def test_generate_skill_doc_missing_review_gate_raises(monkeypatch, tmp_path):
    doc = "---\nname: my-skill\n---\nno gate here"
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: doc)
    with pytest.raises(skill_opt.SkillOptError, match="review_required"):
        skill_opt.generate_skill_doc("do a thing", skills_root=tmp_path)


def test_generate_skill_doc_existing_slug_raises(monkeypatch, tmp_path):
    (tmp_path / "my-new-skill").mkdir()
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    with pytest.raises(skill_opt.SkillOptError, match="already exists"):
        skill_opt.generate_skill_doc("do a thing", skills_root=tmp_path)


def test_install_skill_writes_file(tmp_path):
    path = skill_opt.install_skill("my-slug", "# content", skills_root=tmp_path)
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "# content"


def test_install_skill_raises_when_dir_exists(tmp_path):
    (tmp_path / "my-slug").mkdir(parents=True)
    with pytest.raises(skill_opt.SkillOptError, match="already exists"):
        skill_opt.install_skill("my-slug", "# content", skills_root=tmp_path)


def test_install_skill_from_description(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    path = skill_opt.install_skill_from_description("do a thing", skills_root=tmp_path)
    assert path.name == "SKILL.md"
    assert path.parent.name == "my-new-skill"


def test_main_dry_run_prints_doc(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    monkeypatch.setattr(skill_opt, "_skills_root", lambda: tmp_path)
    rc = skill_opt.main(["do a thing", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "my-new-skill" in out


def test_main_installs_when_not_dry_run(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    monkeypatch.setattr(skill_opt, "_skills_root", lambda: tmp_path)
    rc = skill_opt.main(["do a thing"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "installed at" in err
    assert (tmp_path / "my-new-skill" / "SKILL.md").is_file()


def test_main_generate_error_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: "")
    rc = skill_opt.main(["do a thing"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "skill-opt" in err


def test_main_install_error_returns_3(monkeypatch, capsys, tmp_path):
    (tmp_path / "my-new-skill").mkdir(parents=True)
    monkeypatch.setattr(
        skill_opt, "generate_skill_doc", lambda description: ("my-new-skill", VALID_SKILL_DOC)
    )
    monkeypatch.setattr(skill_opt, "_skills_root", lambda: tmp_path)
    rc = skill_opt.main(["do a thing"])
    err = capsys.readouterr().err
    assert rc == 3
    assert "skill-opt" in err


def test_main_sets_planner_env(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_opt, "planner_complete", lambda prompt: VALID_SKILL_DOC)
    monkeypatch.setattr(skill_opt, "_skills_root", lambda: tmp_path)
    monkeypatch.delenv("SIMPLICIO_PLANNER", raising=False)
    skill_opt.main(["do a thing", "--planner", "custom-model", "--dry-run"])
    assert __import__("os").environ["SIMPLICIO_PLANNER"] == "custom-model"
