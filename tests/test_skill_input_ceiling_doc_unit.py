"""The simplicio-loop skill tells a self-paced host about the input ceiling and the handoff commands (#1608, part D)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILLS = [
    ROOT / ".claude" / "skills" / "simplicio-loop" / "SKILL.md",
    ROOT / "plugin" / "skills" / "simplicio-loop" / "SKILL.md",
    ROOT / "simplicio_loop" / "_bundle" / "skills" / "simplicio-loop" / "SKILL.md",
]


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: str(p.relative_to(ROOT)))
def test_skill_states_the_ceiling_and_the_handoff_commands(path):
    text = path.read_text(encoding="utf-8")
    assert "98,000 input tokens" in text
    for command in ("handoff write", "handoff read", "handoff check"):
        assert "simplicio-loop %s" % command in text
