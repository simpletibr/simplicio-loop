"""issue #1342: immutable contract headers + "What the model sees" gate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import contract_headers as ch  # noqa: E402

HEADER = (
    "<!-- simplicio-contract:begin -->\ncontract: demo\nschema: simplicio.skill/v1\n"
    "purpose: Demo.\nrules: Stable.\n<!-- simplicio-contract:end -->\n\n"
)
SECTION = "## What the model sees\nx\n### Token effect\ny\n### KV cache effect\nz\n"


def _repo(tmp_path: Path, skill: str, readme: str = SECTION) -> Path:
    skill_dir = tmp_path / ".claude" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")
    for rel in ch.MODEL_SEES_FILES:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(readme, encoding="utf-8")
    (tmp_path / "contracts").mkdir()
    return tmp_path


def test_repository_contracts_pass():
    assert ch.check() == []


def test_valid_header_after_frontmatter_passes(tmp_path):
    root = _repo(tmp_path, "---\nname: demo\ndescription: d\n---\n\n" + HEADER + "# Body\n" + SECTION)
    assert ch.check(str(root)) == []


def test_missing_header_fails(tmp_path):
    root = _repo(tmp_path, "# Body\n" + SECTION)
    assert any("missing_header" in e for e in ch.check(str(root)))


def test_injected_version_in_header_fails(tmp_path):
    root = _repo(tmp_path, HEADER.replace("purpose: Demo.", "purpose: Demo 3.43.13.") + SECTION)
    assert any("volatile:semver" in e for e in ch.check(str(root)))


def test_date_in_frontmatter_fails(tmp_path):
    root = _repo(tmp_path, "---\nname: demo\ndescription: 2026-09-26\n---\n" + HEADER + SECTION)
    assert any("volatile:iso_date" in e for e in ch.check(str(root)))


def test_missing_model_sees_section_fails(tmp_path):
    root = _repo(tmp_path, HEADER + "# Body\n")
    assert any("missing_section:What the model sees" in e for e in ch.check(str(root)))


def test_header_change_needs_changelog_note(tmp_path):
    root = _repo(tmp_path, HEADER + SECTION)
    ch.write_lock(str(root))
    skill = root / ".claude" / "skills" / "demo" / "SKILL.md"
    skill.write_text(HEADER.replace("Stable.", "Changed.") + SECTION, encoding="utf-8")
    assert any("header_changed_without_note" in e for e in ch.check(str(root)))
    (root / "CHANGELOG.md").write_text("header-change: .claude/skills/demo/SKILL.md\n", encoding="utf-8")
    assert ch.check(str(root)) == []
