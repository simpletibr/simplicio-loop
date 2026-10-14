"""Unit tests for `simplicio_loop.intake_gate` (issues #1465, #1434).

Tests cover:
- repo_opted_in: present/absent, enabled/disabled
- issue_admitted: label present/absent, author association
- triage: epic, empty body, vague, actionable
"""
from __future__ import annotations

import asyncio
import base64

import pytest

from simplicio_loop import intake_gate
from simplicio_loop.intake_gate import (
    IntakeGateError,
    TriageResult,
    admission_reason,
    issue_admitted,
    repo_config,
    repo_opted_in,
    triage,
)


def _gh_content(toml_text: str) -> bytes:
    return base64.b64encode(toml_text.encode("utf-8"))


class FakeGh:
    """Stand-in for `intake_gate._run_gh`; counts calls."""

    def __init__(self, returncode=0, stdout=b"", stderr=b"", delay=0.0):
        self.result = (returncode, stdout, stderr)
        self.delay = delay
        self.calls = []

    async def __call__(self, *args):
        self.calls.append(args)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


@pytest.fixture
def fake_gh(monkeypatch):
    def install(**kwargs):
        fake = FakeGh(**kwargs)
        monkeypatch.setattr(intake_gate, "_run_gh", fake)
        return fake

    return install


class TestRepoOptedIn:
    """repo_opted_in with the gh subprocess helper faked."""

    def test_enabled_true(self, fake_gh):
        fake = fake_gh(stdout=_gh_content("enabled = true\n"))
        assert asyncio.run(repo_opted_in("org/repo")) is True
        assert len(fake.calls) == 1
        assert "repos/org/repo/contents/.simplicio-loop/loop.toml" in fake.calls[0]

    def test_enabled_false(self, fake_gh):
        fake_gh(stdout=_gh_content("enabled = false\n"))
        assert asyncio.run(repo_opted_in("org/repo")) is False

    def test_enabled_missing_key(self, fake_gh):
        fake_gh(stdout=_gh_content('allowed_authors = ["a"]\n'))
        assert asyncio.run(repo_opted_in("org/repo")) is False

    def test_enabled_string_is_not_truthy(self, fake_gh):
        fake_gh(stdout=_gh_content('enabled = "false"\n'))
        assert asyncio.run(repo_opted_in("org/repo")) is False

    def test_absent_404(self, fake_gh):
        fake_gh(returncode=1, stderr=b"gh: Not Found (HTTP 404)")
        assert asyncio.run(repo_opted_in("org/repo")) is False

    def test_invalid_toml(self, fake_gh):
        fake_gh(stdout=_gh_content("enabled = = oops\n"))
        with pytest.raises(IntakeGateError) as exc_info:
            asyncio.run(repo_opted_in("org/repo"))
        assert exc_info.value.reason_code == "invalid_toml"

    def test_gh_failure_has_reason_code(self, fake_gh):
        fake_gh(returncode=4, stderr=b"auth required")
        with pytest.raises(IntakeGateError) as exc_info:
            asyncio.run(repo_opted_in("org/repo"))
        assert exc_info.value.reason_code == "gh_api_error"

    def test_timeout(self, fake_gh, monkeypatch):
        monkeypatch.setattr(intake_gate, "REPO_OPTED_IN_TIMEOUT", 0.01)
        fake_gh(stdout=_gh_content("enabled = true\n"), delay=1.0)
        with pytest.raises(IntakeGateError) as exc_info:
            asyncio.run(repo_opted_in("org/repo"))
        assert exc_info.value.reason_code == "repo_check_timeout"

    @pytest.mark.parametrize("repo", ["noslash", "/name", "owner/"])
    def test_invalid_repo_format(self, fake_gh, repo):
        fake = fake_gh()
        with pytest.raises(IntakeGateError) as exc_info:
            asyncio.run(repo_opted_in(repo))
        assert exc_info.value.reason_code == "invalid_repo"
        assert fake.calls == []

    def test_cache_within_tick(self, fake_gh):
        fake = fake_gh(stdout=_gh_content("enabled = true\n"))
        cache = {}
        assert asyncio.run(repo_opted_in("org/repo", cache=cache)) is True
        assert len(fake.calls) == 1
        assert asyncio.run(repo_opted_in("org/repo", cache=cache)) is True
        assert len(fake.calls) == 1  # second call: zero subprocess calls

    def test_cache_caches_absent_repo(self, fake_gh):
        fake = fake_gh(returncode=1, stderr=b"HTTP 404")
        cache = {}
        assert asyncio.run(repo_opted_in("org/repo", cache=cache)) is False
        assert asyncio.run(repo_opted_in("org/repo", cache=cache)) is False
        assert len(fake.calls) == 1

    def test_no_cache_means_fresh_lookup(self, fake_gh):
        fake = fake_gh(stdout=_gh_content("enabled = true\n"))
        asyncio.run(repo_opted_in("org/repo"))
        asyncio.run(repo_opted_in("org/repo"))
        assert len(fake.calls) == 2

    def test_allowed_authors_parsed(self, fake_gh):
        fake_gh(stdout=_gh_content('enabled = true\nallowed_authors = ["alice", "bob"]\n'))
        config = asyncio.run(repo_config("org/repo"))
        assert config["enabled"] is True
        assert config["allowed_authors"] == ["alice", "bob"]

    def test_allowed_authors_drive_admission(self, fake_gh):
        fake_gh(stdout=_gh_content('enabled = true\nallowed_authors = ["Alice"]\n'))
        config = asyncio.run(repo_config("org/repo"))
        issue = {
            "labels": [{"name": "loop:auto"}],
            "author_association": "NONE",
            "user": {"login": "alice"},
        }
        assert issue_admitted(issue, config) is True
        assert issue_admitted(issue, {}) is False


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
        assert admission_reason(issue) == "author_unknown"

    def test_reason_codes(self):
        labelled = [{"name": "loop:auto"}]
        assert admission_reason({"labels": [], "author_association": "OWNER"}) == "missing_label"
        assert admission_reason({"labels": labelled}) == "author_unknown"
        assert admission_reason({"labels": labelled, "author_association": "NONE"}) == "author_not_allowed"
        assert admission_reason({"labels": labelled, "author_association": "member"}) == "admitted"

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
        assert "épica" in result.clarifying_question.lower()

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

    def test_epic_label_uppercase(self):
        issue = {"title": "Large", "body": "description", "labels": ["EPIC"]}
        assert triage(issue).reason_code == "epic"

    def test_real_issue_format_criterios_header(self):
        """Issue in this repo's format (## Critérios with accent) is actionable."""
        issue = {
            "title": "[247][P1] Opt-in por repo e por issue",
            "body": (
                "Parte do epic #1429.\n\n## Contexto\nO watcher pega todo repo.\n\n"
                "## Critérios\n- [ ] Repo só entra com `.simplicio-loop/loop.toml`.\n"
            ),
            "labels": [{"name": "loop:auto"}],
        }
        result = triage(issue)
        assert result.verdict == "actionable"

    def test_real_issue_format_criterios_de_aceite(self):
        issue = {
            "title": "Ajustar gate",
            "body": "Contexto sem arquivos.\n\nCritérios de aceite\n- comportamento esperado ao iniciar",
            "labels": [],
        }
        assert triage(issue).verdict == "actionable"

    def test_questions_use_accents(self):
        epic = triage({"title": "[EPIC] x", "body": "", "labels": []})
        empty = triage({"title": "x", "body": "", "labels": []})
        vague = triage({"title": "x", "body": "Precisamos arrumar essa coisa quebrada.", "labels": []})
        assert "épica" in epic.clarifying_question
        assert "descrição" in empty.clarifying_question
        assert "executável" in vague.clarifying_question
