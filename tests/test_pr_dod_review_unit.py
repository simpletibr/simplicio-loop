"""Unit tests for scripts/pr_dod_review.py — PR review against DoD + issue acceptance criteria.

Built so a session that finds all open issues already claimed by other agents can still
contribute value: mechanically checking whether an open PR satisfies AGENTS.md's 7-dimension
Definition of Done and the issue's own frozen acceptance-criteria checklist, instead of a
vibe-based approval.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pr_dod_review", ROOT / "scripts" / "pr_dod_review.py")
pr_dod_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr_dod_review)  # type: ignore[union-attr]


def test_extract_ac_items_parses_checked_and_unchecked():
    body = "## AC\n- [x] done thing\n- [ ] pending thing\n- [X] also done (capital X)\n"
    items = pr_dod_review.extract_ac_items(body)
    assert items == [
        {"text": "done thing", "checked": True},
        {"text": "pending thing", "checked": False},
        {"text": "also done (capital X)", "checked": True},
    ]


def test_extract_ac_items_empty_for_no_checklist():
    assert pr_dod_review.extract_ac_items("just prose, no checklist") == []


def test_review_flags_all_dimensions_missing_for_bare_summary():
    result = pr_dod_review.review("## Summary\nSmall change.\n")
    assert result["verdict"] == "GAPS_FOUND"
    assert "implementacao" in result["missing_dod"]
    assert "testes_unitarios" in result["missing_dod"]
    assert "cobertura_minima" in result["missing_dod"]


def test_review_compliant_when_all_dimensions_present():
    body = (
        "## Summary\nImplemented feature X.\n\n"
        "Unit tests cover Y. Integration tests hit the real DB. "
        "Ran a full end-to-end system test. Regression suite green. "
        "Benchmark: latency 12ms -> 4ms. Coverage 91%.\n"
    )
    result = pr_dod_review.review(body)
    assert result["verdict"] == "COMPLIANT"
    assert result["missing_dod"] == []


def test_review_allows_explicit_not_applicable():
    body = (
        "## Summary\nUpdated documentation only; no runtime code.\n\n"
        "Not applicable for this PR — no new logic, no cross-service seam, no full run flow, "
        "nothing that could regress, no hot path, nothing to measure.\n"
    )
    result = pr_dod_review.review(body)
    assert result["missing_dod"] == []
    non_impl = [d for d in result["dod"] if d["dimension"] != "implementacao"]
    assert all(d["skipped_with_reason"] for d in non_impl)


def test_review_unresolved_acs_reported():
    issue_body = "## Critérios\n- [x] a\n- [ ] b\n- [ ] c\n"
    result = pr_dod_review.review("## Summary\nx\n", issue_body)
    assert result["ac_items_total"] == 3
    assert result["unresolved_acs"] == ["b", "c"]


def test_review_ac_resolved_when_pr_cites_nearby_evidence():
    issue_body = "## Critérios\n- [ ] handles empty input\n"
    pr_body = "## Summary\nx\n\nhandles empty input -> verified with test_empty.py, PASS.\n"
    result = pr_dod_review.review(pr_body, issue_body)
    assert result["unresolved_acs"] == []


def test_review_ac_not_resolved_by_mere_mention_without_evidence_words():
    issue_body = "## Critérios\n- [ ] handles empty input\n"
    pr_body = "## Summary\nx\n\nWe discuss handles empty input somewhere but say nothing else.\n"
    result = pr_dod_review.review(pr_body, issue_body)
    assert result["unresolved_acs"] == ["handles empty input"]


def test_review_verdict_gaps_found_when_ac_unresolved_even_if_dod_complete():
    complete_dod_body = (
        "## Summary\nImplemented X.\n\nUnit tests passed. Integration tests passed. "
        "End-to-end system test passed. Regression green. "
        "Benchmark improved from 12ms to 4ms. Coverage 90%.\n"
    )
    issue_body = "## Critérios\n- [ ] still pending\n"
    result = pr_dod_review.review(complete_dod_body, issue_body)
    assert result["verdict"] == "GAPS_FOUND"
    assert result["unresolved_acs"] == ["still pending"]


def test_render_comment_includes_pr_and_issue_numbers():
    result = pr_dod_review.review("## Summary\nx\n")
    comment = pr_dod_review.render_comment(result, pr_number=42, issue_number=7)
    assert "PR #42" in comment
    assert "issue #7" in comment
    assert "MISSING" in comment


def test_render_comment_compliant_has_no_action_needed_line():
    body = (
        "## Summary\nImplemented X.\n\nUnit tests passed. Integration tests passed. "
        "End-to-end system test passed. Regression green. "
        "Benchmark improved from 12ms to 4ms. Coverage 90%.\n"
    )
    result = pr_dod_review.review(body)
    comment = pr_dod_review.render_comment(result)
    assert "No mechanical gaps found" in comment


def test_review_rejects_negative_keyword_soup_and_low_coverage():
    body = (
        "## Summary\nAttempted implementation.\n\n"
        "Unit tests FAILED; Integration NOT RUN; E2E BROKEN; regression RED; "
        "benchmark missing; coverage 1%."
    )
    result = pr_dod_review.review(body)
    assert result["verdict"] == "GAPS_FOUND"
    assert set(result["missing_dod"]) == {
        "implementacao", "testes_unitarios", "testes_integracao", "testes_sistema",
        "testes_regressao", "performance_benchmark", "cobertura_minima",
    }


def test_review_does_not_accept_negated_ac_evidence():
    issue_body = "## AC\n- [ ] handles empty input\n"
    pr_body = "## Summary\nhandles empty input — tests FAILED and verification NOT RUN.\n"
    result = pr_dod_review.review(pr_body, issue_body)
    assert result["unresolved_acs"] == ["handles empty input"]


def test_review_rejects_negations_contractions_and_noncurrent_coverage():
    body = (
        "## Summary\nUnit tests aren't passing. Integration hasn't green status. "
        "The system test didn't improve. Regression is not green. "
        "Benchmark not improved. Coverage was 91% historically; target coverage is 95%.\n"
    )
    result = pr_dod_review.review(body)
    assert set(result["missing_dod"]) == {
        "implementacao", "testes_unitarios", "testes_integracao", "testes_sistema",
        "testes_regressao", "performance_benchmark", "cobertura_minima",
    }


def test_review_uses_current_coverage_measurement_not_historical_maximum():
    result = pr_dod_review.review("## Summary\nCoverage is 84%; previous coverage was 99%.\n")
    assert "cobertura_minima" in result["missing_dod"]


def test_review_rejects_adversarial_negative_evidence_and_regression():
    body = (
        "## Summary\nImplementation missing. Unit tests did not pass. "
        "Integration tests did not pass. End-to-end tests did not pass. "
        "Regression tests did not pass. Benchmark latency regressed 4ms -> 12ms. "
        "Coverage 99% before; current coverage 40%.\n"
    )
    result = pr_dod_review.review(body)
    assert result["verdict"] == "GAPS_FOUND"
    assert set(result["missing_dod"]) == {
        "implementacao", "testes_unitarios", "testes_integracao", "testes_sistema",
        "testes_regressao", "performance_benchmark", "cobertura_minima",
    }


def test_review_latest_failure_revokes_earlier_positive_evidence():
    body = (
        "## Summary\nImplemented X.\n"
        "Unit tests passed. Unit tests failed now.\n"
        "Integration tests passed. Integration tests failed now.\n"
        "End-to-end tests passed. End-to-end tests failed now.\n"
        "Regression tests passed. Regression tests failed now.\n"
        "Benchmark latency improved 12ms -> 4ms. "
        "Benchmark latency regressed 4ms -> 12ms.\n"
        "Coverage 99%. Current coverage 40%."
    )
    result = pr_dod_review.review(body)
    assert result["verdict"] == "GAPS_FOUND"
    assert set(result["missing_dod"]) == {
        "testes_unitarios", "testes_integracao", "testes_sistema",
        "testes_regressao", "performance_benchmark", "cobertura_minima",
    }


def test_review_rejects_empty_or_explicitly_absent_implementation():
    for body in (
        "## Summary\nNo implementation.\n",
        "## Summary\nUnit tests passed.\n",
        "## Summary\nDocumentation only.\n",
        "## Summary\nNothing was implemented.\n",
        "## Summary\nImplementation reverted.\n",
        "## Summary\nImplementation planned for tomorrow.\n",
        "## Summary\nImplementation will be added later.\n",
    ):
        result = pr_dod_review.review(body)
        assert "implementacao" in result["missing_dod"], body


def test_review_rejects_aspirational_and_historical_ac_evidence():
    issue_body = "## AC\n- [ ] handles empty input\n"
    for statement in (
        "handles empty input should pass after the planned fix",
        "handles empty input passed in the previous release",
    ):
        result = pr_dod_review.review("## Summary\nImplemented X.\n" + statement, issue_body)
        assert result["unresolved_acs"] == ["handles empty input"]


def test_review_ac_positive_word_inside_requirement_is_not_evidence():
    issue_body = "## AC\n- [ ] Return verified receipts\n"
    result = pr_dod_review.review(
        "## Summary\nImplemented X.\nReturn verified receipts\n", issue_body,
    )
    assert result["unresolved_acs"] == ["Return verified receipts"]


def test_review_na_cannot_hide_a_current_failure_in_either_order():
    rest = (
        "Integration tests passed. End-to-end tests passed. Regression tests passed. "
        "Benchmark latency improved 12ms -> 4ms. Coverage 90%."
    )
    for unit in (
        "Unit tests N/A: no new logic. Unit tests failed now. ",
        "Unit tests failed now. Unit tests N/A: no new logic. ",
    ):
        result = pr_dod_review.review("Implemented X. " + unit + rest)
        assert "testes_unitarios" in result["missing_dod"]
        assert result["verdict"] == "GAPS_FOUND"


@pytest.mark.parametrize(
    "body",
    [
        "Implemented X. Coverage 99%. Current coverage unavailable.",
        "Implemented X. Current coverage 99%. Coverage failed now.",
        "Implemented X. Coverage 99%. Coverage not run now.",
        "Implemented X. Coverage 99% yesterday.",
    ],
)
def test_review_current_textual_coverage_failure_or_historical_value_revokes(body):
    assert "cobertura_minima" in pr_dod_review.review(body)["missing_dod"]


@pytest.mark.parametrize(
    "body",
    [
        "Implemented X. Benchmark tests passed: 1 test.",
        "Implemented X. Benchmark issue 123 passed.",
        "Implemented X. Benchmark passed on 2026-07-20.",
    ],
)
def test_review_benchmark_requires_a_performance_metric(body):
    assert "performance_benchmark" in pr_dod_review.review(body)["missing_dod"]


def test_review_rejects_future_historical_tests_and_generic_current_failure():
    for body in (
        "Implemented X. Unit tests will run tomorrow.",
        "Implemented X. Unit tests expected to run later.",
        "Implemented X. Unit tests passed yesterday.",
        "Implemented X. Integration tests passed last week.",
    ):
        assert pr_dod_review.review(body)["verdict"] == "GAPS_FOUND"
    result = pr_dod_review.review(
        "Implemented X. Unit tests passed before these changes. Tests fail now."
    )
    assert "testes_unitarios" in result["missing_dod"]


@pytest.mark.parametrize(
    ("dimension", "historical_pass_current_failure", "historical_failure_current_pass"),
    [
        ("testes_unitarios", "Unit tests passed yesterday but fail now.", "Unit tests failed yesterday but pass now."),
        ("testes_integracao", "Integration tests passed yesterday but fail now.", "Integration tests failed yesterday but pass now."),
        ("testes_sistema", "End-to-end tests passed yesterday but fail now.", "End-to-end tests failed yesterday but pass now."),
        ("testes_regressao", "Regression tests passed yesterday but fail now.", "Regression tests failed yesterday but pass now."),
        ("performance_benchmark", "Benchmark passed yesterday but fails now.", "Benchmark failed yesterday but passed now: latency 12ms -> 4ms."),
        ("cobertura_minima", "Coverage 99% yesterday but unavailable now.", "Coverage failed yesterday but current coverage 91%."),
    ],
)
def test_review_contrast_uses_the_current_clause(
    dimension, historical_pass_current_failure, historical_failure_current_pass,
):
    assert dimension in pr_dod_review.review("Implemented X. " + historical_pass_current_failure)["missing_dod"]
    assert dimension not in pr_dod_review.review("Implemented X. " + historical_failure_current_pass)["missing_dod"]


def test_review_contrast_reverted_implementation_revokes_historical_claim():
    result = pr_dod_review.review("Implementation was implemented previously but reverted now.")
    assert "implementacao" in result["missing_dod"]


@pytest.mark.parametrize(
    ("dimension", "current_failure", "current_success"),
    [
        ("testes_unitarios", "Unit tests passed. They fail now.", "Unit tests failed yesterday. They pass now."),
        ("testes_integracao", "Integration tests passed. They fail now.", "Integration tests failed yesterday. They pass now."),
        ("testes_sistema", "End-to-end tests passed. They fail now.", "End-to-end tests failed yesterday. They pass now."),
        ("testes_regressao", "Regression tests passed. They fail now.", "Regression tests failed yesterday. They pass now."),
        ("performance_benchmark", "Benchmark latency improved 12ms -> 4ms. It fails now.", "Benchmark failed yesterday. It passed now: latency 12ms -> 4ms."),
        ("cobertura_minima", "Coverage 99%. It is unavailable now.", "Coverage failed yesterday. It is available now at coverage 91%."),
    ],
)
def test_review_anaphoric_sentence_uses_the_previous_dimension_subject(
    dimension, current_failure, current_success,
):
    assert dimension in pr_dod_review.review("Implemented X. " + current_failure)["missing_dod"]
    assert dimension not in pr_dod_review.review("Implemented X. " + current_success)["missing_dod"]


@pytest.mark.parametrize(
    ("dimension", "current_failure", "current_success"),
    [
        ("testes_unitarios", "Unit tests passed. Now they fail.", "Unit tests failed yesterday. Now they pass."),
        ("testes_integracao", "Integration tests passed. This now fails.", "Integration tests failed yesterday. This now passes."),
        ("testes_sistema", "End-to-end tests passed. Now they fail.", "End-to-end tests failed yesterday. Now they pass."),
        ("testes_regressao", "Regression tests passed. This now fails.", "Regression tests failed yesterday. This now passes."),
        ("performance_benchmark", "Benchmark latency improved 12ms -> 4ms. Now it regressed.", "Benchmark failed yesterday. Now it passed: latency 12ms -> 4ms."),
        ("cobertura_minima", "Coverage 99%. Now it is unavailable.", "Coverage failed yesterday. Now it is available at coverage 91%."),
    ],
)
def test_review_current_prefix_and_demonstrative_keep_dimension_context(
    dimension, current_failure, current_success,
):
    assert dimension in pr_dod_review.review("Implemented X. " + current_failure)["missing_dod"]
    assert dimension not in pr_dod_review.review("Implemented X. " + current_success)["missing_dod"]


@pytest.mark.parametrize(
    ("dimension", "current_failure", "current_success"),
    [
        ("testes_unitarios", "Unit tests passed yesterday, and now they fail.", "Unit tests failed yesterday, and now they pass."),
        ("testes_integracao", "Integration tests passed yesterday, and now they fail.", "Integration tests failed yesterday, and now they pass."),
        ("testes_sistema", "End-to-end tests passed yesterday, and now they fail.", "End-to-end tests failed yesterday, and now they pass."),
        ("testes_regressao", "Regression tests passed yesterday, and now they fail.", "Regression tests failed yesterday, and now they pass."),
        ("performance_benchmark", "Benchmark improved to 4ms yesterday, and now it regressed.", "Benchmark failed yesterday, and now it passed: latency 12ms -> 4ms."),
        ("cobertura_minima", "Coverage 99% yesterday, and now it is unavailable.", "Coverage failed yesterday, and now it is available at coverage 91%."),
    ],
)
def test_review_and_now_contrast_uses_only_the_current_clause(
    dimension, current_failure, current_success,
):
    assert dimension in pr_dod_review.review("Implemented X. " + current_failure)["missing_dod"]
    assert dimension not in pr_dod_review.review("Implemented X. " + current_success)["missing_dod"]


def test_review_anaphora_does_not_cross_into_an_unrelated_dimension():
    body = "Implemented X. Unit tests passed. Coverage 91%. Now it is unavailable."
    missing = pr_dod_review.review(body)["missing_dod"]
    assert "testes_unitarios" not in missing
    assert "cobertura_minima" in missing


@pytest.mark.parametrize(
    ("failed_dimension", "failure", "recovery"),
    [
        ("testes_unitarios", "Unit tests fail now.", "Unit tests pass now."),
        ("testes_integracao", "Integration tests fail now.", "Integration tests pass now."),
        ("testes_sistema", "End-to-end tests fail now.", "End-to-end tests pass now."),
        ("testes_regressao", "Regression tests fail now.", "Regression tests pass now."),
    ],
)
def test_review_named_test_failure_is_isolated_to_its_lane(
    failed_dimension, failure, recovery,
):
    test_dimensions = {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    }
    all_green = (
        "Unit tests passed. Integration tests passed. End-to-end tests passed. "
        "Regression tests passed. "
    )
    missing_after_failure = set(
        pr_dod_review.review("Implemented X. " + all_green + failure)["missing_dod"]
    ) & test_dimensions
    assert missing_after_failure == {failed_dimension}

    missing_after_recovery = set(
        pr_dod_review.review("Implemented X. " + all_green + failure + " " + recovery)["missing_dod"]
    ) & test_dimensions
    assert missing_after_recovery == set()


def test_review_unqualified_test_failure_conservatively_revokes_all_test_lanes():
    body = (
        "Implemented X. Unit tests passed. Integration tests passed. "
        "End-to-end tests passed. Regression tests passed. Tests fail now."
    )
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    } <= missing


def test_review_singular_system_test_can_fail_and_recover():
    base = (
        "Implemented X. Unit tests passed. Integration tests passed. "
        "Regression tests passed. "
    )
    failed = pr_dod_review.review(base + "System test fails now.")
    assert "testes_sistema" in failed["missing_dod"]
    recovered = pr_dod_review.review(
        base + "System test fails now. System test passes now.",
    )
    assert "testes_sistema" not in recovered["missing_dod"]


@pytest.mark.parametrize(
    ("lanes", "failure", "recovery"),
    [
        (
            {"testes_unitarios", "testes_integracao"},
            "Unit and integration tests fail now.",
            "Unit and integration tests pass now.",
        ),
        (
            {"testes_unitarios", "testes_integracao"},
            "Integration and unit tests fail now.",
            "Integration and unit tests pass now.",
        ),
        (
            {"testes_sistema", "testes_regressao"},
            "E2E and regression tests fail now.",
            "E2E and regression tests pass now.",
        ),
        (
            {"testes_sistema", "testes_regressao"},
            "Regression and E2E tests fail now.",
            "Regression and E2E tests pass now.",
        ),
        (
            {"testes_unitarios", "testes_integracao", "testes_regressao"},
            "Unit, integration, and regression tests fail now.",
            "Regression, integration and unit tests pass now.",
        ),
    ],
)
def test_review_coordinated_test_subjects_are_order_independent(lanes, failure, recovery):
    all_test_lanes = {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    }
    all_green = (
        "Implemented X. Unit tests passed. Integration tests passed. "
        "System tests passed. Regression tests passed. "
    )
    missing = set(pr_dod_review.review(all_green + failure)["missing_dod"])
    assert missing & all_test_lanes == lanes
    recovered = set(
        pr_dod_review.review(all_green + failure + " " + recovery)["missing_dod"]
    )
    assert recovered & all_test_lanes == set()


def test_review_named_failure_does_not_revoke_other_test_lane_na_reasons():
    body = (
        "Implemented X. Unit tests N/A: no new logic. "
        "Integration tests N/A: no integration seam. "
        "System tests N/A: no full run flow. "
        "Regression tests N/A: nothing that could regress. Unit tests fail now."
    )
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert missing & {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    } == {"testes_unitarios"}


@pytest.mark.parametrize(
    ("lanes", "statement"),
    [
        (
            {"testes_unitarios", "testes_integracao"},
            "Unit and integration tests passed. They fail now.",
        ),
        (
            {"testes_unitarios", "testes_integracao"},
            "Integration and unit tests passed. Now they fail.",
        ),
        (
            {"testes_unitarios", "testes_integracao"},
            "Unit and integration tests passed yesterday but fail now.",
        ),
        (
            {"testes_unitarios", "testes_integracao"},
            "Unit and integration tests passed yesterday, and now they fail.",
        ),
        (
            {"testes_unitarios", "testes_integracao", "testes_regressao"},
            "Regression, integration, and unit tests passed. They fail now.",
        ),
    ],
)
def test_review_anaphora_preserves_every_coordinated_lane(lanes, statement):
    all_test_lanes = {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    }
    all_green = (
        "Implemented X. Unit tests passed. Integration tests passed. "
        "System tests passed. Regression tests passed. "
    )
    missing = set(pr_dod_review.review(all_green + statement)["missing_dod"])
    assert missing & all_test_lanes == lanes


def test_review_anaphoric_recovery_restores_every_coordinated_lane():
    body = (
        "Implemented X. Unit tests passed. Integration tests passed. "
        "System tests passed. Regression tests passed. "
        "Unit and integration tests fail now. They pass now."
    )
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert not missing & {
        "testes_unitarios", "testes_integracao", "testes_sistema", "testes_regressao",
    }


@pytest.mark.parametrize(
    ("present", "missing", "statement"),
    [
        (
            {"testes_integracao"},
            {"testes_unitarios"},
            "Unit and integration tests failed yesterday, but integration now passes.",
        ),
        (
            {"testes_unitarios"},
            {"testes_integracao"},
            "Integration and unit tests failed yesterday, but unit now passes.",
        ),
        (
            {"testes_regressao"},
            {"testes_unitarios", "testes_integracao"},
            "Unit, integration, and regression tests failed yesterday, but regression now passes.",
        ),
    ],
)
def test_review_naked_lane_clause_replaces_coordinated_context(present, missing, statement):
    test_missing = set(pr_dod_review.review("Implemented X. " + statement)["missing_dod"])
    assert not present & test_missing
    assert missing <= test_missing


def test_review_naked_lane_current_failure_does_not_revoke_its_coordinated_peer():
    body = (
        "Implemented X. Unit and integration tests passed. "
        "Integration now fails."
    )
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert "testes_unitarios" not in missing
    assert "testes_integracao" in missing


@pytest.mark.parametrize(
    ("present", "missing", "statement"),
    [
        (
            {"testes_unitarios"},
            {"testes_integracao"},
            "Unit and integration tests passed, but now only unit passes.",
        ),
        (
            {"testes_integracao"},
            {"testes_unitarios"},
            "Integration and unit tests passed, but now only integration passes.",
        ),
        (
            {"testes_integracao"},
            {"testes_unitarios", "testes_regressao"},
            "Regression, unit, and integration tests passed, but now only integration passes.",
        ),
    ],
)
def test_review_only_positive_lane_replaces_prior_coordinated_state(present, missing, statement):
    test_missing = set(pr_dod_review.review("Implemented X. " + statement)["missing_dod"])
    assert not present & test_missing
    assert missing <= test_missing


@pytest.mark.parametrize(
    ("statement", "present"),
    [
        ("Benchmark latency improved 1000us -> 2ms.", False),
        ("Benchmark latency improved 2ms -> 1000us.", True),
        ("Benchmark latency improved 1000000ns -> 2ms.", False),
        ("Benchmark latency improved 2ms -> 1000000ns.", True),
        ("Benchmark throughput improved 900mb/s -> 1gb/s.", True),
        ("Benchmark throughput improved 1gb/s -> 900mb/s.", False),
        ("Benchmark throughput improved 100req/s -> 120ops/s.", True),
        ("Benchmark improved 100ops/s -> 2ms.", False),
        ("Benchmark throughput improved 2ms -> 1ms.", False),
        ("Benchmark latency improved 100ops/s -> 200ops/s.", False),
    ],
)
def test_review_benchmark_compares_only_normalized_compatible_units(statement, present):
    missing = pr_dod_review.review("Implemented X. " + statement)["missing_dod"]
    assert ("performance_benchmark" not in missing) is present


def test_review_comma_now_applies_current_failure_after_historical_pass():
    body = "Implemented X. Unit tests passed. Unit tests passed yesterday, now they fail."
    assert "testes_unitarios" in pr_dod_review.review(body)["missing_dod"]


def test_review_comma_now_applies_current_pass_after_historical_failure():
    body = "Implemented X. Unit tests failed yesterday, now they pass."
    assert "testes_unitarios" not in pr_dod_review.review(body)["missing_dod"]


def test_review_comma_separates_independent_test_lane_states():
    body = "Implemented X. Unit tests fail now, integration tests pass now."
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert "testes_unitarios" in missing
    assert "testes_integracao" not in missing


def test_review_comma_separates_failure_from_other_lane_na():
    body = (
        "Implemented X. Unit tests fail now, "
        "integration tests N/A: no integration seam."
    )
    result = pr_dod_review.review(body)
    missing = set(result["missing_dod"])
    assert "testes_unitarios" in missing
    assert "testes_integracao" not in missing
    integration = next(
        item for item in result["dod"] if item["dimension"] == "testes_integracao"
    )
    assert integration["status"] == "SKIPPED_WITH_REASON"


def test_review_comma_splitter_preserves_coordinated_lane_list():
    body = "Implemented X. Unit, integration, and E2E tests passed."
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert not missing & {"testes_unitarios", "testes_integracao", "testes_sistema"}


@pytest.mark.parametrize(
    ("integration_state", "integration_present"),
    [
        ("integration tests pass now", True),
        ("integration tests N/A: no integration seam", True),
        ("integration tests fail now", False),
    ],
)
def test_review_plain_and_separates_independent_lane_predicates(
    integration_state, integration_present,
):
    body = "Implemented X. Unit tests fail now and " + integration_state + "."
    result = pr_dod_review.review(body)
    missing = set(result["missing_dod"])
    assert "testes_unitarios" in missing
    assert ("testes_integracao" not in missing) is integration_present


def test_review_plain_and_does_not_split_coordinated_test_subject():
    body = "Implemented X. Unit and integration tests pass now."
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert not missing & {"testes_unitarios", "testes_integracao"}


@pytest.mark.parametrize(
    ("body", "present"),
    [
        ("Coverage 99% yesterday, now 40%.", False),
        ("Coverage was 99% yesterday and is 40% now.", False),
        ("Coverage 40% yesterday, now 91%.", True),
        ("Coverage was 40% yesterday and is 91% now.", True),
    ],
)
def test_review_coverage_ellipsis_uses_current_measurement(body, present):
    missing = pr_dod_review.review("Implemented X. " + body)["missing_dod"]
    assert ("cobertura_minima" not in missing) is present


def test_review_no_longer_pass_revokes_unit_and_current_pass_restores_it():
    failed = pr_dod_review.review(
        "Implemented X. Unit tests passed. Unit tests no longer pass now.",
    )
    assert "testes_unitarios" in failed["missing_dod"]
    recovered = pr_dod_review.review(
        "Implemented X. Unit tests no longer passed yesterday. Unit tests pass now.",
    )
    assert "testes_unitarios" not in recovered["missing_dod"]


def test_review_no_longer_improves_revokes_benchmark_and_current_improvement_restores_it():
    failed = pr_dod_review.review(
        "Implemented X. Benchmark latency improved 2ms -> 1ms. "
        "Benchmark no longer improves now.",
    )
    assert "performance_benchmark" in failed["missing_dod"]
    recovered = pr_dod_review.review(
        "Implemented X. Benchmark no longer improved yesterday. "
        "Benchmark latency improves now: 2ms -> 1ms.",
    )
    assert "performance_benchmark" not in recovered["missing_dod"]


@pytest.mark.parametrize(
    "rollback",
    ["Implementation rolled back now.", "Implementation rollback is current."],
)
def test_review_current_rollback_revokes_implementation(rollback):
    result = pr_dod_review.review("Implemented X. " + rollback)
    assert "implementacao" in result["missing_dod"]


def test_review_historical_rollback_does_not_override_current_implementation():
    result = pr_dod_review.review(
        "Implementation rolled back yesterday. Implemented X now.",
    )
    assert "implementacao" not in result["missing_dod"]


@pytest.mark.parametrize(
    ("current_clause", "present"),
    [
        ("current coverage is 91%", True),
        ("coverage is 91% now", True),
        ("is 91% now", True),
        ("current coverage is 40%", False),
        ("coverage is 40% now", False),
        ("is 40% now", False),
    ],
)
def test_review_coverage_comma_recognizes_explicit_and_elided_current_clause(
    current_clause, present,
):
    historical = "40" if present else "91"
    body = "Implemented X. Coverage was " + historical + "% yesterday, " + current_clause + "."
    missing = pr_dod_review.review(body)["missing_dod"]
    assert ("cobertura_minima" not in missing) is present


@pytest.mark.parametrize(
    "connector",
    [", only unit passes now", " and only unit passes now"],
)
def test_review_only_lane_after_comma_or_and_replaces_coordinated_state(connector):
    body = "Implemented X. Unit and integration tests passed" + connector + "."
    missing = set(pr_dod_review.review(body)["missing_dod"])
    assert "testes_unitarios" not in missing
    assert "testes_integracao" in missing


def test_review_semicolon_however_preserves_context_for_current_failure():
    body = "Implemented X. Unit tests passed; however, now they fail."
    assert "testes_unitarios" in pr_dod_review.review(body)["missing_dod"]


def test_review_semicolon_however_preserves_context_for_current_recovery():
    body = "Implemented X. Unit tests failed yesterday; however, now they pass."
    assert "testes_unitarios" not in pr_dod_review.review(body)["missing_dod"]


def test_review_rejects_regressed_latency_even_without_regressed_word():
    result = pr_dod_review.review("## Summary\nImplemented X. Benchmark latency 4ms -> 12ms.\n")
    assert "performance_benchmark" in result["missing_dod"]


def test_review_accepts_explicit_current_coverage_over_historical_context():
    result = pr_dod_review.review(
        "## Summary\nImplemented X. Previous coverage 40%; current coverage 91%.\n"
    )
    assert "cobertura_minima" not in result["missing_dod"]


def test_review_rejects_impossible_coverage_percentage():
    result = pr_dod_review.review("## Summary\nImplemented X. Current coverage 101%.\n")
    assert "cobertura_minima" in result["missing_dod"]


def test_review_ac_did_not_pass_remains_unresolved():
    issue_body = "## AC\n- [ ] handles empty input\n"
    result = pr_dod_review.review(
        "## Summary\nImplemented X. handles empty input did not pass verification.\n",
        issue_body,
    )
    assert result["unresolved_acs"] == ["handles empty input"]


def test_build_verdict_keeps_negated_ac_unresolved_and_not_ready():
    issue_body = "## AC\n- [ ] handles empty input\n"
    body = "## Summary\nhandles empty input was not verified; tests aren't passing.\n"
    verdict = pr_dod_review.build_verdict(body, issue_body)
    assert verdict["unresolved_acceptance_criteria"] == ["handles empty input"]
    assert verdict["ready_to_merge"] is False


def test_build_verdict_rejects_contradictory_current_evidence():
    body = (
        "## Summary\nImplemented X. Unit tests passed. Unit tests failed now. "
        "Integration tests passed. Integration tests failed now. "
        "End-to-end tests passed. End-to-end tests failed now. "
        "Regression tests passed. Regression tests failed now. "
        "Benchmark latency improved 12ms -> 4ms. "
        "Benchmark latency regressed 4ms -> 12ms. "
        "Coverage 99%. Current coverage 40%."
    )
    verdict = pr_dod_review.build_verdict(body, "## AC\n- [x] recorded")
    assert verdict["ready_to_merge"] is False
    assert verdict["dod_addressed"] == "1/7"


def test_build_verdict_rejects_textual_coverage_failure_and_requirement_keyword():
    body = (
        "Implemented X. Unit tests passed. Integration tests passed. End-to-end tests passed. "
        "Regression tests passed. Benchmark latency improved 12ms -> 4ms. "
        "Coverage 99%. Current coverage unavailable. Return verified receipts."
    )
    verdict = pr_dod_review.build_verdict(
        body, "## AC\n- [ ] Return verified receipts",
    )
    assert verdict["dod"]["min_coverage"]["addressed"] is False
    assert verdict["unresolved_acceptance_criteria"] == ["Return verified receipts"]
    assert verdict["ready_to_merge"] is False


def test_short_ac_requires_label_and_positive_evidence():
    issue_body = "## AC\n- [ ] b\n"
    accidental = pr_dod_review.review(
        "## Summary\nThe benchmark tests passed, but no criterion is cited.\n", issue_body,
    )
    assert accidental["unresolved_acs"] == ["b"]

    explicit = pr_dod_review.review("## Summary\nAC: b — verified, PASS.\n", issue_body)
    assert explicit["unresolved_acs"] == []


def test_selftest_passes():
    assert pr_dod_review.cmd_selftest({}) == 0
