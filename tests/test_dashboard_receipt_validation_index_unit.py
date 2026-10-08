'''Unit tests for the receipt validation in the run detail of the Simplicio Live drill-down (issue #1405, slice 1405c, TDD red).

run_detail gives each indexed receipt its schema verdict, so the page shows VALID, INVALID or UNVERIFIED from the server.
'''
import json
from datetime import datetime, timezone

from simplicio_loop import stage_agents
from simplicio_loop.dashboard import runs

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


def _run(tmp_path):
    run_dir = tmp_path / 'repo' / '.simplicio-loop' / 'loop-runs' / 'run-v1'
    (run_dir / 'receipts').mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': 'run-v1', 'status': 'running', 'phase': 'executing'}), encoding='utf-8')
    return run_dir


def _by_name(detail):
    return {row['name']: row for row in detail['receipts']}


def test_a_valid_stage_receipt_is_listed_as_valid(tmp_path):
    run_dir = _run(tmp_path)
    receipt = stage_agents.make_stage_receipt(
        receipt_id='rcp-1', agent_instance_id='inst-1', role_id='implementation_agent', stage_id='executing',
        run_id='run-v1', task_id='task-1', attempt_id='att-1', attempt_ordinal=1, fence='fence-1',
        plan_revision=1, context_hash='a' * 64, manifest_hash='b' * 64, verdict='pass',
        evidence_refs=('evidence/unit.json',), now=NOW)
    (run_dir / 'receipts' / 'stage-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    row = _by_name(runs.run_detail(run_dir))['receipts/stage-receipt.json']
    assert row['validation']['state'] == 'VALID', row


def test_a_receipt_without_a_shipped_schema_is_listed_as_unverified_with_the_reason(tmp_path):
    run_dir = _run(tmp_path)
    (run_dir / 'completion-receipt.json').write_text(json.dumps({'schema': 'simplicio.completion-receipt/v1'}), encoding='utf-8')
    row = _by_name(runs.run_detail(run_dir))['completion-receipt.json']
    assert row['validation'] == {'state': 'UNVERIFIED', 'reason': 'sem schema publicado para simplicio.completion-receipt/v1'}


def test_the_quality_matrix_is_listed_with_its_own_verdict(tmp_path):
    run_dir = _run(tmp_path)
    (run_dir / 'quality-matrix.json').write_text(json.dumps({'schema': 'simplicio.quality-matrix/v1'}), encoding='utf-8')
    row = _by_name(runs.run_detail(run_dir))['quality-matrix.json']
    assert row['validation']['state'] == 'UNVERIFIED', row
