"""Tests for the simplicio run intent classifier."""

import pytest

from simplicio.intent import AUTO_CONFIDENCE_THRESHOLD, classify_goal


def test_explicit_scope_wins_over_text():
    result = classify_goal("scaffold a new FastAPI app from scratch", explicit_scope="task")
    assert result.scope == "task"
    assert result.confidence == 1.0
    assert result.signals == ["explicit_scope:task"]


def test_invalid_explicit_scope_raises():
    with pytest.raises(ValueError):
        classify_goal("fix src/auth.py", explicit_scope="unknown")


def test_task_goal_with_file_and_verb():
    result = classify_goal("fix email validation in src/forms/UserForm.tsx")
    assert result.scope == "task"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "verb:fix" in result.signals
    assert "file:src/forms/UserForm.tsx" in result.signals


def test_portuguese_task_goal():
    result = classify_goal("corrija o botao admin em Header.tsx")
    assert result.scope == "task"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "verb:corrija" in result.signals
    assert "file:Header.tsx" in result.signals


def test_multiple_files_becomes_feature_not_task():
    result = classify_goal("update src/a.py and src/b.py for shared auth")
    assert result.scope == "feature"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD


def test_feature_goal_without_target_file():
    result = classify_goal("implement JWT login flow with refresh tokens")
    assert result.scope == "feature"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "feature:login" in result.signals


def test_sprint_goal():
    result = classify_goal("close sprint 12 and get checkout, billing, reports, and DoD green")
    assert result.scope == "sprint"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert any(signal.startswith("sprint:") for signal in result.signals)


def test_many_issue_refs_are_sprint():
    result = classify_goal("finish #41, #42, #43 and ship release DoD")
    assert result.scope == "sprint"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD


def test_scratch_goal():
    result = classify_goal("scaffold a new FastAPI project for condo units from scratch")
    assert result.scope == "scratch"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "scratch:from scratch" in result.signals
    assert "stack:fastapi" in result.signals


def test_new_endpoint_is_not_scratch():
    result = classify_goal("add a new /users endpoint to api.py")
    assert result.scope == "task"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD


def test_cross_repo_endpoint_alignment_is_sprint():
    result = classify_goal(
        "veja todas as telas, alinhe todos os endpoints da web com api e ai-agents"
    )

    assert result.scope == "sprint"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert any(signal.startswith("sprint:") for signal in result.signals)


def test_remaining_endpoint_backlog_is_sprint():
    result = classify_goal(
        "alinhar as 32 rotas restantes do ai-agents contra api .NET com fontes do mapper"
    )

    assert result.scope == "sprint"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "sprint:remaining_endpoint_inventory" in result.signals


def test_playwright_local_api_postgres_evidence_is_feature():
    result = classify_goal(
        "vamos usar playwright para evidenciar as telas web conectando ao api com banco postgresql local"
    )

    assert result.scope == "feature"
    assert result.confidence >= AUTO_CONFIDENCE_THRESHOLD
    assert "feature:real_stack_evidence" in result.signals


def test_read_only_goal_has_low_confidence():
    result = classify_goal("explain how the verify loop works")
    assert result.scope == "task"
    assert result.confidence < AUTO_CONFIDENCE_THRESHOLD
    assert result.signals == ["read_only:explain"]
