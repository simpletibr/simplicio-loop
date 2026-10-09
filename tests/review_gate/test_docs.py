"""Docs check: ste-lint must not get worse and new measured claims need a label (Parte de #1649)."""
from simplicio_loop.review_gate import diffs, docs
from simplicio_loop.review_gate.model import FAIL, PASS, SKIPPED

CLEAN = "# Title\n\nThe gate runs the tests.\n"
DIRTY = CLEAN + "The gate is seamless; it is robust.\n"


def _tree(tmp_path, name, text):
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / name).write_text(text)
    return tmp_path


def _change(status, n):
    return [diffs.FileChange("docs/A.md", status, tuple(range(1, n + 1)))]


def test_hard_count_counts_only_hard_findings():
    assert docs.hard_count(CLEAN) == 0 and docs.hard_count(DIRTY) >= 2


def test_worse_total_fails_with_the_counts(tmp_path):
    base, head = _tree(tmp_path / "b", "A.md", CLEAN), _tree(tmp_path / "h", "A.md", DIRTY)
    result = docs.check_docs(base, head, _change("M", 4))
    assert result.status == FAIL and "docs/A.md" in result.reasons[0] and "ste-lint" in result.reasons[0]
    assert result.measured["files"]["docs/A.md"]["head"] > result.measured["files"]["docs/A.md"]["base"]


def test_same_or_better_total_passes_and_new_file_must_be_clean(tmp_path):
    base, head = _tree(tmp_path / "b", "A.md", DIRTY), _tree(tmp_path / "h", "A.md", DIRTY + "Another plain line.\n")
    assert docs.check_docs(base, head, _change("M", 5)).status == PASS
    new = docs.check_docs(tmp_path / "none", head, _change("A", 5))
    assert new.status == FAIL


def test_unlabeled_measured_claim_needs_a_label(tmp_path):
    text = CLEAN + "The gate takes 12 s per PR.\nThe gate takes 30 s per run. UNVERIFIED\nSee tests/review_gate/test_x.py: 5 tests.\n"
    base, head = _tree(tmp_path / "b", "A.md", CLEAN), _tree(tmp_path / "h", "A.md", text)
    result = docs.check_docs(base, head, _change("M", 6))
    assert result.status == FAIL
    assert any("12 s" in r and "UNVERIFIED" in r for r in result.reasons)
    assert not any("30 s" in r or "5 tests" in r for r in result.reasons)


def test_no_docs_is_skipped(tmp_path):
    assert docs.check_docs(tmp_path, tmp_path, [diffs.FileChange("a.py", "M", (1,))]).status == SKIPPED
