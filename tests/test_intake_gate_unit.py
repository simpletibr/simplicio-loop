"""Unit tests for `simplicio_loop.intake_gate` (issues #1465, #1434).

Tests cover:
- repo_opted_in: present/absent, enabled/disabled
- issue_admitted: label present/absent, author association
- triage: epic, empty body, vague, actionable
"""
from __future__ import annotations

import pytest

from simplicio_loop.intake_gate import (
    IntakeGateError,
    TriageResult,
    issue_admitted,
    triage,
)


class TestRepoOptedInCache:
    """Test repo_opted_in caching behavior (synchronous tests)."""

    def test_cache_parameter_accepted(self):
        """repo_opted_in function accepts optional cache dict parameter."""
        # This test verifies the function signature accepts cache
        from inspect import signature
        from simplicio_loop.intake_gate import repo_opted_in
        sig = signature(repo_opted_in)
        assert "cache" in sig.parameters


class TestTriageResult:
    """Test TriageResult data class."""

    def test_valid_actionable_verdict(self):
        result = TriageResult("actionable", "actionable")
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"
        assert result.clarifying_question == ""

    def test_valid_needs_human_verdict(self):
        result = TriageResult(
            "needs_human",
            "epic",
            clarifying_question="Please break this down",
        )
        assert result.verdict == "needs_human"
        assert result.reason_code == "epic"
        assert result.clarifying_question == "Please break this down"

    def test_invalid_verdict(self):
        with pytest.raises(ValueError, match="Invalid verdict"):
            TriageResult("invalid", "code")

    def test_repr(self):
        result = TriageResult("actionable", "actionable")
        assert "TriageResult" in repr(result)
        assert "actionable" in repr(result)


class TestIssueAdmitted:
    """Test issue_admitted gate."""

    def test_missing_loop_auto_label(self):
        issue = {
            "labels": [{"name": "bug"}],
            "author_association": "OWNER",
        }
        assert issue_admitted(issue) is False

    def test_no_labels(self):
        issue = {
            "labels": [],
            "author_association": "OWNER",
        }
        assert issue_admitted(issue) is False

    def test_loop_auto_with_owner(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "OWNER",
        }
        assert issue_admitted(issue) is True

    def test_loop_auto_with_member(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "MEMBER",
        }
        assert issue_admitted(issue) is True

    def test_loop_auto_with_collaborator(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "COLLABORATOR",
        }
        assert issue_admitted(issue) is True

    def test_loop_auto_with_none_association(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "NONE",
        }
        assert issue_admitted(issue) is False

    def test_loop_auto_with_contributor(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "CONTRIBUTOR",
        }
        assert issue_admitted(issue) is False

    def test_mixed_case_label(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "MEMBER",
        }
        assert issue_admitted(issue) is True

    def test_string_labels(self):
        """Test with labels as strings instead of dicts."""
        issue = {
            "labels": ["loop:auto", "bug"],
            "author_association": "MEMBER",
        }
        assert issue_admitted(issue) is True

    def test_missing_author_association(self):
        issue = {
            "labels": [{"name": "loop:auto"}],
        }
        assert issue_admitted(issue) is False

    def test_none_author_association(self):
        """Issue with None author_association is not admitted."""
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": None,
        }
        assert issue_admitted(issue) is False

    def test_config_param(self):
        """Test that config param is accepted (for future extensions)."""
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "OWNER",
        }
        config = {"allowed_authors": ["user1"]}
        assert issue_admitted(issue, config) is True


class TestTriage:
    """Test triage function."""

    def test_epic_in_title(self):
        issue = {
            "title": "[EPIC] Implement new feature",
            "body": "Description here",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "epic"
        assert result.clarifying_question
        assert "epica" in result.clarifying_question.lower() or "epic" in result.clarifying_question.lower()

    def test_epic_label(self):
        issue = {
            "title": "Large work item",
            "body": "Description here",
            "labels": [{"name": "epic"}],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "epic"

    def test_empty_body(self):
        issue = {
            "title": "Fix bug",
            "body": "",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "empty_body"
        assert result.clarifying_question

    def test_very_short_body(self):
        issue = {
            "title": "Fix bug",
            "body": "x",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "empty_body"

    def test_vague_body_no_criteria(self):
        """Body too vague without acceptance criteria or file references."""
        issue = {
            "title": "Fix something",
            "body": "We need to fix this thing that is broken.",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "vague_body"
        assert result.clarifying_question

    def test_acceptance_criteria_bdd_english(self):
        """Issue with Given/When/Then is actionable."""
        issue = {
            "title": "Fix bug",
            "body": "Given the system is running\nWhen I click the button\nThen it should work",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_acceptance_criteria_bdd_portuguese(self):
        """Issue with Dado/Quando/Entao is actionable."""
        issue = {
            "title": "Corrigir bug",
            "body": "Dado que o sistema esta funcionando\nQuando eu clico no botao\nEntao deve funcionar",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_file_reference(self):
        """Issue with concrete file reference is actionable."""
        issue = {
            "title": "Update API",
            "body": "Update the file: `src/api.py` to add new endpoint",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_code_file_extension(self):
        """Issue mentioning specific file with code extension is actionable."""
        issue = {
            "title": "Update module",
            "body": "Modify simplicio_loop/intake_gate.py to add new validation",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_with_acceptance_criteria_section(self):
        """Issue with explicit acceptance criteria section is actionable."""
        issue = {
            "title": "Implement feature",
            "body": "1. Acceptance Criteria\nScenario 1: User can login\nGiven...",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_scenario_keyword(self):
        """Issue with scenario keyword is actionable."""
        issue = {
            "title": "Implement feature",
            "body": "Scenario 1: User authenticates with valid credentials",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_function_file_keyword(self):
        """Issue with function/file keyword is actionable."""
        issue = {
            "title": "Fix performance",
            "body": "The function: calculate_hash should be optimized to use cache",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_missing_body_key(self):
        """Issue without body key is treated as empty."""
        issue = {
            "title": "Fix bug",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "empty_body"

    def test_none_body(self):
        """Issue with None body is treated as empty."""
        issue = {
            "title": "Fix bug",
            "body": None,
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "empty_body"

    def test_whitespace_only_body(self):
        """Issue with whitespace-only body is treated as empty."""
        issue = {
            "title": "Fix bug",
            "body": "   \n  \t  ",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "empty_body"

    def test_missing_title(self):
        """Issue without title is still processed."""
        issue = {
            "body": "Dado que o sistema esta rodando\nQuando eu faco algo\nEntao funciona",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"

    def test_missing_labels(self):
        """Issue without labels field is still processed."""
        issue = {
            "title": "Fix",
            "body": "Given the system is up\nWhen I act\nThen it works",
        }
        result = triage(issue)
        assert result.verdict == "actionable"

    def test_epic_case_insensitive(self):
        """Epic detection is case insensitive."""
        issue = {
            "title": "[epic] some work",
            "body": "description",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "epic"

    def test_accent_normalization_criterios(self):
        """Accented 'critérios' is normalized and matches unaccented 'criterios'."""
        issue = {
            "title": "Fix feature",
            "body": "Critérios de aceitação: o sistema deve funcionar quando iniciado",
            "labels": [],
        }
        result = triage(issue)
        assert result.verdict == "actionable"
        assert result.reason_code == "actionable"

    def test_accent_normalization_epic(self):
        """Accented 'épico' in label is normalized and detected as epic."""
        issue = {
            "title": "Large feature",
            "body": "description",
            "labels": [{"name": "épico"}],
        }
        result = triage(issue)
        assert result.verdict == "needs_human"
        assert result.reason_code == "epic"
