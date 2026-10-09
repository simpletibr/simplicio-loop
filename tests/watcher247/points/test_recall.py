"""recall (plan): top prior precedents of the issue, from the mapper's precedent ranking (no new ranking)."""
import json

import pytest

from simplicio_loop.watcher247 import points

ISSUE = {"number": 7, "title": "watcher lease heartbeat expires", "body": "the lease is lost mid run"}
ITEMS = [
    {"id": "p-lease", "path": "lease.py", "summary": "fix watcher lease heartbeat", "tags": ["watcher", "lease"]},
    {"id": "p-css", "path": "ui.css", "summary": "button color", "tags": ["css"]},
]


@pytest.fixture(autouse=True)
def local_ranking(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT", "1")  # the mapper's own kill-switch: local ranking


def write_index(clone, items=ITEMS):
    (clone / ".simplicio-loop").mkdir()
    (clone / ".simplicio-loop" / "precedent-index.json").write_text(json.dumps({"items": items}))


def test_registered_at_plan_conditional_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "recall"]
    assert (info.stage, info.blocking, info.conditional) == ("plan", False, True)


def test_contract(point_contract, make_ctx, tmp_path):
    write_index(tmp_path)
    point_contract("recall", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")


def test_top_matches_are_the_evidence(point_contract, make_ctx, tmp_path):
    write_index(tmp_path)
    result = point_contract("recall", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert [m["precedent_id"] for m in result.evidence["matches"]] == ["p-lease"]  # zero overlap is dropped
    assert result.evidence["matches"][0]["summary"] == "fix watcher lease heartbeat"
    assert result.evidence["matches"][0]["provenance"] == "local-keyword-overlap:precedent-index"
    assert result.evidence["delegation"]["used"] is False


def test_no_precedent_is_ok_and_names_unverified(point_contract, make_ctx, tmp_path):
    result = point_contract("recall", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["matches"] == []
    assert result.evidence["label"] == "UNVERIFIED|no_precedent_found"


def test_malformed_index_never_crashes(point_contract, make_ctx, tmp_path):
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "precedent-index.json").write_text("{not json")
    result = point_contract("recall", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["matches"] == []


def test_without_issue_or_clone_it_is_skipped(point_contract, make_ctx, tmp_path):
    assert point_contract("recall", make_ctx(clone=tmp_path), expect="skipped").reason_code == "not_applicable"
    assert point_contract("recall", make_ctx(issue=ISSUE), expect="skipped").reason_code == "not_applicable"
