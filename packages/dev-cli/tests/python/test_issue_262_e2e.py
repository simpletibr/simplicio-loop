from __future__ import annotations

from pathlib import Path

from scripts import issue_262_e2e
from simplicio.hbp import HbpEvidenceLedger


def test_issue_262_runner_writes_markdown_and_hbp_without_json_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        issue_262_e2e,
        "_external_case",
        lambda case_id, executable, expected: issue_262_e2e.Case(
            case_id, "PASS", 1.0, "fixture handshake", "fixture"
        ),
    )
    markdown = tmp_path / "issue-262.md"
    hbp = tmp_path / "issue-262.hbp"

    assert issue_262_e2e.run(markdown=markdown, hbp=hbp) == 0
    assert "release rule" in markdown.read_text(encoding="utf-8")
    assert hbp.read_bytes().startswith(b"HBP1")
    assert len(HbpEvidenceLedger(tmp_path, file_name=hbp.name).verify()) >= 1
    assert not list(tmp_path.glob("*.json"))
