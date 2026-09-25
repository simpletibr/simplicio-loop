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
