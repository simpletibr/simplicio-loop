"""Tests for coverage: ensure PR criteria are covered by changes."""
from __future__ import annotations

import pytest

from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import CheckResult, PASS, FAIL, SKIPPED
from simplicio_loop.review_gate.coverage import criteria, closes, check_coverage


# Two criteria, the first one done by the PR (a function `export_csv(report)`), the second one not.
TWO_CRITERIA = "- [ ] export report to csv\n- [ ] send report by email\n"
FIRST_ONLY_CHANGES = [FileChange("src/report_export.py", "A", (1,))]
FIRST_ONLY_ADDED = {"src/report_export.py": "def export_csv(report):\n    return report\n"}


class TestCriteria:
    """Extract unchecked criteria from issue body."""

    def test_extracts_unchecked_criteria(self):
        body = "## Criteria\n- [ ] Do X\n- [ ] Do Y\n- [x] Done Z\n"
        result = criteria(body)
        assert result == ["Do X", "Do Y"]

    def test_empty_criteria(self):
        body = "No criteria here\n"
        result = criteria(body)
        assert result == []

    def test_ignores_checked_items(self):
        body = "- [x] Already done\n- [ ] Still to do\n"
        result = criteria(body)
        assert result == ["Still to do"]

    def test_whitespace_variations(self):
        body = "- [ ]  Criterion with spaces\n- [  ] Another\n"
        result = criteria(body)
        assert "Criterion with spaces" in result or "Criterion" in str(result).lower()


class TestCloses:
    """Detect if PR closes an issue."""

    def test_closes_basic(self):
        assert closes("fixes #123", 123)
        assert closes("closes #123", 123)
        assert closes("fix #123", 123)

    def test_closes_variations(self):
        assert closes("Fixes: #456", 456)
        assert closes("Closes #789", 789)
        assert closes("Fixed #100", 100)
        assert closes("Resolved #111", 111)

    def test_closes_case_insensitive(self):
        assert closes("CLOSES #222", 222)
        assert closes("Fixes #333", 333)

    def test_closes_with_repo(self):
        assert closes("fixes owner/repo#999", 999)

    def test_closes_pt_br(self):
        assert closes("fecha #555", 555)
        assert closes("resolvido #666", 666)
        assert closes("Fechado #777", 777)

    def test_does_not_close_partial(self):
        # "Parte de" should not close
        assert not closes("Parte de #888", 888)

    def test_does_not_close_wrong_number(self):
        assert not closes("closes #123", 124)

    def test_no_close_keyword(self):
        assert not closes("See #999", 999)


class TestCheckCoverage:
    """Validate coverage of issue criteria by PR changes."""

    def test_skipped_no_issue(self):
        result = check_coverage(None, "", [], {}, "")
        assert result.status == SKIPPED
        assert "sem issue" in str(result.reasons).lower()

    def test_skipped_no_criteria(self):
        result = check_coverage(123, "No criteria here", [], {}, "")
        assert result.status == SKIPPED
        assert "sem criterios" in str(result.reasons).lower()

    def test_pass_all_criteria_covered(self):
        """All criteria are covered by changes."""
        issue_body = "- [ ] implement foo.py\n- [ ] add tests\n"
        changes = [FileChange("src/foo.py", "A", (1,)), FileChange("tests/test_foo.py", "A", (1,))]
        added_text = {"src/foo.py": "def foo():\n    pass\n", "tests/test_foo.py": "def test_foo():\n    pass\n"}

        result = check_coverage(123, issue_body, changes, added_text, "closes #123")
        assert result.status == PASS

    def test_fail_uncovered_criterion(self):
        """Some criteria are not covered."""
        issue_body = "- [ ] implement feature X\n- [ ] document API\n"
        changes = [FileChange("src/feature.py", "A", (1,))]
        added_text = {"src/feature.py": "# feature\n"}

        result = check_coverage(123, issue_body, changes, added_text, "just a normal PR body")
        assert result.status == FAIL
        # Should fail because some criteria are not covered
        assert any("sem cobertura" in r.lower() for r in result.reasons)

    def test_partial_with_parte_de(self):
        """Partial coverage with 'Parte de' is allowed if falta list matches."""
        issue_body = TWO_CRITERIA
        changes = FIRST_ONLY_CHANGES
        added_text = FIRST_ONLY_ADDED
        pr_body = "Parte de #123\nFalta:\n- [ ] send report by email\n"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == PASS
        assert result.measured["partial"]

    def test_partial_fail_without_parte_de(self):
        """Partial coverage without 'Parte de' fails."""
        issue_body = TWO_CRITERIA
        changes = FIRST_ONLY_CHANGES
        added_text = FIRST_ONLY_ADDED
        pr_body = "Does something\n"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == FAIL

    def test_partial_fail_with_closes(self):
        """Partial coverage with closes keyword fails (unless it's Parte de)."""
        issue_body = TWO_CRITERIA
        changes = FIRST_ONLY_CHANGES
        added_text = FIRST_ONLY_ADDED
        pr_body = "closes #123"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == FAIL

    def test_partial_fail_without_falta_list(self):
        """Partial coverage with 'Parte de' but no Falta list fails."""
        issue_body = TWO_CRITERIA
        changes = FIRST_ONLY_CHANGES
        added_text = FIRST_ONLY_ADDED
        pr_body = "Parte de #123\n"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == FAIL

    def test_coverage_by_token_match(self):
        """Criteria covered by token matches in files."""
        issue_body = "- [ ] implement `user_controller.py`\n"
        changes = [FileChange("app/user_controller.py", "A", (1,))]
        added_text = {"app/user_controller.py": "class UserController:\n    pass\n"}

        result = check_coverage(123, issue_body, changes, added_text, "closes #123")
        assert result.status == PASS

    def test_coverage_by_single_significant_word(self):
        """Criteria with single significant word covered by match."""
        issue_body = "- [ ] create database\n"
        changes = [FileChange("database.py", "A", (1,))]
        added_text = {"database.py": "def setup_database():\n    pass\n"}

        result = check_coverage(123, issue_body, changes, added_text, "closes #123")
        assert result.status == PASS

    def test_coverage_by_multiple_significant_words(self):
        """Criteria with multiple significant words need >= 50% match."""
        issue_body = "- [ ] write authentication system\n"
        changes = [FileChange("auth.py", "A", (1,))]
        added_text = {"auth.py": "def authenticate():\n    pass\n"}

        # content words: "authentication", "system" ("write" is a generic verb); only "authentication" is found
        # and a criterion with 2+ words needs 2 of them (and 50%) in one unit -> FAIL
        result = check_coverage(123, issue_body, changes, added_text, "just a PR")
        assert result.status == FAIL

    def test_coverage_by_path_token(self):
        """Criteria with path token is covered by file creation."""
        issue_body = "- [ ] create src/handlers.py\n"
        changes = [FileChange("src/handlers.py", "A", (1,))]
        added_text = {"src/handlers.py": "def handle_request():\n    pass\n"}

        result = check_coverage(123, issue_body, changes, added_text, "closes #123")
        assert result.status == PASS


# --- how a criterion is matched to the diff -----------------------------------------------------------------------

from simplicio_loop.review_gate import coverage as cov  # noqa: E402


def _pr(issue_body, files, pr_body="PR normal"):
    """files: {path: (status, added text)}; the line numbers of the added lines are not used by the check."""
    changes = [FileChange(p, st, tuple(range(1, text.count("\n") + 2))) for p, (st, text) in files.items()]
    added = {p: text for p, (st, text) in files.items() if st != "D"}
    return check_coverage(1649, issue_body, changes, added, pr_body)


def _uncovered(result):
    return result.measured.get("uncovered", [])


CLAMP = "- [ ] clamp limita o valor entre low e high"
MOD = ("A", "def clamp(value, low, high):\n    return max(low, min(high, value))\n")
TEST_CLAMP = ("A", "def test_clamp_low():\n    assert mod.clamp(-1, 0, 10) == 0\n")


class TestCriterionMatching:
    def test_clamp_scenario_is_covered_by_the_definition_and_its_test(self):
        # the test alone has 2 of 5 words (clamp, low), the definition `clamp(value, low, high)` has 3: >= 50%
        result = _pr(CLAMP, {"mod.py": MOD, "tests/test_mod.py": TEST_CLAMP})
        assert result.status == PASS, result.reasons
        assert result.measured["evidence"] == {"clamp limita o valor entre low e high": ["code:mod.py"]}

    def test_a_test_with_half_of_the_words_covers_the_criterion(self):
        test = ("A", "def test_clamp_limits_low_high():\n    assert mod.clamp(5, 0, 1) == 1\n")
        result = _pr("- [ ] clamp limita low e high", {"tests/test_mod.py": test})  # clamp, limita, low, high
        assert result.status == PASS and result.measured["evidence"]["clamp limita low e high"] == [
            "test:tests/test_mod.py::test_clamp_limits_low_high"]

    def test_the_definition_alone_without_the_matching_signature_does_not_cover(self):
        # `clamp` + `low` only: 2 of 5 words, in the test and in the definition alike
        mod = ("A", "def clamp(x, lo, hi):\n    return max(lo, min(hi, x))\n")
        result = _pr(CLAMP, {"mod.py": mod, "tests/test_mod.py": TEST_CLAMP})
        assert result.status == FAIL
        assert result.reasons == ("criterio sem cobertura: clamp limita o valor entre low e high",)

    def test_words_found_in_different_units_do_not_add_up(self):
        issue = "- [ ] cliente recebe fatura mensal pelo correio"  # 5 words: 3 needed in one unit
        tests = ("A", "def test_a():\n    cliente.recebe()\n\ndef test_b():\n    fatura.mensal()\n")
        result = _pr(issue, {"tests/test_x.py": tests})
        assert result.status == FAIL  # 2 words in test_a, 2 in test_b: 4 in total, never 3 in one
        together = ("A", "def test_a():\n    cliente.recebe(fatura)\n")
        assert _pr(issue, {"tests/test_x.py": together}).status == PASS

    def test_words_found_in_different_files_do_not_add_up(self):
        issue = "- [ ] exportar relatorio mensal"  # 3 words: 2 needed in one unit
        files = {"src/exportar.py": ("A", "def exportar_tudo():\n    pass\n"),
                 "src/relatorio.py": ("A", "def gerar_relatorio():\n    pass\n")}
        assert _pr(issue, files).status == FAIL
        one = {"src/exportar.py": ("A", "def exportar_relatorio():\n    pass\n")}
        assert _pr(issue, one).status == PASS

    def test_required_words_by_criterion_size(self):
        assert [cov._needed(n) for n in range(1, 8)] == [1, 2, 2, 2, 3, 3, 4]

    def test_a_single_content_word_is_enough_for_a_one_word_criterion(self):
        assert _pr("- [ ] cache", {"src/cache.py": ("A", "x = 1\n")}).status == PASS

    def test_two_words_need_both_even_if_that_is_more_than_half(self):
        issue = "- [ ] exportar relatorio"
        assert _pr(issue, {"src/relatorio.py": ("A", "def gerar():\n    pass\n")}).status == FAIL

    def test_comments_and_bodies_of_production_code_are_not_evidence(self):
        mod = ("A", "def total(x):\n    # calcular desconto progressivo do carrinho\n    return x\n")
        result = _pr("- [ ] calcular desconto progressivo do carrinho", {"src/total.py": mod})
        assert result.status == FAIL

    def test_names_and_signatures_of_definitions_are_evidence(self):
        for line in ("class DescontoProgressivo:", "async def desconto_progressivo(carrinho):",
                     "export function descontoProgressivo() {", "DESCONTO_PROGRESSIVO = 3", "pub fn desconto_progressivo() {"):
            result = _pr("- [ ] desconto progressivo", {"src/x.py": ("A", line + "\n")})
            assert result.status == PASS, line

    def test_indented_assignments_are_not_definitions(self):
        result = _pr("- [ ] desconto progressivo", {"src/x.py": ("A", "def f():\n    desconto_progressivo = 3\n")})
        assert result.status == FAIL

    def test_accents_are_ignored(self):
        mod = ("A", "def validacao_cartao(numero):\n    pass\n")
        assert _pr("- [ ] Validação do cartão", {"src/pagamento.py": mod}).status == PASS

    def test_words_share_a_stem(self):
        assert cov._same("authentication", "authenticate")
        assert cov._same("limita", "limit")
        assert cov._same("autenticar", "autenticacao")
        assert not cov._same("report", "repository")
        assert not cov._same("interface", "internal")
        assert not cov._same("cart", "carta")  # under 5 letters only equal words match

    def test_words_are_split_on_case_underscore_digits_and_accents(self):
        assert cov._words("UserController") == ["user", "controller"]
        assert cov._words("Validação_do cartão2") == ["validacao", "cartao"]
        assert cov._words("add the Tests to a b") == []  # stopwords, generic verbs, test words, short words
        assert cov._words("users classes") == ["user", "classe"]  # plural "s" dropped, "ss" kept: "class"
        assert cov._words("class") == ["class"]

    def test_pure_test_criterion_needs_a_test_file(self):
        prod = {"src/foo.py": ("A", "def foo():\n    pass\n")}
        assert _pr("- [ ] adicionar testes", prod).status == FAIL
        with_test = {**prod, "tests/test_foo.py": ("A", "def test_foo():\n    pass\n")}
        result = _pr("- [ ] adicionar testes", with_test)
        assert result.status == PASS and result.measured["evidence"]["adicionar testes"] == ["test:tests/test_foo.py"]

    def test_a_test_file_without_added_lines_or_a_conftest_is_not_a_test(self):
        prod = {"src/foo.py": ("A", "def foo():\n    pass\n")}
        assert _pr("- [ ] add tests", {**prod, "tests/conftest.py": ("A", "import pytest\n")}).status == FAIL
        assert _pr("- [ ] add tests", {**prod, "tests/test_foo.py": ("M", "")}).status == FAIL

    def test_a_criterion_about_tests_is_covered_by_tests_only(self):
        prod = {"src/clamp.py": ("A", "def clamp(value):\n    return value\n")}
        issue = "- [ ] adicionar teste para clamp"
        assert _pr(issue, prod).status == FAIL
        assert _pr(issue, {**prod, "tests/test_clamp.py": ("A", "def test_clamp():\n    pass\n")}).status == PASS

    def test_a_criterion_about_tests_does_not_take_cited_symbols_from_production(self):
        prod = {"src/clamp.py": ("A", "def clamp(value):\n    return value\n")}
        assert _pr("- [ ] adicionar teste para `clamp`", prod).status == FAIL

    def test_test_file_without_test_defs_is_one_unit(self):
        # only body lines of an existing test were added: no `def test_*` in the added lines
        body = ("M", "    result = clamp(-1, 0, 10)\n    assert result == 0  # limite inferior\n")
        assert _pr("- [ ] teste do limite inferior do clamp", {"tests/test_mod.py": body}).status == PASS

    def test_deleted_files_are_not_evidence_but_can_be_cited(self):
        gone = {"src/carrinho.py": ("D", "")}
        assert _pr("- [ ] implementar carrinho", gone).status == FAIL
        assert _pr("- [ ] remover `src/carrinho.py`", gone).status == PASS

    def test_docs_are_evidence_by_path_and_added_text(self):
        doc = ("A", "## API de pagamento\n\nComo cobrar.\n")
        result = _pr("- [ ] documentar a API de pagamento", {"docs/uso.md": doc})
        assert result.status == PASS and result.measured["evidence"]["documentar a API de pagamento"] == ["docs:docs/uso.md"]

    def test_criterion_without_content_words_cannot_be_verified(self):
        assert _pr("- [ ] Do it", {"src/foo.py": ("A", "def foo():\n    pass\n")}).status == FAIL

    def test_evidence_is_capped(self):
        files = {f"src/cache{i}.py": ("A", "x = 1\n") for i in range(9)}
        assert len(_pr("- [ ] cache", files).measured["evidence"]["cache"]) == cov._EVIDENCE_CAP


class TestCitedPathsAndSymbols:
    FILES = {"src/data.py": ("A", "class Dataset:\n    pass\n"), "tests/test_data.py": ("A", "def test_dataset():\n    assert Dataset()\n")}

    def test_backticked_path_must_be_a_changed_file(self):
        assert _pr("- [ ] atualizar `src/data.py`", self.FILES).status == PASS
        assert _pr("- [ ] atualizar `src/other.py`", self.FILES).status == FAIL

    def test_a_path_is_not_matched_by_substring(self):
        files = {"src/metadata.py": ("A", "x = 1\n")}
        assert _pr("- [ ] atualizar `data.py`", files).status == FAIL
        assert _pr("- [ ] atualizar `metadata.py`", files).status == PASS

    def test_bare_paths_count_too(self):
        assert _pr("- [ ] implement foo.py", {"src/foo.py": ("A", "x = 1\n")}).status == PASS
        assert _pr("- [ ] implement src/foo.py.", {"src/foo.py": ("A", "x = 1\n")}).status == PASS  # trailing dot

    def test_bare_words_with_a_slash_are_prose_not_paths(self):
        added = {"src/io.py": ("A", "def processa_entrada_saida():\n    pass\n")}
        assert _pr("- [ ] entrada/saida", added).status == PASS  # both words are content words

    def test_directory_covered_by_a_file_under_it(self):
        assert _pr("- [ ] criar `src/api/`", {"src/api/users.py": ("A", "x = 1\n")}).status == PASS
        assert _pr("- [ ] criar `src/api/`", {"src/apis/users.py": ("A", "x = 1\n")}).status == FAIL
        assert _pr("- [ ] criar `api/`", {"src/api/users.py": ("A", "x = 1\n")}).status == PASS

    def test_dot_slash_prefix_is_ignored(self):
        assert _pr("- [ ] atualizar `./src/data.py`", self.FILES).status == PASS

    def test_symbol_must_be_a_whole_word_of_the_added_lines(self):
        added = {"src/x.py": ("A", "def reparse_all():\n    pass\n")}
        assert _pr("- [ ] `parse` aceita vazio", added).status == FAIL
        assert _pr("- [ ] `reparse_all` aceita vazio", added).status == PASS

    def test_symbol_with_call_parens_and_dotted_name(self):
        added = {"src/x.py": ("A", "def clamp(v):\n    pass\n")}
        assert _pr("- [ ] `clamp()` existe", added).status == PASS
        assert _pr("- [ ] `mod.clamp` existe", added).status == PASS

    def test_bare_snake_and_camel_case_identifiers_are_cited_symbols(self):
        files = {"src/x.py": ("A", "class UserController:\n    def list_users(self):\n        pass\n")}
        assert _pr("- [ ] UserController lista", files).status == PASS
        assert _pr("- [ ] chama list_users sempre", files).status == PASS
        assert _pr("- [ ] chama other_thing sempre", files).status == FAIL

    def test_symbol_equal_to_a_changed_file_name_is_found(self):
        assert _pr("- [ ] `database` pronto", {"src/database.py": ("A", "x = 1\n")}).status == PASS

    def test_every_cited_token_must_be_in_the_diff(self):
        files = {"src/a.py": ("A", "x = 1\n")}
        assert _pr("- [ ] `src/a.py` e `src/b.py`", files).status == FAIL
        assert _pr("- [ ] `src/a.py` e `src/b.py`", {**files, "src/b.py": ("A", "y = 2\n")}).status == PASS

    def test_short_symbols_are_ignored(self):
        assert _pr("- [ ] `x` existe", {"src/a.py": ("A", "x = 1\n")}).status == FAIL

    def test_cited_but_absent_falls_back_to_the_words(self):
        # `other.py` is not in the diff, but "exportar relatorio" is in one definition: words cover it
        files = {"src/rel.py": ("A", "def exportar_relatorio():\n    pass\n")}
        assert _pr("- [ ] exportar relatorio de `other.py`", files).status == PASS

    def test_evidence_names_the_cited_tokens(self):
        result = _pr("- [ ] atualizar `src/data.py` e `Dataset`", self.FILES)
        assert result.measured["evidence"] == {"atualizar `src/data.py` e `Dataset`": ["path:src/data.py", "symbol:Dataset"]}


class TestCriteriaBullets:
    def test_other_bullets_and_numbered_items(self):
        body = "* [ ] star\n+ [ ] plus\n1. [ ] numbered\n2) [ ] paren\n- [x] done\n* [x] done too\n"
        assert criteria(body) == ["star", "plus", "numbered", "paren"]


class TestClosesAndPartial:
    def test_any_closing_keyword_for_the_issue_counts(self):
        assert closes("closes #5, closes #123", 123)
        assert closes("Fixes #5\nFixes #123", 123)

    def test_keyword_is_a_whole_word(self):
        assert not closes("prefix #123", 123)
        assert not closes("the unresolved #123", 123)
        assert closes("(fixes #123)", 123)

    def test_repo_qualified_reference_with_a_hyphen(self):
        assert closes("Closes simpletibr/simplicio-loop#123", 123)
        assert not closes("Closes simpletibr/simplicio-loop#124", 123)

    def test_parte_de_next_to_a_keyword_does_not_undo_it(self):
        assert closes("Parte de #123\nCloses #123", 123)
        assert closes("Parte de #5 e fecha #123", 123)
        assert not closes("Parte de #123", 123)

    def test_issue_number_is_compared_whole(self):
        assert not closes("closes #1234", 123)

    def test_partial_pr_must_be_partial_of_this_issue(self):
        body = "Parte de #999\nFalta:\n- [ ] send report by email\n"
        result = check_coverage(123, TWO_CRITERIA, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body)
        assert result.status == FAIL
        assert "criterio sem cobertura: send report by email" in result.reasons

    def test_parte_de_with_repo_prefix_is_partial(self):
        body = "Parte de simpletibr/simplicio-loop#123\nFalta:\n- [ ] send report by email\n"
        result = check_coverage(123, TWO_CRITERIA, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body)
        assert result.status == PASS and result.measured["partial"] is True

    def test_partial_pr_with_a_closing_keyword_fails(self):
        body = "Parte de #123\nCloses #123\nFalta:\n- [ ] send report by email\n"
        result = check_coverage(123, TWO_CRITERIA, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body)
        assert result.status == FAIL
        assert result.reasons[0] == "PR parcial sem 'Parte de #' ou com palavra de fechamento"
        assert "criterio sem cobertura: send report by email" in result.reasons

    def test_falta_list_may_use_any_bullet(self):
        body = "Parte de #123\nFalta:\n* [ ] send report by email\n"
        assert check_coverage(123, TWO_CRITERIA, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body).status == PASS

    def test_falta_list_shorter_than_the_uncovered_criteria_fails(self):
        issue = "- [ ] export report to csv\n- [ ] send report by email\n- [ ] sync clock drift\n"
        body = "Parte de #123\nFalta:\n- [ ] send report by email\n"
        result = check_coverage(123, issue, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body)
        assert result.status == FAIL and "tem 1 items mas ha 2" in result.reasons[0]

    def test_partial_pass_reports_what_is_left(self):
        body = "Parte de #123\nFalta:\n- [ ] send report by email\n"
        result = check_coverage(123, TWO_CRITERIA, FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, body)
        assert result.measured["uncovered"] == ["send report by email"]
        assert result.measured["covered"] == 1 and result.measured["criteria"] == 2
        assert list(result.measured["evidence"]) == ["export report to csv"]

    def test_full_coverage_may_close_the_issue(self):
        result = check_coverage(123, "- [ ] export report to csv\n", FIRST_ONLY_CHANGES, FIRST_ONLY_ADDED, "Closes #123")
        assert result.status == PASS and result.measured["partial"] is False
