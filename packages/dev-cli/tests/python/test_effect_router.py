"""Unit + regression tests for the issue #709 effect router.

Fixtures required by the issue's acceptance criteria: edit ok, preimage
miss, codegen whitelist hit, llm full-file rejected -- plus the escalation
state machine and the execution-report receipt.
"""

from __future__ import annotations

from simplicio.effect_router import (
    EXECUTION_REPORT_SCHEMA,
    ROUTER_DECISION_SCHEMA,
    EffectMode,
    EscalationState,
    build_execution_report,
    classify,
    reject_full_file_llm_edit,
    validate_llm_edit,
)

# --- classify(): Edit ------------------------------------------------------


def test_classify_edit_ok_unique_anchor() -> None:
    task = {"path": "a.py", "old": "def foo():", "exact_span": True}
    hits = [{"path": "a.py", "occurrences": 1, "sha256": "abc"}]

    decision = classify(task, hits)

    assert decision.mode is EffectMode.MECHANICAL_EDIT
    assert decision.reason_code == "exact_span_unique"
    assert decision.refused is False
    payload = decision.to_dict()
    assert payload["schema"] == ROUTER_DECISION_SCHEMA
    assert payload["mode"] == "mechanical_edit"


def test_classify_edit_with_matching_preimage_hash_still_routes_edit() -> None:
    task = {
        "path": "a.py",
        "old": "def foo():",
        "exact_span": True,
        "expected_sha256": "sha256:abc",
    }
    hits = [{"path": "a.py", "occurrences": 1, "sha256": "abc"}]

    decision = classify(task, hits)

    assert decision.mode is EffectMode.MECHANICAL_EDIT


# --- classify(): preimage miss (fail-closed, no escalation) ---------------


def test_classify_preimage_miss_is_refused_not_promoted() -> None:
    task = {
        "path": "a.py",
        "old": "def foo():",
        "exact_span": True,
        "expected_sha256": "abc",
    }
    hits = [{"path": "a.py", "occurrences": 1, "sha256": "different"}]

    decision = classify(task, hits)

    assert decision.mode is None
    assert decision.refused is True
    assert decision.reason_code == "preimage_miss"


def test_classify_ambiguous_anchor_is_refused() -> None:
    task = {"path": "a.py", "old": "def foo():", "exact_span": True}
    hits = [{"path": "a.py", "occurrences": 3, "sha256": "abc"}]

    decision = classify(task, hits)

    assert decision.mode is None
    assert decision.refused is True
    assert decision.reason_code == "ambiguous_anchor"


# --- classify(): Codegen whitelist hit -------------------------------------


def test_classify_codegen_whitelist_hit() -> None:
    task = {"path": "models.py", "transform": "python-add-orm-field"}

    decision = classify(task, mapper_hits=None, codegen_registry=["python-add-orm-field"])

    assert decision.mode is EffectMode.CODEGEN
    assert decision.reason_code == "codegen_whitelist_hit"


def test_classify_uses_real_scratch_codegen_registry_by_default() -> None:
    task = {"path": "models.py", "transform": "python-add-orm-field"}

    decision = classify(task)

    assert decision.mode is EffectMode.CODEGEN


def test_classify_transform_not_on_whitelist_falls_to_llm() -> None:
    task = {"path": "models.py", "transform": "not-a-real-transform"}

    decision = classify(task, codegen_registry=["python-add-orm-field"])

    assert decision.mode is EffectMode.LLM


# --- classify(): 0 hits / uncertainty -> Llm --------------------------------


def test_classify_zero_hits_falls_to_llm() -> None:
    task = {"path": "unknown.py", "old": "needle", "exact_span": True}

    decision = classify(task, mapper_hits=[])

    assert decision.mode is EffectMode.LLM
    assert decision.reason_code == "no_exact_span_no_codegen_match"


def test_classify_no_task_fields_falls_to_llm() -> None:
    decision = classify({"path": "unknown.py"})

    assert decision.mode is EffectMode.LLM


# --- Mode 3 budget guard: full-file rejection ------------------------------


def test_llm_full_file_edit_is_rejected() -> None:
    file_size = 1000
    new_text = "x" * 950

    assert reject_full_file_llm_edit(old=None, new=new_text, file_size=file_size) is True
    errors = validate_llm_edit(old=None, new=new_text, file_size=file_size)
    assert errors[0]["code"] == "full_file_generation_rejected"


def test_llm_full_file_edit_rejected_with_blank_old() -> None:
    assert reject_full_file_llm_edit(old="", new="y" * 950, file_size=1000) is True


def test_llm_bounded_edit_is_accepted() -> None:
    file_size = 1000
    new_text = "x" * 20

    assert reject_full_file_llm_edit(old=None, new=new_text, file_size=file_size) is False
    assert validate_llm_edit(old=None, new=new_text, file_size=file_size) == []


def test_llm_edit_with_old_anchor_never_counts_as_full_file_even_if_large() -> None:
    # A real anchor-based edit is never "full-file generation" by definition
    # -- the guard only fires on an EMPTY/blank old.
    assert reject_full_file_llm_edit(old="def foo():", new="x" * 950, file_size=1000) is False


def test_llm_full_file_edit_on_new_file_with_zero_size_is_rejected_when_new_nonempty() -> None:
    assert reject_full_file_llm_edit(old=None, new="hello", file_size=0) is True
    assert reject_full_file_llm_edit(old=None, new="", file_size=0) is False


# --- Escalation state machine ----------------------------------------------


def test_escalation_retries_same_mode_once_then_escalates() -> None:
    state = EscalationState(EffectMode.MECHANICAL_EDIT)

    first = state.record_failure()
    assert first is EffectMode.MECHANICAL_EDIT  # retry, same mode

    second = state.record_failure()
    assert second is EffectMode.CODEGEN  # second consecutive failure escalates

    third = state.record_failure()
    assert third is EffectMode.CODEGEN  # retry again in the new mode

    fourth = state.record_failure()
    assert fourth is EffectMode.LLM

    assert state.history == (EffectMode.MECHANICAL_EDIT, EffectMode.CODEGEN, EffectMode.LLM)


def test_escalation_never_descends_past_llm() -> None:
    state = EscalationState(EffectMode.LLM)

    state.record_failure()
    result = state.record_failure()

    assert result is EffectMode.LLM


def test_escalation_success_resets_retry_budget_without_descending_mode() -> None:
    state = EscalationState(EffectMode.MECHANICAL_EDIT)

    state.record_failure()  # attempt 1 fails -> still MECHANICAL_EDIT (retry)
    state.record_success()  # the retry succeeds
    state.record_failure()  # a later, unrelated failure -> still just a retry

    assert state.mode is EffectMode.MECHANICAL_EDIT

    state.record_failure()  # second consecutive failure without a success in between
    assert state.mode is EffectMode.CODEGEN


# --- Execution report -------------------------------------------------------


def test_build_execution_report_has_required_fields_and_is_deterministic() -> None:
    task = {"path": "a.py"}
    report = build_execution_report(
        mode=EffectMode.MECHANICAL_EDIT,
        task=task,
        tokens={"input": 12, "output": 0},
        patches=[{"path": "a.py", "before_sha256": "x", "after_sha256": "y"}],
        certify={"status": "passed", "checks": ["pytest"]},
    )

    assert report["schema"] == EXECUTION_REPORT_SCHEMA
    assert report["mode"] == "mechanical_edit"
    assert report["task_path"] == "a.py"
    assert report["tokens"] == {"input": 12, "output": 0}
    assert report["patches"] == [{"path": "a.py", "before_sha256": "x", "after_sha256": "y"}]
    assert report["certify"] == {"status": "passed", "checks": ["pytest"]}
    assert isinstance(report["report_digest"], str) and len(report["report_digest"]) == 64

    # Same inputs -> same digest, stable across repeated calls.
    again = build_execution_report(
        mode=EffectMode.MECHANICAL_EDIT,
        task=task,
        tokens={"input": 12, "output": 0},
        patches=[{"path": "a.py", "before_sha256": "x", "after_sha256": "y"}],
        certify={"status": "passed", "checks": ["pytest"]},
    )
    assert again["report_digest"] == report["report_digest"]


def test_build_execution_report_defaults_are_explicit_not_fabricated() -> None:
    report = build_execution_report(mode=EffectMode.LLM, task={"path": "b.py"})

    assert report["tokens"] == {"input": 0, "output": 0}
    assert report["patches"] == []
    assert report["certify"] == {"status": "pending"}
