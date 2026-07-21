from pathlib import Path

from scripts.mapper_quality_gate import build_report


def test_quality_report_is_markdown_and_preserves_unavailable_evidence():
    root = Path(__file__).parents[1]
    report, code = build_report(root, runtime_binary="definitely-missing-simplicio")
    assert code == 0
    assert report.startswith("# Mapper quality gate")
    assert "Performance observations | null" in report
    assert "HBP receipt | null" in report
    assert "Runtime ecosystem doctor | null" in report


def test_runtime_requirement_blocks_missing_runtime():
    root = Path(__file__).parents[1]
    _, code = build_report(
        root,
        runtime_binary="definitely-missing-simplicio",
        require_runtime=True,
    )
    assert code == 1
