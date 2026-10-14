"""reuse_precedent (plan): only a native precedent of high reuse_level (git-apply dry-run checked) is reusable."""
import json

from simplicio_loop.watcher247 import points

ISSUE = {"number": 7, "title": "watcher lease heartbeat expires", "body": "the lease is lost mid run"}


def native(monkeypatch, *candidates):
    """The mapper's precedent ranking answers as the native runtime would."""
    from simplicio_mapper import prototype_context
    monkeypatch.setattr(prototype_context, "_precedent_candidates", lambda cwd, items, query, limit: (
        list(candidates), {"runtime": "simplicio-runtime", "used": True, "reason": "delegated"}))


def candidate(pid, level, action="apply"):
    return {"precedent_id": pid, "path": f"{pid}.py", "summary": pid, "tags": [], "confidence": 0.9,
            "provenance": "runtime-precedent-search", "reuse_level": level, "suggested_next_action": action}


def test_registered_at_plan_conditional_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "reuse_precedent"]
    assert (info.stage, info.blocking, info.conditional) == ("plan", False, True)


def test_contract(point_contract, make_ctx, tmp_path, monkeypatch):
    native(monkeypatch, candidate("p1", "high"))
    point_contract("reuse_precedent", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")


def test_high_reuse_level_is_reusable(point_contract, make_ctx, tmp_path, monkeypatch):
    native(monkeypatch, candidate("p-low", "low"), candidate("p-high", "high", "apply_patch"))
    result = point_contract("reuse_precedent", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["reuse"] == {"precedent_id": "p-high", "path": "p-high.py", "reuse_level": "high",
                                        "suggested_next_action": "apply_patch"}


def test_low_reuse_level_is_not_reused(point_contract, make_ctx, tmp_path, monkeypatch):
    native(monkeypatch, candidate("p-low", "low"))
    result = point_contract("reuse_precedent", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["reuse"] is None


def test_local_ranking_never_claims_reuse(point_contract, make_ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT", "1")
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "precedent-index.json").write_text(json.dumps({"items": [
        {"id": "p1", "path": "lease.py", "summary": "watcher lease heartbeat", "tags": ["lease"]}]}))
    result = point_contract("reuse_precedent", make_ctx(clone=tmp_path, issue=ISSUE), expect="ok")
    assert result.evidence["reuse"] is None  # a keyword overlap is not a checked reuse
    assert result.evidence["label"] == "UNVERIFIED|no_reusable_precedent"


def test_without_issue_or_clone_it_is_skipped(point_contract, make_ctx, tmp_path):
    assert point_contract("reuse_precedent", make_ctx(clone=tmp_path), expect="skipped").reason_code == "not_applicable"
    assert point_contract("reuse_precedent", make_ctx(issue=ISSUE), expect="skipped").reason_code == "not_applicable"
