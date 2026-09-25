"""Unit tests for the quality-matrix module itself (#278) — no CLI, no oracle wiring."""
import json
import sys

from simplicio_loop.quality_matrix import (
    CHANGE_TYPES,
    DEFAULT_COVERAGE_THRESHOLD,
    QualityMatrixError,
    REQUIRED_REQUIREMENTS,
    TESTS_ENVELOPE_CATEGORIES,
    build_quality_matrix_template,
    classify_change_type,
    default_policy_for_change_type,
    evaluate_quality_matrix,
    sync_tests_envelope,
    validate_coverage_threshold,
)


def _passing_receipt(**overrides):
    receipt = {
        "schema": "simplicio.quality-matrix/v1",
        "coverage_threshold": 85,
        "requirements": {
            name: {"status": "pass", "proof_ref": f"tests/{name}"} for name in REQUIRED_REQUIREMENTS
        },
        "coverage": {"measured": 90.0},
    }
    receipt.update(overrides)
    return receipt


def test_default_threshold_is_eighty_five():
    assert DEFAULT_COVERAGE_THRESHOLD == 85.0


def test_all_required_lanes_present():
    assert set(REQUIRED_REQUIREMENTS) == {
        "implementation", "unit", "integration", "system", "regression", "benchmark",
    }


def test_validate_coverage_threshold_accepts_bounds():
    assert validate_coverage_threshold(0) == 0.0
    assert validate_coverage_threshold(100) == 100.0
    assert validate_coverage_threshold(85.5) == 85.5


def test_validate_coverage_threshold_rejects_out_of_range():
    for bad in (-1, 100.1, 250, -0.001):
        try:
            validate_coverage_threshold(bad)
        except QualityMatrixError:
            pass
        else:
            raise AssertionError(f"expected QualityMatrixError for {bad!r}")


def test_validate_coverage_threshold_rejects_non_numeric_and_bool():
    for bad in ("85", None, [], {}, True, False):
        try:
            validate_coverage_threshold(bad)
        except QualityMatrixError:
            pass
        else:
            raise AssertionError(f"expected QualityMatrixError for {bad!r}")


def test_missing_receipt_fails_closed(tmp_path):
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_matrix_missing"


def test_passing_receipt_is_ready(tmp_path):
    (tmp_path / "quality-matrix.json").write_text(json.dumps(_passing_receipt()), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True
    assert verdict["reason_code"] == "quality_matrix_verified"
    assert verdict["coverage_threshold"] == 85.0
    assert verdict["coverage_measured"] == 90.0


def test_each_missing_requirement_blocks_individually(tmp_path):
    for name in REQUIRED_REQUIREMENTS:
        receipt = _passing_receipt()
        del receipt["requirements"][name]
        (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(tmp_path))
        assert verdict["ready"] is False, name
        assert verdict["reason_code"] == f"quality_{name}_missing", name


def test_each_failing_requirement_blocks_individually(tmp_path):
    for name in REQUIRED_REQUIREMENTS:
        receipt = _passing_receipt()
        receipt["requirements"][name] = {"status": "fail", "proof_ref": "x"}
        (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(tmp_path))
        assert verdict["ready"] is False, name
        assert verdict["reason_code"] == f"quality_{name}_failed", name


def test_requirement_without_proof_ref_is_unproven(tmp_path):
    receipt = _passing_receipt()
    receipt["requirements"]["unit"] = {"status": "pass", "proof_ref": ""}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_unit_unproven"


def test_coverage_below_threshold_blocks(tmp_path):
    receipt = _passing_receipt(coverage={"measured": 84.9})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "coverage_below_threshold"
    assert verdict["coverage_measured"] == 84.9


def test_coverage_exactly_at_threshold_passes(tmp_path):
    receipt = _passing_receipt(coverage={"measured": 85.0})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True


def test_coverage_missing_or_non_numeric_blocks(tmp_path):
    for bad in ({"measured": None}, {}, {"measured": "90"}, {"measured": True}):
        receipt = _passing_receipt(coverage=bad)
        (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
        verdict = evaluate_quality_matrix(str(tmp_path))
        assert verdict["ready"] is False, bad
        assert verdict["reason_code"] == "coverage_unmeasured", bad


def test_custom_coverage_threshold_is_honored(tmp_path):
    receipt = _passing_receipt(coverage_threshold=95, coverage={"measured": 90.0})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "coverage_below_threshold"
    assert verdict["coverage_threshold"] == 95.0


def test_invalid_coverage_threshold_config_fails_closed_not_default(tmp_path):
    receipt = _passing_receipt(coverage_threshold=150)
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "coverage_threshold_invalid"


def test_build_quality_matrix_template_is_all_unset_never_a_passing_default():
    template = build_quality_matrix_template()
    for name in REQUIRED_REQUIREMENTS:
        assert template["requirements"][name]["status"] == "unset"
    assert template["coverage"]["measured"] is None
    assert "policy" not in template  # no change_type -> exact #278 shape, no regression


# --- #283: opt-in TDD lane -------------------------------------------------------


def test_receipt_without_policy_never_evaluates_tdd_no_regression():
    # A plain #278-shaped receipt (no "policy", no "tdd") must keep passing exactly
    # as before -- TDD is opt-in, never silently mandatory.
    receipt = _passing_receipt()
    assert "policy" not in receipt and "tdd" not in receipt["requirements"]


def test_tdd_lane_not_evaluated_without_policy_opt_in(tmp_path):
    receipt = _passing_receipt()
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True  # tdd absent, but policy doesn't require it


def test_verdict_propagates_run_id_and_work_item(tmp_path):
    # #283: the issue-envelope fields run_id / work_item must surface on the
    # verdict (result) regardless of pass/fail, so a consumer reading them off
    # the verdict -- not the raw receipt -- gets a complete, round-trippable view.
    receipt = _passing_receipt(
        run_id="run-abc123",
        work_item={"source": "github", "id": 283},
    )
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["run_id"] == "run-abc123"
    assert verdict["work_item"] == {"source": "github", "id": 283}


def test_verdict_propagates_nested_tests_mirror(tmp_path):
    # #283: a receipt carrying the nested "tests" envelope must expose it on the
    # verdict; when absent, sync_tests_envelope fills a derived mirror.
    receipt = _passing_receipt(
        tests={
            "unit": {"status": "pass", "proof_ref": "tests/unit"},
            "integration": {"status": "pass", "proof_ref": "tests/integration"},
        },
    )
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert "tests" in verdict
    assert verdict["tests"]["unit"]["status"] == "pass"
    assert verdict["tests"]["integration"]["status"] == "pass"


def test_verdict_tests_mirror_derived_when_absent(tmp_path):
    # #283: no nested "tests" key -> verdict still carries a derived mirror.
    receipt = _passing_receipt()
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert "tests" in verdict
    assert isinstance(verdict["tests"], dict)


def test_tdd_lane_required_when_policy_opts_in_and_missing(tmp_path):
    receipt = _passing_receipt(policy={"tdd_required": True})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_tdd_missing"


def test_tdd_lane_requires_distinct_red_and_green_refs(tmp_path):
    receipt = _passing_receipt(policy={"tdd_required": True})
    receipt["requirements"]["tdd"] = {
        "status": "pass", "red_proof_ref": "same-ref", "green_proof_ref": "same-ref",
    }
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_tdd_red_green_identical"


def test_tdd_lane_passes_with_distinct_red_and_green_refs(tmp_path):
    receipt = _passing_receipt(policy={"tdd_required": True})
    receipt["requirements"]["tdd"] = {
        "status": "pass",
        "red_proof_ref": "tests/test_x.py::test_feature (failed pre-impl)",
        "green_proof_ref": "tests/test_x.py::test_feature (passed post-impl)",
    }
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True


# --- #283: justified NOT_APPLICABLE (benchmark only) -----------------------------


def test_benchmark_not_applicable_blocked_without_policy_opt_in(tmp_path):
    receipt = _passing_receipt()
    receipt["requirements"]["benchmark"] = {"status": "not_applicable", "justification": "no perf-sensitive path"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_benchmark_not_applicable_unjustified"


def test_benchmark_not_applicable_blocked_without_justification(tmp_path):
    receipt = _passing_receipt(policy={"allow_justified_not_applicable": True})
    receipt["requirements"]["benchmark"] = {"status": "not_applicable"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_benchmark_not_applicable_unjustified"


def test_benchmark_not_applicable_passes_when_policy_and_justification_present(tmp_path):
    receipt = _passing_receipt(policy={"allow_justified_not_applicable": True})
    receipt["requirements"]["benchmark"] = {"status": "not_applicable", "justification": "no perf-sensitive code path touched"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True


def test_coverage_unmeasured_blocks_by_default(tmp_path):
    receipt = _passing_receipt(coverage={"measured": None})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "coverage_unmeasured"


def test_coverage_waived_by_policy_passes_without_a_measurement(tmp_path):
    receipt = _passing_receipt(policy={"coverage_required": False}, coverage={"measured": None})
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True, verdict


def test_not_applicable_ineligible_lane_still_blocks(tmp_path):
    # NA is only ever excusable for "benchmark" (issue text verbatim) -- unit must
    # never be excusable this way even with the policy flag on.
    receipt = _passing_receipt(policy={"allow_justified_not_applicable": True})
    receipt["requirements"]["unit"] = {"status": "not_applicable", "justification": "skipped"}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_unit_not_applicable_unjustified"


# --- #283: change classification -------------------------------------------------


def test_classify_change_type_label_authoritative():
    assert classify_change_type("irrelevant title", ["bug"]) == "bug"
    assert classify_change_type("irrelevant title", ["enhancement"]) == "feat"


def test_classify_change_type_title_fallback():
    assert classify_change_type("fix: null pointer crash on login", []) == "fix"
    assert classify_change_type("feat: add SSO login", []) == "feat"
    assert classify_change_type("chore: refactor the queue module", []) == "chore"


def test_classify_change_type_defaults_to_task_unclassified():
    assert classify_change_type("something ambiguous", []) == "task"


def test_default_policy_strict_for_behavior_changing_types():
    for change_type in ("bug", "fix", "feat", "task"):
        policy = default_policy_for_change_type(change_type)
        assert policy["tdd_required"] is True
        assert policy["allow_justified_not_applicable"] is False


def test_default_policy_relaxed_for_chore():
    policy = default_policy_for_change_type("chore")
    assert policy["tdd_required"] is False
    assert policy["allow_justified_not_applicable"] is True


def test_build_template_with_change_type_seeds_policy_and_tdd_lane():
    template = build_quality_matrix_template(change_type="feat")
    assert template["policy"]["tdd_required"] is True
    assert template["requirements"]["tdd"]["status"] == "unset"

    chore_template = build_quality_matrix_template(change_type="chore")
    assert chore_template["policy"]["tdd_required"] is False
    assert "tdd" not in chore_template["requirements"]


# --- #283: full envelope shape (run_id, work_item, nested "tests") -----------------


def test_template_defaults_run_id_and_work_item_to_empty_never_fabricated():
    template = build_quality_matrix_template()
    assert template["run_id"] == ""
    assert template["work_item"] == {}


def test_template_records_run_id_and_work_item_verbatim():
    work_item = {"source": "github", "id": "283", "type": "feat", "title": "Quality Gate"}
    template = build_quality_matrix_template(run_id="run-abc123", work_item=work_item)
    assert template["run_id"] == "run-abc123"
    assert template["work_item"] == work_item
    # mutating the caller's dict afterwards must not affect the stored template
    work_item["id"] = "mutated"
    assert template["work_item"]["id"] == "283"


def test_template_always_has_tests_mirror_in_sync_with_requirements():
    template = build_quality_matrix_template()
    assert set(template["tests"]) == set(TESTS_ENVELOPE_CATEGORIES)
    for name in TESTS_ENVELOPE_CATEGORIES:
        assert template["tests"][name] == template["requirements"][name]


def test_sync_tests_envelope_recomputes_from_requirements():
    receipt = _passing_receipt()
    del receipt["requirements"]["unit"]  # simulate a stale/incomplete flat dict
    sync_tests_envelope(receipt)
    assert receipt["tests"]["unit"] == {"status": "unset", "proof_ref": "", "detail": ""}
    for name in ("integration", "system", "regression"):
        assert receipt["tests"][name] == receipt["requirements"][name]


def test_evaluate_accepts_nested_tests_shape_for_missing_flat_lane(tmp_path):
    # A lane present ONLY under "tests" (the issue's literal envelope shape) must be
    # accepted exactly as if it were under "requirements" directly.
    receipt = _passing_receipt()
    unit_entry = receipt["requirements"].pop("unit")
    receipt["tests"] = {"unit": unit_entry}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True


def test_evaluate_flat_requirement_wins_over_stale_tests_mirror(tmp_path):
    # A flat requirements.<lane> entry is canonical -- a stale/contradictory "tests"
    # mirror for the same lane must never override it.
    receipt = _passing_receipt()
    receipt["tests"] = {"unit": {"status": "fail", "proof_ref": "stale"}}
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is True  # requirements.unit (pass) wins, not tests.unit (fail)


def test_evaluate_missing_lane_in_both_shapes_still_blocks(tmp_path):
    receipt = _passing_receipt()
    del receipt["requirements"]["integration"]
    receipt["tests"] = {}  # present but doesn't supply the missing lane either
    (tmp_path / "quality-matrix.json").write_text(json.dumps(receipt), encoding="utf-8")
    verdict = evaluate_quality_matrix(str(tmp_path))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_integration_missing"


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_quality_matrix_unit")
