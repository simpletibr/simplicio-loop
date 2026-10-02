"""Tests for the full loop protocol skill entry (Issue #1392).

Red-first test suite verifying:
- The skill names the protocol phases (intake, anchor and ACs, backlog, per-turn loop, evidence-gated promise, PR evidence);
- No model-facing surface says "Invoking it runs simplicio-loop turbo";
- Every command named in SKILL.md and references exists and --help exits 0;
- The extension-point count stated in the docs equals the table;
- The header lock passes.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SKILL = ROOT / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
REFERENCES_DIR = ROOT / ".claude" / "skills" / "simplicio-loop" / "references"
BEGIN = "<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->"
END = "<!-- SIMPLICIO-LLM-ORIENTATION:END -->"

PROTOCOL_PHASES = (
    ("intake", "intake"),
    ("anchor & ACs", "anchor"),
    ("backlog", "backlog"),
    ("triage", "triage"),
    ("decide", "decide"),
    ("operate", "operate"),
    ("verify", "verify"),
    ("journal", "journal"),
    ("promise", "promise"),
    ("PR evidence", "evidence"),
)

MODEL_FACING_SURFACES = (
    ".claude/skills/simplicio-loop/SKILL.md",
    "plugin/skills/simplicio-loop/SKILL.md",
    "simplicio_loop/_bundle/skills/simplicio-loop/SKILL.md",
    "docs/LLM_MAX_SPEED_ORIENTATION.md",
    "docs/ECOSYSTEM_LLM_GUIDE.md",
    "llms.txt",
    "AGENTS.md",
    "packaging/host-rules/simplicio-loop-operator-flow.md",
    "adapters/opencode/README.md",
)


def test_skill_names_protocol_phases() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    for name, pattern in PROTOCOL_PHASES:
        assert re.search(r"\b" + re.escape(pattern) + r"\b", text), f"Missing protocol phase: {name}"


@pytest.mark.parametrize("rel", MODEL_FACING_SURFACES)
def test_no_model_facing_surface_says_invoking_runs_turbo(rel: str) -> None:
    path = ROOT / rel
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        assert "Invoking it runs simplicio-loop turbo" not in text, f"Found turbo entry in {rel}"


def test_every_command_named_in_skill_and_references_exists_and_help_exits_zero() -> None:
    """Every script and command cited in SKILL.md and references/*.md must exist and answer --help."""
    sources = [SKILL] + list(REFERENCES_DIR.glob("*.md"))
    cited_scripts: set[str] = set()
    script_pattern = re.compile(r"\bscripts/([a-zA-Z0-9_\-]+\.py)\b")

    for src in sources:
        text = src.read_text(encoding="utf-8")
        for match in script_pattern.findall(text):
            cited_scripts.add(f"scripts/{match}")

    # Also test the primary CLI commands
    for script_rel in sorted(cited_scripts):
        script_path = ROOT / script_rel
        assert script_path.is_file(), f"Cited script missing: {script_rel}"
        res = subprocess.run(["python3", str(script_path), "--help"], capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, f"Script {script_rel} --help exited with {res.returncode}: {res.stderr or res.stdout}"

    # simplicio-loop subcommands cited
    res = subprocess.run(["python3", "-c", "from simplicio_loop.cli import main; import sys; sys.argv = ['simplicio-loop', '--help']; main()"],
                         capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0, f"simplicio-loop --help failed: {res.stderr}"


def test_extension_point_count_equals_table() -> None:
    from scripts.claims_audit import _extension_point_table_count
    table_count = _extension_point_table_count()
    assert table_count == 50, f"Extension point table count expected 50, got {table_count}"

    ext_doc = REFERENCES_DIR / "extension-points.md"
    assert ext_doc.is_file()
    doc_text = ext_doc.read_text(encoding="utf-8")
    assert "50 named binding points" in doc_text or "50 extension points" in doc_text


def test_contract_headers_pass() -> None:
    from scripts.contract_headers import check
    errors = check(str(ROOT))
    assert not errors, f"Header lock check failed: {errors}"
