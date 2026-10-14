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


class TestGenericWordsNameNoCriterion:
    """Twelve items made only of the words every criterion shares name none of them: each criterion needs a word of its own."""

    OWN = ["alpine", "brazen", "cobalt", "dormant", "eclipse", "fabric", "granite", "harbor", "ivory", "jasmine", "kestrel", "lantern"]
    ISSUE = "".join(f"- [ ] gateway ledger {own}\n" for own in OWN)

    def _run(self, items):
        return check_coverage(123, self.ISSUE, CHANGES, ADDED, "Parte de #123\nFalta:\n" + "".join(f"- [ ] {item}\n" for item in items))

    def test_twelve_items_of_only_shared_words_cannot_approve(self):
        result = self._run(["gateway ledger"] * 12)
        assert result.status == FAIL
        assert len([r for r in result.reasons if "nao nomeia" in r]) == 12

    def test_shared_words_in_any_order_and_form_still_name_nothing(self):
        assert self._run([f"ledger gateway {n}" if n % 2 else f"gateways, ledgers ({n})" for n in range(12)]).status == FAIL

    def test_items_with_the_word_of_their_own_criterion_approve(self):
        result = self._run([f"gateway ledger {own}" for own in self.OWN])
        assert result.status == PASS and result.measured["partial"] is True
        assert self._run([f"{own} gateway" for own in reversed(self.OWN)]).status == PASS  # the order of the list is free

    def test_one_item_without_the_own_word_is_the_one_reported(self):
        items = [f"gateway ledger {own}" for own in self.OWN]
        items[5] = "gateway ledger"
        result = self._run(items)
        assert result.status == FAIL and [r for r in result.reasons if "nao nomeia" in r] == ["lista 'Falta' nao nomeia o criterio: gateway ledger fabric"]

    def test_a_criterion_with_no_word_of_its_own_still_falls_back_to_the_count_of_shared_words(self):
        issue = "- [ ] send report by email\n- [ ] send report by email and sms\n"  # the first is a subset of the second
        result = check_coverage(5, issue, CHANGES, ADDED, "Parte de #5\nFalta:\n- [ ] send report by email\n- [ ] send report by email and sms\n")
        assert result.status == PASS


class TestOneItemNamesOneCriterion:
    """An item that holds the own words of several criteria stands for none of them: twelve copies of it cannot approve."""

    OWN = TestGenericWordsNameNoCriterion.OWN
    ISSUE = TestGenericWordsNameNoCriterion.ISSUE

    def _run(self, items):
        return check_coverage(123, self.ISSUE, CHANGES, ADDED, "Parte de #123\nFalta:\n" + "".join(f"- [ ] {item}\n" for item in items))

    def test_twelve_items_that_list_all_the_words_of_all_the_criteria_cannot_approve(self):
        result = self._run(["gateway ledger " + " ".join(self.OWN)] * 12)
        assert result.status == FAIL and result.measured["partial"] is False
        ambiguous = [r for r in result.reasons if "item names several criteria" in r]
        assert len(ambiguous) == 12 and all("ambiguous" in r for r in ambiguous)

    def test_the_reason_quotes_the_item(self):
        result = self._run([*[f"gateway ledger {own}" for own in self.OWN[:-1]], "gateway ledger kestrel lantern"])
        assert result.status == FAIL
        assert [r for r in result.reasons if "several criteria" in r] == ["lista 'Falta': item names several criteria (ambiguous): gateway ledger kestrel lantern"]

    def test_two_criteria_in_one_item_are_ambiguous_even_when_the_count_is_right(self):
        issue = "- [ ] export report to csv\n- [ ] send report by email\n- [ ] sync clock drift\n"
        body = "Parte de #123\nFalta:\n- [ ] send report by email and sync clock drift\n- [ ] sync clock drift\n"
        result = check_coverage(123, issue, CHANGES, ADDED, body)
        assert result.status == FAIL and any("item names several criteria" in r for r in result.reasons)

    def test_a_normal_list_of_one_criterion_per_item_still_approves(self):
        result = self._run([f"gateway ledger {own}" for own in self.OWN])
        assert result.status == PASS and result.measured["partial"] is True
        assert self._run([f"{own} (gateway ledger, pending)" for own in self.OWN]).status == PASS

    def test_a_criterion_with_no_word_of_its_own_does_not_make_the_item_ambiguous(self):
        issue = "- [ ] send report by email\n- [ ] send report by email and sms\n"
        body = "Parte de #5\nFalta:\n- [ ] send report by email\n- [ ] send report by email and sms\n"
        assert check_coverage(5, issue, CHANGES, ADDED, body).status == PASS


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
