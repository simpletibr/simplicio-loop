"""Tests for coverage: ensure PR criteria are covered by changes."""
from __future__ import annotations

import pytest

from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import CheckResult, PASS, FAIL, SKIPPED
from simplicio_loop.review_gate.coverage import criteria, closes, check_coverage


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
        issue_body = "- [ ] task 1\n- [ ] task 2\n"
        changes = [FileChange("file1.py", "A", (1,))]
        added_text = {"file1.py": "# task 1 only\n"}
        pr_body = "Parte de #123\nFalta:\n- [ ] task 2\n"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == PASS
        assert result.measured["partial"]

    def test_partial_fail_without_parte_de(self):
        """Partial coverage without 'Parte de' fails."""
        issue_body = "- [ ] task 1\n- [ ] task 2\n"
        changes = [FileChange("file1.py", "A", (1,))]
        added_text = {"file1.py": "# task 1\n"}
        pr_body = "Does something\n"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == FAIL

    def test_partial_fail_with_closes(self):
        """Partial coverage with closes keyword fails (unless it's Parte de)."""
        issue_body = "- [ ] task 1\n- [ ] task 2\n"
        changes = [FileChange("file1.py", "A", (1,))]
        added_text = {"file1.py": "# task 1\n"}
        pr_body = "closes #123"

        result = check_coverage(123, issue_body, changes, added_text, pr_body)
        assert result.status == FAIL

    def test_partial_fail_without_falta_list(self):
        """Partial coverage with 'Parte de' but no Falta list fails."""
        issue_body = "- [ ] task 1\n- [ ] task 2\n"
        changes = [FileChange("file1.py", "A", (1,))]
        added_text = {"file1.py": "# task 1\n"}
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

        # "write" (5 letters), "authentication" (14), "system" (6) = 3 words
        # Only "authentication" matches -> 1/3 = 33% < 50% -> FAIL
        result = check_coverage(123, issue_body, changes, added_text, "just a PR")
        assert result.status == FAIL

    def test_coverage_by_path_token(self):
        """Criteria with path token is covered by file creation."""
        issue_body = "- [ ] create src/handlers.py\n"
        changes = [FileChange("src/handlers.py", "A", (1,))]
        added_text = {"src/handlers.py": "def handle_request():\n    pass\n"}

        result = check_coverage(123, issue_body, changes, added_text, "closes #123")
        assert result.status == PASS
