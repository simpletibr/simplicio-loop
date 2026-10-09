"""Squad metrics: escalation rate, dependency wait, measured-only."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, squad_metrics


# Helpers to build task/report dicts
def step(role, outcome="ok", reason=None, family="anthropic", model="claude-opus-5-5", effort="xhigh"):
    """Build a step dict for escalation_part."""
    s = {"role": role, "family": family, "model": model, "effort": effort, "outcome": outcome}
    if reason and outcome == "failed":
        s["reason"] = reason
    return s


def task(task_id=1, issue="repo#1", steps=None, depends_on=None, ready_at=None, merged_at=None):
    """Build a task dict for reports."""
    t = {"task_id": task_id, "issue": issue}
    if steps is not None:
        t["squad_metrics"] = squad_metrics.task_record(steps, depends_on or [], ready_at, merged_at or {})
    return t


def report(schema="simplicio.execution-report/v1", run_id="run1", tasks=None):
    """Build an execution-report dict."""
    return {
        "schema": schema,
        "run_id": run_id,
        "tasks": tasks or [],
    }


# Tests for escalation_part
class TestEscalationPart:
    def test_no_escalation_same_role_ok(self):
        """Single execution step that succeeds -> MEASURED, no escalations."""
        steps = [step("execution", outcome="ok")]
        result = squad_metrics.escalation_part(steps)
        assert result["initial_role"] == "execution"
        assert result["final_role"] == "execution"
        assert result["escalations"] == []
        assert result["proof_kind"]["escalations"] == "measured"
        assert result["unverified"] == {}

    def test_escalation_execution_to_coordination(self):
        """Two steps: execution fails, coordination succeeds -> one escalation at attempt 2."""
        steps = [
            step("execution", outcome="failed", reason="verify_failed"),
            step("coordination", outcome="ok"),
        ]
        result = squad_metrics.escalation_part(steps)
        assert result["initial_role"] == "execution"
        assert result["final_role"] == "coordination"
        assert len(result["escalations"]) == 1
        assert result["escalations"][0] == {
            "from": "execution",
            "to": "coordination",
            "reason": "verify_failed",
            "attempt": 2,
        }
        assert result["proof_kind"]["escalations"] == "measured"

    def test_multiple_escalations(self):
        """Three different roles: execution -> coordination -> planning."""
        steps = [
            step("execution", outcome="failed", reason="timeout"),
            step("coordination", outcome="failed", reason="resource_limit"),
            step("planning", outcome="ok"),
        ]
        result = squad_metrics.escalation_part(steps)
        assert result["initial_role"] == "execution"
        assert result["final_role"] == "planning"
        assert len(result["escalations"]) == 2
        assert result["escalations"][0]["from"] == "execution"
        assert result["escalations"][0]["to"] == "coordination"
        assert result["escalations"][0]["attempt"] == 2
        assert result["escalations"][1]["from"] == "coordination"
        assert result["escalations"][1]["to"] == "planning"
        assert result["escalations"][1]["attempt"] == 3

    def test_same_role_repeated_is_not_escalation(self):
        """Two execution steps (first fails, second succeeds) -> no escalation."""
        steps = [
            step("execution", outcome="failed", reason="retry"),
            step("execution", outcome="ok"),
        ]
        result = squad_metrics.escalation_part(steps)
        assert result["initial_role"] == "execution"
        assert result["final_role"] == "execution"
        assert result["escalations"] == []

    def test_missing_reason_unverified(self):
        """Failed step without reason recorded -> UNVERIFIED|reason_not_recorded."""
        steps = [
            step("execution", outcome="failed"),
            step("coordination", outcome="ok"),
        ]
        result = squad_metrics.escalation_part(steps)
        assert result["initial_role"] == "execution"
        assert result["final_role"] == "coordination"
        assert len(result["escalations"]) == 1
        assert "UNVERIFIED|reason_not_recorded" in result["escalations"][0]["reason"]

    def test_empty_steps_unverified(self):
        """No steps recorded -> UNVERIFIED with None fields."""
        result = squad_metrics.escalation_part([])
        assert result["initial_role"] is None
        assert result["final_role"] is None
        assert result["escalations"] is None
        assert result["proof_kind"]["escalations"] == "UNVERIFIED"
        assert result["unverified"]["escalations"] == "no_steps_recorded"

    def test_none_steps_unverified(self):
        """None steps -> UNVERIFIED."""
        result = squad_metrics.escalation_part(None)
        assert result["initial_role"] is None
        assert result["escalations"] is None
        assert result["proof_kind"]["escalations"] == "UNVERIFIED"


# Tests for dependency_part
class TestDependencyPart:
    def test_no_dependencies(self):
        """No deps, any ready_at/merged_at -> wait 0.0 measured."""
        result = squad_metrics.dependency_part([], 100.0, {})
        assert result["dependency_wait_s"] == 0.0
        assert result["depends_on"] == []
        assert result["proof_kind"]["dependency_wait"] == "measured"
        assert result["unverified"] == {}

    def test_one_dependency_measured(self):
        """One dep merged at 112.5, ready at 100.0 -> wait 12.5."""
        result = squad_metrics.dependency_part([1], 100.0, {1: 112.5})
        assert result["dependency_wait_s"] == 12.5
        assert result["depends_on"] == [1]
        assert result["proof_kind"]["dependency_wait"] == "measured"

    def test_two_dependencies_latest_merge(self):
        """Two deps; use the latest merge time."""
        result = squad_metrics.dependency_part([1, 2], 100.0, {1: 110.0, 2: 120.0})
        assert result["dependency_wait_s"] == 20.0
        assert result["depends_on"] == [1, 2]

    def test_dependency_already_merged_before_ready(self):
        """Dep merged before task ready -> wait 0.0 (floored at 0)."""
        result = squad_metrics.dependency_part([1], 110.0, {1: 100.0})
        assert result["dependency_wait_s"] == 0.0

    def test_ready_at_none_unverified(self):
        """ready_at is None -> UNVERIFIED task_never_ready."""
        result = squad_metrics.dependency_part([1], None, {1: 100.0})
        assert result["dependency_wait_s"] is None
        assert result["proof_kind"]["dependency_wait"] == "UNVERIFIED"
        assert "task_never_ready" in result["unverified"]["dependency_wait_s"]

    def test_missing_dependency_merge_unverified(self):
        """A dependency not in merged_at -> UNVERIFIED with issue numbers."""
        result = squad_metrics.dependency_part([1, 3], 100.0, {1: 110.0})
        assert result["dependency_wait_s"] is None
        assert "dependency_merge_not_observed: #3" in result["unverified"]["dependency_wait_s"]

    def test_missing_multiple_dependencies_unverified(self):
        """Multiple deps missing -> sorted list in reason."""
        result = squad_metrics.dependency_part([1, 3, 2], 100.0, {})
        assert result["dependency_wait_s"] is None
        assert "dependency_merge_not_observed: #1,#2,#3" in result["unverified"]["dependency_wait_s"]

    def test_depends_on_sorted(self):
        """depends_on list is returned sorted."""
        result = squad_metrics.dependency_part([3, 1, 2], 100.0, {1: 105.0, 2: 106.0, 3: 107.0})
        assert result["depends_on"] == [1, 2, 3]


# Tests for task_record
class TestTaskRecord:
    def test_merges_escalation_and_dependency_parts(self):
        """task_record combines escalation and dependency parts."""
        steps = [step("execution", outcome="ok")]
        result = squad_metrics.task_record(steps, [1], 100.0, {1: 110.0})
        assert result["initial_role"] == "execution"
        assert result["dependency_wait_s"] == 10.0
        assert result["depends_on"] == [1]
        assert result["proof_kind"]["escalations"] == "measured"
        assert result["proof_kind"]["dependency_wait"] == "measured"

    def test_both_parts_unverified_merge(self):
        """Both parts UNVERIFIED -> merged unverified dict."""
        result = squad_metrics.task_record([], [1], None, {})
        assert result["initial_role"] is None
        assert result["dependency_wait_s"] is None
        assert "escalations" in result["unverified"]
        assert "dependency_wait_s" in result["unverified"]


# Tests for collect
class TestCollect:
    def test_collect_tasks_with_squad_metrics(self):
        """Collect returns one dict per task with squad_metrics."""
        t1 = task(1, "repo#1", steps=[step("execution", "ok")])
        t2 = task(2, "repo#2", steps=[step("execution", "ok")])
        reports = [report(tasks=[t1, t2])]
        result = squad_metrics.collect(reports)
        assert len(result) == 2
        assert result[0]["issue"] == "repo#1"
        assert result[1]["issue"] == "repo#2"

    def test_collect_ignores_tasks_without_squad_metrics(self):
        """Tasks without squad_metrics key are ignored."""
        t1 = {"task_id": 1, "issue": "repo#1"}
        t2 = task(2, "repo#2", steps=[step("execution", "ok")])
        reports = [report(tasks=[t1, t2])]
        result = squad_metrics.collect(reports)
        assert len(result) == 1
        assert result[0]["task_id"] == 2


# Tests for percentile
class TestPercentile:
    def test_percentile_nearest_rank_p50(self):
        """[1,2,3,4] p50 -> rank ceil(50/100*4)=2 -> value 2."""
        result = squad_metrics.percentile([1, 2, 3, 4], 50)
        assert result == 2

    def test_percentile_nearest_rank_p95(self):
        """[1,2,3,4] p95 -> rank ceil(95/100*4)=4 -> value 4."""
        result = squad_metrics.percentile([1, 2, 3, 4], 95)
        assert result == 4

    def test_percentile_single_value(self):
        """Single value [5] at any percentile -> 5."""
        assert squad_metrics.percentile([5], 50) == 5
        assert squad_metrics.percentile([5], 95) == 5

    def test_percentile_empty_list(self):
        """Empty list -> None."""
        assert squad_metrics.percentile([], 50) is None


# Tests for summarize_records and summarize
class TestSummarizeRecords:
    def test_summarize_empty_records(self):
        """Empty records -> safe defaults with counts 0."""
        result = squad_metrics.summarize_records([])
        assert result["schema"] == "simplicio.squad-metrics/v1"
        assert result["reports"] is None
        assert result["tasks"] == 0
        assert result["issues"] == []
        assert result["escalation_n"] == 0
        assert result["escalation_unverified"] == 0
        assert result["escalation_rate"] is None

    def test_summarize_one_measured_no_escalation(self):
        """One record, measured, execution, no escalation."""
        record = {
            "initial_role": "execution",
            "final_role": "execution",
            "escalations": [],
            "depends_on": [],
            "dependency_wait_s": 0.0,
            "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
            "unverified": {},
            "issue": "repo#1",
        }
        result = squad_metrics.summarize_records([record])
        assert result["escalation_n"] == 1
        assert result["escalated"] == 0
        assert result["escalation_rate"] == 0.0

    def test_summarize_three_escalated_one_not(self):
        """Four records: 3 measured/escalated, 1 measured/not escalated."""
        records = []
        for i in range(3):
            records.append({
                "initial_role": "execution",
                "final_role": "coordination",
                "escalations": [{"from": "execution", "to": "coordination", "reason": "failed", "attempt": 2}],
                "depends_on": [],
                "dependency_wait_s": 0.0,
                "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
                "unverified": {},
                "issue": f"repo#{i+1}",
            })
        records.append({
            "initial_role": "execution",
            "final_role": "execution",
            "escalations": [],
            "depends_on": [],
            "dependency_wait_s": 0.0,
            "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
            "unverified": {},
            "issue": "repo#4",
        })
        result = squad_metrics.summarize_records(records)
        assert result["escalation_n"] == 4
        assert result["escalated"] == 3
        assert result["escalation_rate"] == 0.75

    def test_rates_are_rounded_to_four_places_overall_and_by_initial_role(self):
        """1 of 3 escalated -> 0.3333, never a longer float that looks more precise than three tasks can be."""
        def record(n, steps):
            return squad_metrics.task_record(steps, [], None, {}) | {"issue": f"repo#{n}"}
        records = [record(1, [step("execution", "failed", "verify_failed"), step("coordination")]),
                   record(2, [step("execution")]), record(3, [step("execution")])]
        result = squad_metrics.summarize_records(records)
        assert result["escalation_rate"] == 0.3333
        assert result["by_initial_role"]["execution"] == {"n": 3, "escalated": 1, "escalation_rate": 0.3333}

    def test_hand_edited_or_odd_records_are_unverified_not_a_crash(self):
        """Reports come from disk: a record that is not shaped as the numbers need is UNVERIFIED and in no denominator."""
        good = squad_metrics.task_record([step("execution")], [1], 1.0, {1: 3.0}) | {"issue": "repo#1"}
        odd = [good | {"dependency_wait_s": "5"}, good | {"proof_kind": "measured"}, good | {"escalations": [{"x": 1}]},
               good | {"escalations": ["a"]}, good | {"issue": ["x"]}, good | {"dependency_wait_s": True}, "oops", None]
        result = squad_metrics.summarize_records([good, *odd])
        assert result["tasks"] == 7  # the two non-objects are dropped, the six odd objects are counted
        assert result["escalation_n"] + result["escalation_unverified"] == result["tasks"]
        assert result["dependency_wait_n"] + result["no_dependency_tasks"] + result["dependency_wait_unverified"] == result["tasks"]
        # escalation measured: good, str-wait, bad-issue, bool-wait; wait measured: good, the two bad escalations, bad-issue
        assert (result["escalation_n"], result["dependency_wait_n"]) == (4, 4) and result["issues"] == ["repo#1"]
        assert result["dependency_wait_p50_s"] == 2.0

    def test_collect_ignores_a_squad_metrics_that_is_not_an_object(self):
        reports = [{"tasks": [{"squad_metrics": "x"}, "y", {"squad_metrics": {"initial_role": "execution"}}]}, "z", {"tasks": "q"}]
        assert len(squad_metrics.collect(reports)) == 1

    def test_summarize_unverified_excluded_from_denominators(self):
        """Two records: 1 measured, 1 UNVERIFIED -> only measured counts."""
        measured = {
            "initial_role": "execution",
            "final_role": "execution",
            "escalations": [],
            "depends_on": [],
            "dependency_wait_s": 0.0,
            "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
            "unverified": {},
            "issue": "repo#1",
        }
        unverified = {
            "initial_role": None,
            "final_role": None,
            "escalations": None,
            "depends_on": [],
            "dependency_wait_s": None,
            "proof_kind": {"escalations": "UNVERIFIED", "dependency_wait": "UNVERIFIED"},
            "unverified": {"escalations": "no_steps", "dependency_wait_s": "ready_at_none"},
            "issue": "repo#2",
        }
        result = squad_metrics.summarize_records([measured, unverified])
        assert result["escalation_n"] == 1
        assert result["escalation_unverified"] == 1
        assert result["dependency_wait_unverified"] == 1

    def test_summarize_dependency_wait_percentiles(self):
        """10 records with dependency_wait_s = 1..10 -> p50=5, p95=10, max=10."""
        records = []
        for i in range(10):
            records.append({
                "initial_role": "execution",
                "final_role": "execution",
                "escalations": [],
                "depends_on": [1],
                "dependency_wait_s": float(i + 1),
                "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
                "unverified": {},
                "issue": f"repo#{i+1}",
            })
        result = squad_metrics.summarize_records(records)
        assert result["dependency_wait_n"] == 10
        assert result["dependency_wait_p50_s"] == 5.0
        assert result["dependency_wait_p95_s"] == 10.0
        assert result["dependency_wait_max_s"] == 10.0

    def test_summarize_escalations_by_transition(self):
        """Count escalations by transition."""
        records = [
            {
                "initial_role": "execution",
                "final_role": "coordination",
                "escalations": [{"from": "execution", "to": "coordination", "reason": "fail", "attempt": 2}],
                "depends_on": [],
                "dependency_wait_s": 0.0,
                "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
                "unverified": {},
                "issue": "repo#1",
            },
            {
                "initial_role": "coordination",
                "final_role": "planning",
                "escalations": [{"from": "coordination", "to": "planning", "reason": "fail", "attempt": 2}],
                "depends_on": [],
                "dependency_wait_s": 0.0,
                "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
                "unverified": {},
                "issue": "repo#2",
            },
            {
                "initial_role": "execution",
                "final_role": "coordination",
                "escalations": [{"from": "execution", "to": "coordination", "reason": "fail", "attempt": 2}],
                "depends_on": [],
                "dependency_wait_s": 0.0,
                "proof_kind": {"escalations": "measured", "dependency_wait": "measured"},
                "unverified": {},
                "issue": "repo#3",
            },
        ]
        result = squad_metrics.summarize_records(records)
        assert result["escalations_by_transition"]["coordination->planning"] == 1
        assert result["escalations_by_transition"]["execution->coordination"] == 2


# Tests for load_reports
class TestLoadReports:
    def test_load_reports_single_file(self):
        """Load a single valid report file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.json"
            r = report(tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            path.write_text(json.dumps(r))
            reports, skipped = squad_metrics.load_reports([str(path)])
            assert len(reports) == 1
            assert len(skipped) == 0

    def test_load_reports_directory(self):
        """Load all *.json files from a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            r1 = report(run_id="run1", tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            r2 = report(run_id="run2", tasks=[task(2, "repo#2", steps=[step("execution", "ok")])])
            (tmpdir_path / "report1.json").write_text(json.dumps(r1))
            (tmpdir_path / "report2.json").write_text(json.dumps(r2))
            reports, skipped = squad_metrics.load_reports([str(tmpdir_path)])
            assert len(reports) == 2
            assert len(skipped) == 0

    def test_load_reports_skips_latest_json(self):
        """latest.json is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            r = report(run_id="run1", tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            (tmpdir_path / "report.json").write_text(json.dumps(r))
            (tmpdir_path / "latest.json").write_text(json.dumps(r))
            reports, skipped = squad_metrics.load_reports([str(tmpdir_path)])
            assert len(reports) == 1
            assert len(skipped) == 0

    def test_load_reports_deduplicates_by_run_id(self):
        """Same run_id twice -> counted once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            r = report(run_id="run1", tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            (tmpdir_path / "report1.json").write_text(json.dumps(r))
            (tmpdir_path / "report2.json").write_text(json.dumps(r))
            reports, skipped = squad_metrics.load_reports([str(tmpdir_path)])
            assert len(reports) == 1

    def test_load_reports_skips_invalid_json(self):
        """Invalid JSON -> skipped with reason."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "bad.json").write_text("not json")
            reports, skipped = squad_metrics.load_reports([str(tmpdir_path)])
            assert len(reports) == 0
            assert len(skipped) == 1
            assert "bad.json" in skipped[0]["path"]
            assert "reason" in skipped[0]

    def test_load_reports_skips_json_that_is_not_an_object(self):
        """A JSON list (or any non-object) is skipped with a reason, never a crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "list.json").write_text("[1, 2]")
            reports, skipped = squad_metrics.load_reports([tmpdir])
            assert reports == [] and len(skipped) == 1 and "list" in skipped[0]["reason"]

    def test_load_reports_skips_wrong_schema(self):
        """Valid JSON but wrong schema -> skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            (tmpdir_path / "report.json").write_text(json.dumps({"schema": "other"}))
            reports, skipped = squad_metrics.load_reports([str(tmpdir_path)])
            assert len(reports) == 0
            assert len(skipped) == 1


# Tests for compare
class TestCompare:
    def test_compare_escalation_rate(self):
        """Compare escalation_rate between two summaries."""
        summary1 = {
            "schema": "simplicio.squad-metrics/v1",
            "reports": 1,
            "tasks": 10,
            "issues": ["repo#1"],
            "escalation_n": 10,
            "escalated": 5,
            "escalation_rate": 0.5,
            "escalations_by_transition": {},
            "by_initial_role": {},
            "dependency_wait_n": 0,
            "no_dependency_tasks": 0,
            "dependency_wait_unverified": 0,
            "dependency_wait_p50_s": None,
            "dependency_wait_p95_s": None,
            "dependency_wait_max_s": None,
            "escalation_unverified": 0,
        }
        summary2 = {**summary1, "escalation_n": 10, "escalated": 3, "escalation_rate": 0.3}
        result = squad_metrics.compare(summary1, summary2)
        assert result["schema"] == "simplicio.squad-metrics-compare/v1"
        rows = result["rows"]
        rate_row = next((r for r in rows if r["metric"] == "escalation_rate"), None)
        assert rate_row is not None
        assert rate_row["before"]["value"] == 0.5
        assert rate_row["after"]["value"] == 0.3
        assert rate_row["before"]["n"] == 10
        assert rate_row["after"]["n"] == 10

    def test_compare_warns_on_small_n(self):
        """n<10 on either side -> warning."""
        summary_before = {
            "schema": "simplicio.squad-metrics/v1",
            "tasks": 5,
            "escalation_n": 5,
            "escalated": 2,
            "escalation_rate": 0.4,
            "dependency_wait_n": 5,
            "dependency_wait_p50_s": 10.0,
            "dependency_wait_p95_s": 20.0,
            "dependency_wait_max_s": 25.0,
            "escalation_unverified": 0,
            "dependency_wait_unverified": 0,
            "issues": [],
        }
        summary_after = {**summary_before, "escalation_n": 15, "dependency_wait_n": 15}
        result = squad_metrics.compare(summary_before, summary_after)
        warnings = result["warnings"]
        assert any("before" in w and "escalation rate" in w for w in warnings)
        assert any("before" in w and "dependency wait" in w for w in warnings)

    def test_compare_warns_on_issue_set_diff(self):
        """Different issue sets -> warning."""
        summary_before = {
            "schema": "simplicio.squad-metrics/v1",
            "tasks": 10,
            "issues": ["repo#1", "repo#2"],
            "escalation_n": 10,
            "escalated": 5,
            "escalation_rate": 0.5,
            "dependency_wait_n": 10,
            "dependency_wait_p50_s": 10.0,
            "dependency_wait_p95_s": 20.0,
            "dependency_wait_max_s": 25.0,
            "escalation_unverified": 0,
            "dependency_wait_unverified": 0,
        }
        summary_after = {
            **summary_before,
            "issues": ["repo#1", "repo#3"],
        }
        result = squad_metrics.compare(summary_before, summary_after)
        warnings = result["warnings"]
        assert any("task sets differ" in w for w in warnings)

    def test_compare_warns_on_unverified(self):
        """Unverified tasks on either side -> warning."""
        summary_before = {
            "schema": "simplicio.squad-metrics/v1",
            "tasks": 10,
            "issues": [],
            "escalation_n": 8,
            "escalated": 2,
            "escalation_rate": 0.25,
            "escalation_unverified": 2,
            "dependency_wait_n": 8,
            "dependency_wait_unverified": 0,
            "dependency_wait_p50_s": 10.0,
            "dependency_wait_p95_s": 20.0,
            "dependency_wait_max_s": 25.0,
        }
        summary_after = {**summary_before}
        result = squad_metrics.compare(summary_before, summary_after)
        warnings = result["warnings"]
        assert any("UNVERIFIED" in w for w in warnings)

    def test_compare_no_warnings_when_all_good(self):
        """n>=10 both sides, same issues, nothing UNVERIFIED -> no warnings."""
        summary = {
            "schema": "simplicio.squad-metrics/v1",
            "tasks": 20,
            "issues": ["repo#1"],
            "escalation_n": 20,
            "escalated": 10,
            "escalation_rate": 0.5,
            "escalation_unverified": 0,
            "dependency_wait_n": 20,
            "dependency_wait_unverified": 0,
            "dependency_wait_p50_s": 10.0,
            "dependency_wait_p95_s": 20.0,
            "dependency_wait_max_s": 25.0,
        }
        result = squad_metrics.compare(summary, summary)
        assert result["warnings"] == []


# Tests for render_summary and render_compare
class TestRender:
    def test_render_summary_text(self):
        """Render summary as plain text table."""
        summary = {
            "schema": "simplicio.squad-metrics/v1",
            "reports": 1,
            "tasks": 10,
            "issues": ["repo#1"],
            "escalation_n": 10,
            "escalated": 5,
            "escalation_rate": 0.5,
            "escalations_by_transition": {"execution->coordination": 3},
            "by_initial_role": {"execution": {"n": 8, "escalated": 4, "escalation_rate": 0.5}},
            "dependency_wait_n": 10,
            "no_dependency_tasks": 0,
            "dependency_wait_unverified": 0,
            "dependency_wait_p50_s": 5.0,
            "dependency_wait_p95_s": 15.0,
            "dependency_wait_max_s": 20.0,
            "escalation_unverified": 0,
        }
        text = squad_metrics.render_summary(summary)
        assert "escalation" in text.lower() or "rate" in text.lower()
        assert len(text) > 0

    def test_render_compare_text(self):
        """Render compare as plain text table."""
        result = {
            "schema": "simplicio.squad-metrics-compare/v1",
            "rows": [
                {"metric": "escalation_rate", "before": {"value": 0.5, "n": 10}, "after": {"value": 0.3, "n": 10}},
                {"metric": "dependency_wait_p50_s", "before": {"value": 10.0, "n": 10}, "after": {"value": 8.0, "n": 10}},
            ],
            "warnings": [],
        }
        text = squad_metrics.render_compare(result)
        assert len(text) > 0


# Tests for load_summary
class TestLoadSummary:
    def test_load_summary_from_summary_file(self):
        """Load a squad-metrics/v1 summary file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.json"
            summary = {
                "schema": "simplicio.squad-metrics/v1",
                "reports": 1,
                "tasks": 10,
                "issues": [],
                "escalation_n": 10,
                "escalation_unverified": 0,
                "escalated": 5,
                "escalation_rate": 0.5,
                "escalations_by_transition": {},
                "by_initial_role": {},
                "dependency_wait_n": 0,
                "no_dependency_tasks": 0,
                "dependency_wait_unverified": 0,
                "dependency_wait_p50_s": None,
                "dependency_wait_p95_s": None,
                "dependency_wait_max_s": None,
            }
            path.write_text(json.dumps(summary))
            result = squad_metrics.load_summary(str(path))
            assert result["schema"] == "simplicio.squad-metrics/v1"

    def test_load_summary_from_report_file(self):
        """Load an execution-report file, summarize it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.json"
            r = report(tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            path.write_text(json.dumps(r))
            result = squad_metrics.load_summary(str(path))
            assert result["schema"] == "simplicio.squad-metrics/v1"
            assert result["tasks"] == 1

    def test_load_summary_of_a_json_list_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "list.json"
            path.write_text("[]")
            with pytest.raises(ValueError):
                squad_metrics.load_summary(str(path))

    def test_compare_of_a_hand_edited_summary_is_blocked_not_a_traceback(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "odd.json"
            path.write_text(json.dumps({"schema": "simplicio.squad-metrics/v1", "escalation_n": "x", "issues": 3}))
            assert cli_impl.main(["squads", "metrics", "--compare", str(path), str(path), "--json"]) == 2
        assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"

    def test_load_summary_wrong_schema_raises(self):
        """Wrong schema -> ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "wrong.json"
            path.write_text(json.dumps({"schema": "other"}))
            with pytest.raises(ValueError):
                squad_metrics.load_summary(str(path))


# Tests for dispatch (CLI)
class TestDispatch:
    def test_dispatch_reports_json(self, capsys):
        """dispatch with --reports, --json -> JSON summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            r = report(tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            (tmpdir_path / "report.json").write_text(json.dumps(r))
            
            class Args:
                reports = [str(tmpdir_path)]
                compare = None
                json = True
            
            code = squad_metrics.dispatch(Args())
            assert code == 0
            out = capsys.readouterr().out
            result = json.loads(out)
            assert result["schema"] == "simplicio.squad-metrics/v1"

    def test_dispatch_reports_text(self, capsys):
        """dispatch with --reports, no --json -> text output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            r = report(tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])
            (tmpdir_path / "report.json").write_text(json.dumps(r))
            
            class Args:
                reports = [str(tmpdir_path)]
                compare = None
                json = False
            
            code = squad_metrics.dispatch(Args())
            assert code == 0
            out = capsys.readouterr().out
            assert "simplicio.squad-metrics" not in out
            assert len(out) > 0

    def test_dispatch_compare_json(self, capsys):
        """dispatch with --compare, --json -> compare result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            summary = {
                "schema": "simplicio.squad-metrics/v1",
                "reports": 1,
                "tasks": 10,
                "issues": [],
                "escalation_n": 10,
                "escalation_unverified": 0,
                "escalated": 5,
                "escalation_rate": 0.5,
                "escalations_by_transition": {},
                "by_initial_role": {},
                "dependency_wait_n": 0,
                "no_dependency_tasks": 0,
                "dependency_wait_unverified": 0,
                "dependency_wait_p50_s": None,
                "dependency_wait_p95_s": None,
                "dependency_wait_max_s": None,
            }
            before_path = tmpdir_path / "before.json"
            after_path = tmpdir_path / "after.json"
            before_path.write_text(json.dumps(summary))
            after_path.write_text(json.dumps(summary))
            
            class Args:
                reports = None
                compare = [str(before_path), str(after_path)]
                json = True
            
            code = squad_metrics.dispatch(Args())
            assert code == 0
            out = capsys.readouterr().out
            result = json.loads(out)
            assert result["schema"] == "simplicio.squad-metrics-compare/v1"

    def test_dispatch_no_reports_given_blocked(self, capsys):
        """Neither --reports nor --compare -> BLOCKED."""
        class Args:
            reports = None
            compare = None
            json = True
        
        code = squad_metrics.dispatch(Args())
        assert code == 2
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["status"] == "BLOCKED"

    def test_dispatch_both_reports_and_compare_blocked(self, capsys):
        """Both --reports and --compare set -> BLOCKED."""
        class Args:
            reports = ["/tmp/report.json"]
            compare = ["/tmp/before.json", "/tmp/after.json"]
            json = True
        
        code = squad_metrics.dispatch(Args())
        assert code == 2
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["status"] == "BLOCKED"

    def test_dispatch_no_reports_found_blocked(self, capsys):
        """--reports given but no valid reports found -> BLOCKED."""
        class Args:
            reports = ["/nonexistent/path"]
            compare = None
            json = True
        
        code = squad_metrics.dispatch(Args())
        assert code == 2
        out = capsys.readouterr().out
        result = json.loads(out)
        assert result["status"] == "BLOCKED"
        assert "no execution-report/v1 found" in result["reason"]


# CLI integration tests
def _run_cli(capsys, *argv):
    """Run cli_impl.main and return (code, output)."""
    code = cli_impl.main(list(argv))
    out = capsys.readouterr().out
    return code, out


def test_squads_metrics_cli_integration(capsys):
    """Full CLI round trip: load reports, save summary, compare."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        r1 = report(run_id="run1", tasks=[
            task(1, "repo#1", steps=[step("execution", "ok"), step("execution", "ok")])
        ])
        r2 = report(run_id="run2", tasks=[
            task(2, "repo#2", steps=[step("execution", "failed", "timeout"), step("coordination", "ok")])
        ])
        (tmpdir_path / "report1.json").write_text(json.dumps(r1))
        (tmpdir_path / "report2.json").write_text(json.dumps(r2))
        
        code, out = _run_cli(capsys, "squads", "metrics", "--reports", str(tmpdir_path), "--json")
        assert code == 0
        summary = json.loads(out)
        assert summary["schema"] == "simplicio.squad-metrics/v1"
        assert summary["tasks"] == 2


# --- hostile input (reviewer pass): nothing raises, nothing unbounded is read, nothing odd counts as measured ---


def _good_report(run_id="ok"):
    return report(run_id=run_id, tasks=[task(1, "repo#1", steps=[step("execution", "ok")])])


def _skipped_reason(skipped, name):
    (row,) = [s for s in skipped if s["path"].endswith(name)]
    return row["reason"]


class TestHostileFiles:
    def test_a_symlink_found_in_a_directory_is_not_followed(self, tmp_path):
        """/dev/zero would be an unbounded read; a link to a good file outside the directory is still not followed."""
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(_good_report("outside")))
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "ok.json").write_text(json.dumps(_good_report("ok")))
        (scan / "zero.json").symlink_to("/dev/zero")
        (scan / "out.json").symlink_to(outside)
        reports, skipped = squad_metrics.load_reports([str(scan)])
        assert [r["run_id"] for r in reports] == ["ok"]
        assert {Path(s["path"]).name for s in skipped} == {"zero.json", "out.json"}
        assert "symlink" in _skipped_reason(skipped, "zero.json")

    def test_a_fifo_named_json_is_skipped_and_never_opened(self, tmp_path):
        os.mkfifo(tmp_path / "pipe.json")  # open() on it would block forever
        (tmp_path / "ok.json").write_text(json.dumps(_good_report()))
        reports, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert len(reports) == 1 and "regular file" in _skipped_reason(skipped, "pipe.json")

    def test_a_device_named_as_a_report_is_skipped(self):
        reports, skipped = squad_metrics.load_reports(["/dev/zero"])
        assert reports == [] and len(skipped) == 1

    def test_a_file_over_the_size_cap_is_skipped_without_being_parsed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(squad_metrics, "MAX_FILE_BYTES", 200)
        (tmp_path / "big.json").write_text(json.dumps(_good_report()) + " " * 300)
        (tmp_path / "ok.json").write_text(json.dumps(report(run_id="s")))
        reports, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert [r["run_id"] for r in reports] == ["s"] and "larger than 200 bytes" in _skipped_reason(skipped, "big.json")

    def test_deeply_nested_json_is_skipped_not_a_recursion_error(self, tmp_path):
        (tmp_path / "deep.json").write_text("[" * 200000 + "]" * 200000)
        (tmp_path / "ok.json").write_text(json.dumps(_good_report()))
        reports, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert len(reports) == 1 and "deep.json" in skipped[0]["path"]

    def test_one_bad_file_never_aborts_the_others(self, tmp_path):
        bad = {
            "list_run_id.json": {"schema": "simplicio.execution-report/v1", "run_id": ["a"], "tasks": []},
            "int_run_id.json": {"schema": "simplicio.execution-report/v1", "run_id": 5, "tasks": []},
            "dict_schema.json": {"schema": {"a": 1}},
        }
        for name, body in bad.items():
            (tmp_path / name).write_text(json.dumps(body))
        (tmp_path / "bigint.json").write_text('{"schema":"simplicio.execution-report/v1","run_id":"b","x":' + "9" * 5000 + "}")
        (tmp_path / "ok.json").write_text(json.dumps(_good_report()))
        reports, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert [r["run_id"] for r in reports] == ["ok"]
        assert {Path(s["path"]).name for s in skipped} == set(bad) | {"bigint.json"}

    def test_a_report_without_run_id_still_counts_and_sorts_with_the_others(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps({"schema": "simplicio.execution-report/v1", "tasks": []}))
        (tmp_path / "b.json").write_text(json.dumps({"schema": "simplicio.execution-report/v1", "run_id": None, "tasks": []}))
        (tmp_path / "c.json").write_text(json.dumps(_good_report("z")))
        reports, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert len(reports) == 3 and skipped == []

    def test_the_skipped_reason_is_short_even_for_a_huge_schema_string(self, tmp_path):
        (tmp_path / "s.json").write_text(json.dumps({"schema": "x" * 100000}))
        _, skipped = squad_metrics.load_reports([str(tmp_path)])
        assert len(skipped[0]["reason"]) < 200

    def test_a_path_that_does_not_exist_is_reported_as_skipped(self, tmp_path):
        reports, skipped = squad_metrics.load_reports([str(tmp_path / "nope")])
        assert reports == [] and "nope" in skipped[0]["path"] and "not a file or directory" in skipped[0]["reason"]

    def test_blocked_output_says_why_each_file_was_skipped(self, tmp_path, capsys):
        (tmp_path / "bad.json").write_text("not json")
        assert cli_impl.main(["squads", "metrics", "--reports", str(tmp_path), "--json"]) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "BLOCKED" and "bad.json" in out["skipped"][0]["path"]


class TestOddNumbersAreNeverMeasured:
    @pytest.mark.parametrize("wait", [float("nan"), float("inf"), float("-inf"), -5, -0.001, True, False, "3", None, [1], 10 ** 12])
    def test_a_wait_that_is_not_a_plausible_duration_is_unverified_and_in_no_sample(self, wait):
        good = squad_metrics.task_record([step("execution")], [1], 1.0, {1: 4.0})
        odd = {**good, "dependency_wait_s": wait}
        summary = squad_metrics.summarize_records([good, odd])
        assert summary["dependency_wait_n"] == 1 and summary["dependency_wait_unverified"] == 1
        assert summary["dependency_wait_p50_s"] == summary["dependency_wait_p95_s"] == summary["dependency_wait_max_s"] == 3.0

    def test_a_report_with_nan_and_infinity_waits_prints_strict_json(self, tmp_path, capsys):
        rows = [{"issue": f"r#{i}", "squad_metrics": {
            "initial_role": "execution", "final_role": "execution", "escalations": [], "depends_on": [1],
            "dependency_wait_s": value, "proof_kind": {"escalations": "measured", "dependency_wait": "measured"}}}
            for i, value in enumerate([float("nan"), float("inf"), -5])]
        (tmp_path / "r.json").write_text(json.dumps({"schema": "simplicio.execution-report/v1", "run_id": "n", "tasks": rows}))
        assert cli_impl.main(["squads", "metrics", "--reports", str(tmp_path), "--json"]) == 0

        def refuse(constant):
            raise AssertionError(f"not strict JSON: {constant}")
        summary = json.loads(capsys.readouterr().out, parse_constant=refuse)
        assert summary["dependency_wait_n"] == 0 and summary["dependency_wait_p50_s"] is None


class TestHostileSummaries:
    def _summary(self, **override):
        base = {"schema": "simplicio.squad-metrics/v1", "escalation_n": 12, "dependency_wait_n": 12, "escalation_rate": 0.25,
                "dependency_wait_p50_s": 1.5, "dependency_wait_p95_s": 3.0, "dependency_wait_max_s": 4.0, "issues": ["a#1"],
                "escalation_unverified": 0, "dependency_wait_unverified": 0}
        return {**base, **override}

    @pytest.mark.parametrize("field,value", [
        ("escalation_rate", "abc"), ("escalation_rate", 7), ("escalation_rate", float("nan")), ("escalation_rate", True),
        ("dependency_wait_p50_s", 10 ** 400), ("dependency_wait_p50_s", [1]), ("dependency_wait_p50_s", {"a": 1}),
        ("dependency_wait_p95_s", float("inf")), ("dependency_wait_max_s", -1),
        ("escalation_n", "many"), ("escalation_n", None), ("escalation_n", True), ("escalation_n", -1), ("dependency_wait_n", [1]),
        ("escalation_unverified", "x"), ("dependency_wait_unverified", [1]), ("escalation_n", 10 ** 400),
        ("issues", 5), ("issues", [["a"]]), ("issues", [{"a": 1}]), ("issues", "abc"),
    ])
    def test_a_hand_edited_field_is_blocked_in_json_and_in_text_mode(self, tmp_path, capsys, field, value):
        good, odd = tmp_path / "good.json", tmp_path / "odd.json"
        good.write_text(json.dumps(self._summary()))
        odd.write_text(json.dumps(self._summary(**{field: value})))  # json.dumps writes NaN/Infinity, which json.loads reads back
        for extra in (["--json"], []):
            assert cli_impl.main(["squads", "metrics", "--compare", str(good), str(odd), *extra]) == 2
            assert "BLOCKED" in capsys.readouterr().out

    def test_a_summary_with_none_and_plain_numbers_still_compares(self, tmp_path, capsys):
        good = tmp_path / "good.json"
        good.write_text(json.dumps(self._summary(dependency_wait_p50_s=None, escalation_rate=None, escalation_n=0)))
        assert cli_impl.main(["squads", "metrics", "--compare", str(good), str(good)]) == 0

    def test_deep_json_and_a_device_as_compare_input_are_blocked(self, tmp_path, capsys):
        good, deep = tmp_path / "good.json", tmp_path / "deep.json"
        good.write_text(json.dumps(self._summary()))
        deep.write_text("[" * 200000 + "]" * 200000)
        for odd in (deep, Path("/dev/zero"), tmp_path):
            assert cli_impl.main(["squads", "metrics", "--compare", str(good), str(odd), "--json"]) == 2
            assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
