"""Unit tests for scripts/finding_collector.py (issue #466, phase-1 slice: T1).

Covers schema validation (state must be one of the allowed set), fingerprint stability
across ephemeral noise (timestamps/hex ids/tmp paths/line numbers), and dedup/increment
behavior (a repeat sighting of the same defect bumps occurrence_count instead of creating
a second record).
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("finding_collector", ROOT / "scripts" / "finding_collector.py")
finding_collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finding_collector)  # type: ignore[union-attr]


@pytest.fixture
def isolated_findings(tmp_path, monkeypatch):
    findings_dir = tmp_path / "findings"
    monkeypatch.setattr(finding_collector, "FINDINGS_DIR", str(findings_dir))
    monkeypatch.setattr(finding_collector, "FINDINGS_PATH", str(findings_dir / "findings.jsonl"))
    return findings_dir


def test_fingerprint_stable_across_timestamps_hex_and_tmp_paths():
    fp_a = finding_collector.fingerprint(
        "acme/repo", "scripts/x.py", "NameError",
        "name 'foo' is not defined at 2026-07-17T10:00:00Z line:42 /tmp/abc123def/x.py")
    fp_b = finding_collector.fingerprint(
        "acme/repo", "scripts/x.py", "NameError",
        "name 'foo' is not defined at 2026-07-18T11:30:05Z line:99 /tmp/9988776655/x.py")
    assert fp_a == fp_b


def test_fingerprint_differs_for_different_signature():
    fp_a = finding_collector.fingerprint("acme/repo", "scripts/x.py", "NameError", "foo undefined")
    fp_b = finding_collector.fingerprint("acme/repo", "scripts/x.py", "NameError", "bar undefined")
    assert fp_a != fp_b


def test_fingerprint_differs_for_different_component():
    fp_a = finding_collector.fingerprint("acme/repo", "scripts/x.py", "NameError", "same signature")
    fp_b = finding_collector.fingerprint("acme/repo", "scripts/y.py", "NameError", "same signature")
    assert fp_a != fp_b


def test_record_rejects_invalid_state(isolated_findings):
    with pytest.raises(ValueError):
        finding_collector.record_finding(
            "scripts/x.py", "NameError", "sig", "summary",
            owner_repo="acme/repo", state="not-a-real-state")


def test_record_accepts_all_documented_states(isolated_findings):
    for state in sorted(finding_collector.STATES):
        rec = finding_collector.record_finding(
            "scripts/x.py", "NameError", f"distinct-signature-for-{state}", "summary",
            owner_repo="acme/repo", state=state)
        assert rec["state"] == state
        assert rec["schema"] == finding_collector.SCHEMA


def test_duplicate_sighting_bumps_occurrence_not_new_record(isolated_findings):
    rec1 = finding_collector.record_finding(
        "scripts/x.py", "NameError",
        "name 'foo' is not defined at 2026-07-17T10:00:00Z line:42 /tmp/abc123/x.py",
        "crash on selftest", owner_repo="acme/repo")
    assert rec1["occurrence_count"] == 1

    rec2 = finding_collector.record_finding(
        "scripts/x.py", "NameError",
        "name 'foo' is not defined at 2026-07-18T11:30:05Z line:99 /tmp/def456/x.py",
        "crash on selftest (again)", owner_repo="acme/repo")
    assert rec2["occurrence_count"] == 2
    assert rec2["fingerprint"] == rec1["fingerprint"]

    all_records = finding_collector._load_all()
    assert len(all_records) == 1


def test_distinct_findings_produce_distinct_records(isolated_findings):
    finding_collector.record_finding("scripts/x.py", "NameError", "sig-a", "a", owner_repo="acme/repo")
    finding_collector.record_finding("scripts/y.py", "ValueError", "sig-b", "b", owner_repo="acme/repo")
    assert len(finding_collector._load_all()) == 2


def test_repeat_sighting_can_transition_to_disproved(isolated_findings):
    finding_collector.record_finding(
        "scripts/x.py", "NameError", "name 'foo' is not defined at 2026-07-17T10:00:00Z /tmp/a/x.py",
        "first sighting", owner_repo="acme/repo", state="confirmed")
    updated = finding_collector.record_finding(
        "scripts/x.py", "NameError", "name 'foo' is not defined at 2026-07-18T10:00:00Z /tmp/b/x.py",
        "re-checked, was a stale cache", owner_repo="acme/repo", state="disproved")
    assert updated["state"] == "disproved"
    assert updated["occurrence_count"] == 2


def test_cmd_status_counts_by_state(isolated_findings, capsys):
    finding_collector.record_finding("scripts/x.py", "NameError", "sig-a", "a", owner_repo="acme/repo",
                                     state="confirmed")
    finding_collector.record_finding("scripts/y.py", "ValueError", "sig-b", "b", owner_repo="acme/repo",
                                     state="suspected")
    finding_collector.cmd_status({})
    out = capsys.readouterr().out.strip()
    assert out.startswith("MEASURED|")
    payload = json.loads(out[len("MEASURED|"):])
    assert payload["total"] == 2
    assert payload["confirmed"] == 1
    assert payload["suspected"] == 1


def test_cmd_list_filters_by_state(isolated_findings, capsys):
    finding_collector.record_finding("scripts/x.py", "NameError", "sig-a", "a", owner_repo="acme/repo",
                                     state="confirmed")
    finding_collector.record_finding("scripts/y.py", "ValueError", "sig-b", "b", owner_repo="acme/repo",
                                     state="suspected")
    capsys.readouterr()
    finding_collector.cmd_list({"state": "confirmed"})
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert json.loads(out[0][len("MEASURED|"):])["component"] == "scripts/x.py"


def test_selftest_passes():
    assert finding_collector.cmd_selftest({}) == 0


# --- IssueTargetResolver (#493, T2) ---

def test_resolve_owner_exact_match():
    result = finding_collector.resolve_owner("scripts/coordinator.py")
    assert result["repo"] == "simpletibr/simplicio-loop"
    assert result["reason_code"] == "exact_match"


def test_resolve_owner_no_match_falls_back_with_explicit_reason():
    result = finding_collector.resolve_owner("totally-unrelated-thing.exe")
    assert result["repo"] == finding_collector.FALLBACK_REPOSITORY
    assert result["reason_code"] == "fallback_no_match"
    assert result["candidates"] == []


def test_resolve_owner_custom_fallback_repository():
    result = finding_collector.resolve_owner("nothing-matches", fallback_repository="acme/custom-fallback")
    assert result["repo"] == "acme/custom-fallback"


def test_resolve_owner_ambiguous_component_never_guesses():
    ownership_map = {"scripts/": "repo-a/repo-a", "simplicio-mapper": "repo-b/repo-b"}
    result = finding_collector.resolve_owner("scripts/simplicio-mapper-helper.py", ownership_map=ownership_map)
    assert result["repo"] is None
    assert result["reason_code"] == "triage_multiple_candidates"
    assert result["candidates"] == ["repo-a/repo-a", "repo-b/repo-b"]


def test_resolve_owner_same_repo_matched_twice_is_not_ambiguous():
    ownership_map = {"scripts/": "acme/repo", "simplicio_loop/": "acme/repo"}
    result = finding_collector.resolve_owner("scripts/simplicio_loop/x.py", ownership_map=ownership_map)
    assert result["repo"] == "acme/repo"
    assert result["reason_code"] == "exact_match"


def test_cmd_resolve_requires_component():
    with pytest.raises(SystemExit) as exc_info:
        finding_collector.cmd_resolve({})
    assert exc_info.value.code == 2


def test_cmd_resolve_prints_measured_for_exact_match(capsys):
    finding_collector.cmd_resolve({"component": "scripts/coordinator.py"})
    out = capsys.readouterr().out.strip()
    assert out.startswith("MEASURED|")
    payload = json.loads(out[len("MEASURED|"):])
    assert payload["repo"] == "simpletibr/simplicio-loop"


def test_cmd_resolve_prints_unverified_for_triage(capsys):
    finding_collector.cmd_resolve({"component": "totally-unrelated-thing.exe",
                                   "fallback-repository": "acme/fallback"})
    out = capsys.readouterr().out.strip()
    payload = json.loads(out[len("MEASURED|"):])
    assert payload["repo"] == "acme/fallback"
