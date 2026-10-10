"""Coverage by identity and non-Python production (#1649 M3 and M2)."""
from __future__ import annotations

import pytest

from simplicio_loop.review_gate.coverage import check_coverage
from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import FAIL, PASS

CHANGES = [FileChange("src/report_export.py", "A", (1,))]
ADDED = {"src/report_export.py": "def export_csv(report):\n    return report\n"}


class TestCoverageByIdentity:
    """A Falta list names the uncovered criteria; a list of the right size that names nothing approves nothing."""

    ISSUE = "- [ ] export report to csv\n- [ ] send report by email\n- [ ] sync clock drift\n"

    def _run(self, falta):
        return check_coverage(123, self.ISSUE, CHANGES, ADDED, "Parte de #123\nFalta:\n" + falta)

    def test_a_generic_item_n_list_cannot_approve(self):
        assert self._run("- [ ] item 1\n- [ ] item 2\n").status == FAIL

    def test_empty_falta_items_cannot_approve(self):
        assert self._run("- [ ]\n- [ ]\n").status == FAIL

    def test_one_item_cannot_stand_for_two_criteria(self):
        assert self._run("- [ ] send report by email\n- [ ] send report by email\n").status == FAIL

    def test_a_list_that_names_each_uncovered_criterion_approves(self):
        result = self._run("- [ ] send report by email\n- [ ] sync clock drift\n")
        assert result.status == PASS and result.measured["partial"] is True

    def test_the_failure_names_the_criteria_the_list_does_not_name(self):
        result = self._run("- [ ] item 1\n- [ ] sync clock drift\n")
        assert result.status == FAIL and any("send report by email" in r for r in result.reasons)


class TestNonPythonProduction:
    """Red/green and mutation only read Python: js/sh/yml/toml cannot be approved by coverage alone."""

    @pytest.mark.parametrize("path", ["web/app.js", "scripts/run.sh", "deploy/ci.yml", "pyproject.toml"])
    def test_a_cited_non_python_file_is_not_coverage(self, path):
        result = check_coverage(5, f"- [ ] ajustar `{path}`\n", [FileChange(path, "M", (1,))], {path: "x = 1\n"}, "Closes #5")
        assert result.status == FAIL

    def test_non_python_definitions_do_not_cover_a_criterion_by_words(self):
        changes = [FileChange("web/app.js", "A", (1,))]
        result = check_coverage(5, "- [ ] export report to csv\n", changes, {"web/app.js": "function exportCsv(report) {}\n"}, "Closes #5")
        assert result.status == FAIL

    def test_python_production_still_covers(self):
        assert check_coverage(5, "- [ ] export report to csv\n", CHANGES, ADDED, "Closes #5").status == PASS
