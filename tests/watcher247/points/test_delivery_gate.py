"""delivery_gate (pr, blocking): verify green + judge ACCEPT + secret-scan clean + Closes #N, from the ctx."""
import asyncio
import json

import pytest

from simplicio_loop.watcher247 import points, verify

from .blocking import point_contract  # noqa: F401  (the blocking variant of the fixture)

GREEN = "MEASURED|verify_passed: `python3 -m pytest -q`"
RED = "MEASURED|verify_failed: `python3 -m pytest -q`"
ACCEPT = {"verdict": "ACCEPT", "reasons": [], "files": ["app.py"], "secret_files": []}


def ctx_for(make_ctx, tmp_path, judge=ACCEPT, **fields):
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    if judge is not None:
        (run_dir / "judge.json").write_text(json.dumps(judge))
    fields.setdefault("verify", GREEN)
    fields.setdefault("issue", {"number": 1509})
    return make_ctx(run_dir=run_dir, **fields)


def test_registered_at_pr_and_blocking():
    [info] = [i for i in points.registered() if i.name == "delivery_gate"]
    assert (info.stage, info.blocking, info.conditional) == ("pr", True, False)


def test_everything_green_passes_and_names_the_closing_line(point_contract, make_ctx, tmp_path):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path), expect="ok")
    assert result.evidence == {"verify": "passed", "judge": "ACCEPT", "secret_scan": "clean",
                               "closes": "Closes #1509"}


def test_unverified_label_is_what_verify_decide_lets_through_and_is_flagged(point_contract, make_ctx, tmp_path):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, verify=verify.UNVERIFIED), expect="ok")
    assert result.evidence["verify"] == "unverified"


def test_missing_verify_blocks(make_ctx, tmp_path):
    with pytest.raises(points.PointBlocked) as blocked:
        asyncio.run(points.run("pr", ctx_for(make_ctx, tmp_path, verify=None)))
    assert (blocked.value.name, blocked.value.reason_code) == ("delivery_gate", "verify_missing")


def test_empty_verify_blocks(point_contract, make_ctx, tmp_path):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, verify="  "), expect="blocked")
    assert result.reason_code == "verify_missing"


def test_failed_verify_blocks(point_contract, make_ctx, tmp_path):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, verify=RED), expect="blocked")
    assert result.reason_code == "verify_failed"


def test_judge_reject_blocks(make_ctx, tmp_path):
    rejected = {**ACCEPT, "verdict": "REJECT", "reasons": ["empty_diff"]}
    with pytest.raises(points.PointBlocked) as blocked:
        asyncio.run(points.run("pr", ctx_for(make_ctx, tmp_path, judge=rejected)))
    assert blocked.value.reason_code == "judge_rejected"
    assert blocked.value.results[-1].evidence["judge"] == "REJECT"


def test_missing_judge_verdict_blocks(point_contract, make_ctx, tmp_path):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, judge=None), expect="blocked")
    assert result.reason_code == "judge_missing"


def test_unreadable_judge_verdict_blocks(point_contract, make_ctx, tmp_path):
    ctx = ctx_for(make_ctx, tmp_path)
    (ctx.run_dir / "judge.json").write_text("{not json")
    assert point_contract("delivery_gate", ctx, expect="blocked").reason_code == "judge_missing"


def test_no_run_dir_means_no_judge_verdict_and_blocks(point_contract, make_ctx):
    ctx = make_ctx(verify=GREEN, issue={"number": 7})
    assert point_contract("delivery_gate", ctx, expect="blocked").reason_code == "judge_missing"


def test_secret_found_by_the_scan_blocks_even_if_the_judge_said_accept(point_contract, make_ctx, tmp_path):
    dirty = {**ACCEPT, "secret_files": ["config.py"]}
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, judge=dirty), expect="blocked")
    assert result.reason_code == "secret_detected"
    assert result.evidence["secret_files"] == ["config.py"]


def test_a_verdict_without_the_scan_result_blocks(point_contract, make_ctx, tmp_path):
    no_scan = {"verdict": "ACCEPT", "reasons": []}
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, judge=no_scan), expect="blocked")
    assert result.reason_code == "secret_scan_missing"


@pytest.mark.parametrize("issue", [None, {}, {"number": None}, {"number": ""}, {"number": 0}])
def test_without_an_issue_number_there_is_no_closes_and_it_blocks(point_contract, make_ctx, tmp_path, issue):
    result = point_contract("delivery_gate", ctx_for(make_ctx, tmp_path, issue=issue), expect="blocked")
    assert result.reason_code == "closes_missing"


def test_every_failure_is_listed_and_the_first_is_the_reason(point_contract, make_ctx, tmp_path):
    ctx = ctx_for(make_ctx, tmp_path, judge=None, verify=RED, issue=None)
    result = point_contract("delivery_gate", ctx, expect="blocked")
    assert result.reason_code == "verify_failed"
    assert result.evidence["failures"] == ["verify_failed", "judge_missing", "closes_missing"]
