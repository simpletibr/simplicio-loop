"""pattern_match (intake): the issue against the bug patterns of simplicio-learn (patterns.jsonl); records hit_count."""
import json

from simplicio_loop.watcher247 import points

ISSUE = {"number": 9, "title": "Lease heartbeat dies", "body": "TimeoutError: heartbeat missed after 30s"}
FP = "a1b2c3d4e5f6a7b8c9d0"


def write_patterns(clone, *rows, raw=None):
    folder = clone / ".simplicio-loop" / "orchestrator"
    folder.mkdir(parents=True)
    lines = [json.dumps(r) for r in rows] + ([raw] if raw else [])
    (folder / "patterns.jsonl").write_text("\n".join(lines) + "\n")


def row(fingerprint=FP, symptom="heartbeat missed", hits=1, **extra):
    return {"fingerprint": fingerprint, "root_cause": "lease ttl shorter than a tick", "symptom_pattern": symptom,
            "fix_summary": "renew in the tick", "sibling_files": ["claim.py"], "hit_count": hits,
            "last_seen": "2026-10-01T00:00:00Z", **extra}


def test_registered_at_intake_conditional_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "pattern_match"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, True)


def test_contract(point_contract, make_ctx, tmp_path):
    write_patterns(tmp_path, row())
    point_contract("pattern_match", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")


def test_symptom_hit_records_hit_count(point_contract, make_ctx, tmp_path):
    write_patterns(tmp_path, row(hits=3), row(fingerprint="f" * 20, symptom="disk full", hits=9))
    result = point_contract("pattern_match", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["hit_count"] == 3
    assert [m["fingerprint"] for m in result.evidence["matches"]] == [FP[:12]]
    assert result.evidence["matches"][0]["fix_summary"] == "renew in the tick"
    assert result.evidence["structural_attention"] is True  # hit_count > 1: the module keeps breaking


def test_fingerprint_in_the_issue_text_is_a_hit(point_contract, make_ctx, tmp_path):
    write_patterns(tmp_path, row(symptom="never in the issue", hits=1))
    issue = {**ISSUE, "body": f"seen before: {FP[:12]}"}
    result = point_contract("pattern_match", make_ctx(clone=tmp_path, issue=issue), expect="ok")
    assert result.evidence["hit_count"] == 1
    assert result.evidence["structural_attention"] is False


def test_invalid_regex_falls_back_to_substring(point_contract, make_ctx, tmp_path):
    write_patterns(tmp_path, row(symptom="heartbeat missed ("))
    issue = {**ISSUE, "body": "log: heartbeat missed ("}
    result = point_contract("pattern_match", make_ctx(clone=tmp_path, issue=issue), expect="ok")
    assert result.evidence["hit_count"] == 1


def test_no_store_is_ok_and_names_unverified(point_contract, make_ctx, tmp_path):
    result = point_contract("pattern_match", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence == {"matches": [], "hit_count": 0, "structural_attention": False,
                               "label": "UNVERIFIED|no_pattern_store"}


def test_bad_lines_are_skipped(point_contract, make_ctx, tmp_path):
    write_patterns(tmp_path, row(), raw="{not json")
    result = point_contract("pattern_match", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["hit_count"] == 1


def test_without_issue_or_clone_it_is_skipped(point_contract, make_ctx, tmp_path):
    assert point_contract("pattern_match", make_ctx(clone=tmp_path), expect="skipped").reason_code == "not_applicable"
    assert point_contract("pattern_match", make_ctx(issue=ISSUE), expect="skipped").reason_code == "not_applicable"
