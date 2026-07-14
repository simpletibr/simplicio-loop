"""Additional unit coverage for simplicio/commands/claims.py.

This module was previously only ~51% covered. These tests exercise
each of the 8 rule-check functions (pass and fail branches),
suggest_tag's three outcomes, generate_report's file-backed and
in-memory paths, and the CLI dispatch surface (main/cmd_check/cmd_tag/
cmd_report/run).
"""

from __future__ import annotations

import argparse
import json

import pytest

from simplicio.commands import claims


# ---------------------------------------------------------------------------
# Rule 1 — ground impact before severity
# ---------------------------------------------------------------------------


def test_rule1_severity_without_grounding_fails():
    r = claims._rule_1_ground("this is a critical bug")
    assert r["pass"] is False
    assert "severity" in r["issues"][0]


def test_rule1_severity_with_grounding_passes():
    r = claims._rule_1_ground("this is a critical bug that causes downtime")
    assert r["pass"] is True


def test_rule1_no_severity_word_passes():
    r = claims._rule_1_ground("this is a normal statement")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 2 — no flat tuples
# ---------------------------------------------------------------------------


def test_rule2_flat_comparison_without_dimensions_fails():
    r = claims._rule_2_tuples("the new version is faster")
    assert r["pass"] is False


def test_rule2_flat_comparison_with_dimensions_passes():
    r = claims._rule_2_tuples("the new version is faster on p99 latency")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 3 — mirrors are not authority
# ---------------------------------------------------------------------------


def test_rule3_mirror_without_fabric_anchor_fails():
    r = claims._rule_3_mirrors("i believe the fix works")
    assert r["pass"] is False


def test_rule3_mirror_with_fabric_anchor_passes():
    r = claims._rule_3_mirrors("i believe the fix works, and the ci log confirms it")
    assert r["pass"] is True


def test_rule3_no_mirror_signal_passes():
    r = claims._rule_3_mirrors("plain statement with no mirror words")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 4 — cylinders not levels
# ---------------------------------------------------------------------------


def test_rule4_level_without_count_or_cylinder_fails():
    r = claims._rule_4_cylinders("scaled up another layer")
    assert r["pass"] is False


def test_rule4_level_with_count_passes():
    r = claims._rule_4_cylinders("added three more layers")
    assert r["pass"] is True


def test_rule4_level_with_cylinder_word_passes():
    r = claims._rule_4_cylinders("added a layer running as a new pod")
    assert r["pass"] is True


def test_rule4_no_level_word_passes():
    r = claims._rule_4_cylinders("nothing relevant here")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 5 — owning gate not transcript
# ---------------------------------------------------------------------------


def test_rule5_gate_claim_backed_by_pasted_log_fails():
    r = claims._rule_5_gate("tests passed, here's the log")
    assert r["pass"] is False


def test_rule5_gate_claim_with_ci_reference_passes():
    r = claims._rule_5_gate("tests passed, here's the log from the github actions run")
    assert r["pass"] is True


def test_rule5_gate_claim_without_paste_or_ci_fails():
    r = claims._rule_5_gate("the tests passed")
    assert r["pass"] is False


def test_rule5_gate_claim_with_ci_only_passes():
    r = claims._rule_5_gate("the ci pipeline passed")
    assert r["pass"] is True


def test_rule5_no_gate_claim_passes():
    r = claims._rule_5_gate("just a regular statement")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 6 — missing not clean-zero
# ---------------------------------------------------------------------------


def test_rule6_missing_reported_as_clean_fails():
    r = claims._rule_6_missing("the log was not found but everything is clean")
    assert r["pass"] is False


def test_rule6_missing_with_explicit_flag_passes():
    r = claims._rule_6_missing("the log was not found; missing=1")
    assert r["pass"] is True


def test_rule6_no_conflict_passes():
    r = claims._rule_6_missing("all good, no issues detected")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 7 — real lane not windows
# ---------------------------------------------------------------------------


def test_rule7_windows_without_production_reference_fails():
    r = claims._rule_7_lane("ran the benchmark on windows")
    assert r["pass"] is False


def test_rule7_windows_with_production_reference_passes():
    r = claims._rule_7_lane("ran the benchmark on windows and confirmed on linux production")
    assert r["pass"] is True


def test_rule7_no_lane_signal_passes():
    r = claims._rule_7_lane("plain statement")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# Rule 8 — source not live
# ---------------------------------------------------------------------------


def test_rule8_performance_claim_without_lifecycle_stage_fails():
    r = claims._rule_8_source("the system is fast")
    assert r["pass"] is False


def test_rule8_source_only_perf_claim_fails():
    r = claims._rule_8_source("the source code is fast")
    assert r["pass"] is False


def test_rule8_source_and_live_without_separation_fails():
    r = claims._rule_8_source("the source code is deployed to production and fast")
    assert r["pass"] is False


def test_rule8_source_and_live_with_separation_passes():
    r = claims._rule_8_source(
        "the source code is fast in benchmarks, and separately, deployed to production it is stable"
    )
    assert r["pass"] is True


def test_rule8_no_performance_claim_passes():
    r = claims._rule_8_source("just a plain informational statement")
    assert r["pass"] is True


def test_rule8_running_stage_perf_claim_passes():
    r = claims._rule_8_source("the running process handles load well")
    assert r["pass"] is True


# ---------------------------------------------------------------------------
# suggest_tag
# ---------------------------------------------------------------------------


def test_suggest_tag_measured():
    assert claims.suggest_tag("latency dropped to 12ms") == claims.TAG_MEASURED


def test_suggest_tag_canon():
    assert claims.suggest_tag("verified against the ci pipeline") == claims.TAG_CANON


def test_suggest_tag_unverified():
    assert claims.suggest_tag("i just feel like it works") == claims.TAG_UNVERIFIED


# ---------------------------------------------------------------------------
# check_statement / tag_statement
# ---------------------------------------------------------------------------


def test_check_statement_all_pass():
    result = claims.check_statement("nothing controversial here")
    assert result["pass"] is True
    assert result["pass_count"] == 8
    assert result["fail_count"] == 0
    assert result["suggested_tag"] == claims.TAG_UNVERIFIED


def test_check_statement_some_fail():
    result = claims.check_statement("this is a critical bug and it is faster")
    assert result["pass"] is False
    assert result["fail_count"] > 0


def test_tag_statement_shape():
    result = claims.tag_statement("latency dropped to 12ms")
    assert result["tag"] == claims.TAG_MEASURED
    assert "results" in result


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_with_claims_list():
    report = claims.generate_report(["latency dropped to 12ms", "i feel good about it"])
    assert report["status"] == "ok"
    assert report["claims_checked"] == 2
    assert set(report["tag_counts"]) <= {claims.TAG_MEASURED, claims.TAG_CANON, claims.TAG_UNVERIFIED}


def test_generate_report_missing_file_returns_no_report(tmp_path):
    missing = tmp_path / "nope.json"
    report = claims.generate_report(path=str(missing))
    assert report["status"] == "no_report"
    assert report["claims_checked"] == 0


def test_generate_report_loads_existing_file(tmp_path):
    report_path = tmp_path / "claims_report.json"
    report_path.write_text(json.dumps({"status": "ok", "claims": []}), encoding="utf-8")
    report = claims.generate_report(path=str(report_path))
    assert report["status"] == "ok"


# ---------------------------------------------------------------------------
# CLI entrypoints
# ---------------------------------------------------------------------------


def test_cmd_check_no_args(capsys):
    rc = claims.cmd_check([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "usage" in err


def test_cmd_check_passes(capsys):
    rc = claims.cmd_check(["plain", "statement"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["pass"] is True


def test_cmd_check_fails(capsys):
    rc = claims.cmd_check(["this", "is", "critical"])
    assert rc == 1


def test_cmd_tag_no_args(capsys):
    rc = claims.cmd_tag([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "usage" in err


def test_cmd_tag_prints_result(capsys):
    rc = claims.cmd_tag(["latency", "dropped", "to", "12ms"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["tag"] == claims.TAG_MEASURED


def test_cmd_report_with_json_file(tmp_path, capsys):
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps(["a plain statement"]), encoding="utf-8")
    rc = claims.cmd_report(["--json", str(claims_file)])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["claims_checked"] == 1


def test_cmd_report_json_file_not_found(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    rc = claims.cmd_report(["--json", str(missing)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "claims report:" in err


def test_cmd_report_json_file_not_a_list(tmp_path, capsys):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    rc = claims.cmd_report(["--json", str(bad_file)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "must point to a JSON array" in err


def test_cmd_report_with_inline_claims(capsys):
    rc = claims.cmd_report(["a", "plain", "statement"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["claims_checked"] == 3


def test_cmd_report_with_path(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"status": "ok", "claims": []}), encoding="utf-8")
    rc = claims.cmd_report(["--path", str(report_path)])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["status"] == "ok"


def test_main_no_args_prints_usage(capsys):
    rc = claims.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "usage" in err


def test_main_unknown_subcommand(capsys):
    rc = claims.main(["bogus"])
    assert rc == 2


def test_main_check_dispatch(capsys):
    rc = claims.main(["check", "plain", "statement"])
    assert rc == 0


def test_main_tag_dispatch(capsys):
    rc = claims.main(["tag", "plain", "statement"])
    assert rc == 0


def test_main_report_dispatch(capsys):
    rc = claims.main(["report", "plain", "statement"])
    assert rc == 0


def test_run_adapter_check(capsys):
    ns = argparse.Namespace(claims_cmd="check", statement=["plain", "statement"])
    rc = claims.run(ns)
    assert rc == 0


def test_run_adapter_tag(capsys):
    ns = argparse.Namespace(claims_cmd="tag", statement=["plain", "statement"])
    rc = claims.run(ns)
    assert rc == 0


def test_run_adapter_report(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"status": "ok", "claims": []}), encoding="utf-8")
    ns = argparse.Namespace(
        claims_cmd="report",
        path=str(report_path),
        json_file=None,
        claims=[],
    )
    rc = claims.run(ns)
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["status"] == "ok"


def test_run_adapter_report_with_json_file(tmp_path, capsys):
    claims_file = tmp_path / "claims.json"
    claims_file.write_text(json.dumps(["plain statement"]), encoding="utf-8")
    ns = argparse.Namespace(
        claims_cmd="report",
        path=None,
        json_file=str(claims_file),
        claims=[],
    )
    rc = claims.run(ns)
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["claims_checked"] == 1
