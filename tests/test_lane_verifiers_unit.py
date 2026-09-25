"""Per-lane verifiers: the task file names one command per quality lane and the
loop measures each in the target repo to build quality-matrix.json. Nothing is
inferred: a lane without a command blocks, naming the line to add."""
from __future__ import annotations

import json
import sys

from simplicio_loop import lane_verifiers as lv
from simplicio_loop.quality_matrix import evaluate_quality_matrix

PY = sys.executable
OK = f'`{PY} -c "print(1)"`'
SLOW = f'`{PY} -c "import time; time.sleep(0.15)"`'


def _task(**lanes):
    lines = [f"{name.capitalize()} verifier: {cmd}" for name, cmd in lanes.items()]
    return "8. Additional Information\n\n" + "\n".join(lines) + "\n"


ALL = dict(unit=OK, integration=OK, system=OK, regression=OK, benchmark=OK,
           coverage=f'`{PY} -c "print(\'TOTAL  120  3  97%\')"`')


def test_parse_reads_one_command_per_lane():
    parsed = lv.parse_lane_verifiers(_task(unit="`pytest -q tests/unit`", benchmark="`python bench.py`"))
    assert parsed == {"unit": "pytest -q tests/unit", "benchmark": "python bench.py"}


def _run_dir(tmp_path, applied=True):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "operator-receipt-1.json").write_text(json.dumps(
        {"execution_state": "applied" if applied else "blocked"}))
    return run_dir


def test_all_declared_lanes_measured_make_the_gate_pass(tmp_path):
    run_dir = _run_dir(tmp_path)
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**ALL)])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is True, verdict
    assert verdict["coverage_measured"] == 97.0


def test_undeclared_lane_blocks_and_names_the_missing_line(tmp_path):
    run_dir = _run_dir(tmp_path)
    lanes = dict(ALL)
    del lanes["system"]
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**lanes)])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is False
    receipt = json.loads((run_dir / "quality-matrix.json").read_text())
    assert "System verifier:" in receipt["requirements"]["system"]["detail"]


def test_failing_lane_command_fails_the_lane(tmp_path):
    run_dir = _run_dir(tmp_path)
    lanes = dict(ALL, integration=f'`{PY} -c "import sys; sys.exit(3)"`')
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**lanes)])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_integration_failed"


def test_implementation_requires_applied_operator_receipts(tmp_path):
    run_dir = _run_dir(tmp_path, applied=False)
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**ALL)])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["reason_code"] == "quality_implementation_failed"


def test_missing_or_unapplied_tasks_counts_every_task_index(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "operator-receipt-1.json").write_text(json.dumps({"execution_state": "applied"}))
    # tasks 2 and 3 dead-lettered before dev-cli ever ran: no receipt file at all.
    assert lv.missing_or_unapplied_tasks(run_dir, 3) == [2, 3]


def test_implementation_gate_fails_when_most_tasks_never_got_a_receipt(tmp_path):
    """Regression for the wave benchmark's false-VERIFIED: only task 1 of 10 applied
    (tasks 2..10 dead-lettered with plan_repo_state_stale and wrote no receipt), yet
    the old `bool(receipts) and all(...)` check only looked at the receipts that
    happened to exist and reported implementation: pass."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "operator-receipt-1.json").write_text(json.dumps({"execution_state": "applied"}))
    task_texts = [_task(**ALL)] + [_task() for _ in range(9)]
    receipt = lv.build_quality_matrix(tmp_path, run_dir, task_texts)
    assert receipt["requirements"]["implementation"]["status"] == "fail"
    assert receipt["requirements"]["implementation"]["missing_task_indices"] == list(range(2, 11))
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is False
    assert verdict["reason_code"] == "quality_implementation_failed"


def test_independent_reverify_reruns_declared_lane_commands_in_the_target_repo(tmp_path, monkeypatch):
    from simplicio_loop import quality_matrix as qm

    marker = tmp_path / "reran.txt"
    lanes = dict(ALL, unit=f'`{PY} -c "open(\'reran.txt\', \'a\').write(\'u\')"`')
    run_dir = _run_dir(tmp_path)
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**lanes)])
    marker.unlink()

    def forbidden(*_a, **_k):
        raise AssertionError("must not run simplicio-loop's own gate scripts")

    monkeypatch.setattr(qm, "_rerun_gate_script", forbidden)
    monkeypatch.setattr(qm, "_rerun_coverage_gate", forbidden)
    verdict = qm.independent_reverify_quality_matrix(str(run_dir), repo=str(tmp_path))
    assert verdict["ready"] is True, verdict
    assert marker.read_text() == "u"


def test_independent_reverify_catches_a_lane_that_now_fails(tmp_path):
    from simplicio_loop import quality_matrix as qm

    flag = tmp_path / "ok"
    flag.write_text("1")
    lanes = dict(ALL, system=f'`{PY} -c "import os,sys; sys.exit(0 if os.path.exists(\'ok\') else 1)"`')
    run_dir = _run_dir(tmp_path)
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**lanes)])
    flag.unlink()
    verdict = qm.independent_reverify_quality_matrix(str(run_dir), repo=str(tmp_path))
    assert verdict["ready"] is False


# --------------------------------------------------------------------------
# Conditional lanes: a Docs/Chore/Config task, or an explicit `Tests: none`
# line, only needs implementation (+ its Independent verifier if declared);
# missing quality lanes are waived, not blocking.
# --------------------------------------------------------------------------

def _story(header_lines, **lanes):
    lines = [f"{name.capitalize()} verifier: {cmd}" for name, cmd in lanes.items()]
    return "\n".join(header_lines) + "\n\n8. Additional Information\n\n" + "\n".join(lines) + "\n"


def test_lanes_required_true_for_feature_type():
    text = _story(["Type: Feature"])
    assert lv.lanes_required(text) is True


def test_lanes_required_false_for_docs_type():
    text = _story(["Type: Docs"])
    assert lv.lanes_required(text) is False


def test_lanes_required_false_for_chore_type():
    text = _story(["Type: Chore"])
    assert lv.lanes_required(text) is False


def test_lanes_required_false_for_config_type():
    text = _story(["Type: Config"])
    assert lv.lanes_required(text) is False


def test_lanes_required_false_for_explicit_tests_none():
    text = _story(["Type: Feature", "Tests: none"])
    assert lv.lanes_required(text) is False


def test_lanes_required_defaults_true_with_no_type_header():
    assert lv.lanes_required("8. Additional Information\n\nUnit verifier: `x`\n") is True


def test_docs_task_with_no_lanes_declared_does_not_block_the_gate(tmp_path):
    run_dir = _run_dir(tmp_path)
    text = _story(["Type: Docs"])  # no lane verifiers declared at all
    receipt = lv.build_quality_matrix(tmp_path, run_dir, [text])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is True, verdict
    assert receipt["policy"]["unit_required"] is False
    assert receipt["policy"]["benchmark_required"] is False


def test_feature_task_with_no_lanes_declared_still_blocks_the_gate(tmp_path):
    run_dir = _run_dir(tmp_path)
    text = _story(["Type: Feature"])  # no lane verifiers declared
    lv.build_quality_matrix(tmp_path, run_dir, [text])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is False


def test_mixed_batch_requires_lanes_if_any_task_needs_them(tmp_path):
    run_dir = _run_dir(tmp_path)
    docs_text = _story(["Type: Docs"])
    feature_text = _story(["Type: Feature"])
    lv.build_quality_matrix(tmp_path, run_dir, [docs_text, feature_text])
    verdict = evaluate_quality_matrix(str(run_dir))
    assert verdict["ready"] is False


# --------------------------------------------------------------------------
# Concurrent lane execution: independent lane commands run via asyncio.gather,
# not sequentially -- N slow commands should take much less than N * duration.
# --------------------------------------------------------------------------

def test_declared_lanes_run_concurrently_not_sequentially(tmp_path):
    import time as _time

    run_dir = _run_dir(tmp_path)
    lanes = dict(unit=SLOW, integration=SLOW, system=SLOW, regression=SLOW, benchmark=SLOW)
    started = _time.perf_counter()
    lv.build_quality_matrix(tmp_path, run_dir, [_task(**lanes)])
    elapsed = _time.perf_counter() - started
    # Five 0.15s lanes run concurrently should finish well under the ~0.75s
    # a sequential loop would take.
    assert elapsed < 0.5, elapsed
