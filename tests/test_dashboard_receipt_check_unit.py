'''Unit tests for the receipt schema check of the Simplicio Live drill-down (issue #1405, slice 1405c, TDD red).

receipt_check.check_receipt reads one receipt file and reports VALID, INVALID or UNVERIFIED with a reason. It checks
only schemas the package ships (simplicio_loop/_contracts). A receipt whose schema is not shipped stays UNVERIFIED,
and it is never shown as valid. jsonschema is a runtime dependency; the check runs in-process.
'''
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from simplicio_loop import stage_agents
from simplicio_loop.dashboard import receipt_check

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


def _stage_receipt():
    return stage_agents.make_stage_receipt(
        receipt_id='rcp-1', agent_instance_id='inst-1', role_id='implementation_agent', stage_id='executing',
        run_id='run-r1', task_id='task-1', attempt_id='att-1', attempt_ordinal=1, fence='fence-1',
        plan_revision=1, context_hash='a' * 64, manifest_hash='b' * 64, verdict='pass',
        evidence_refs=('evidence/unit.json',), now=NOW,
    )


def _write(tmp_path, payload, name='stage-receipt.json'):
    path = tmp_path / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding='utf-8')
    return path


def test_a_receipt_the_package_builds_is_valid_against_its_shipped_schema(tmp_path):
    result = receipt_check.check_receipt(_write(tmp_path, _stage_receipt()))
    assert result == {'state': 'VALID', 'reason': 'conforme ao schema simplicio.stage-receipt/v1'}


def test_a_receipt_missing_a_required_field_is_invalid_with_a_readable_reason(tmp_path):
    receipt = _stage_receipt()
    del receipt['run_id']
    result = receipt_check.check_receipt(_write(tmp_path, receipt))
    assert result['state'] == 'INVALID'
    assert 'run_id' in result['reason'], result


def test_a_receipt_with_a_wrong_field_type_is_invalid(tmp_path):
    receipt = _stage_receipt()
    receipt['attempt_ordinal'] = 'primeira'
    result = receipt_check.check_receipt(_write(tmp_path, receipt))
    assert result['state'] == 'INVALID', result
    assert 'attempt_ordinal' in result['reason'], result


def test_a_schema_the_package_does_not_ship_is_unverified_never_valid(tmp_path):
    receipt = {'schema': 'simplicio.delivery-receipt/v1', 'run_id': 'run-r1'}
    result = receipt_check.check_receipt(_write(tmp_path, receipt, name='delivery-receipt.json'))
    assert result == {'state': 'UNVERIFIED', 'reason': 'sem schema publicado para simplicio.delivery-receipt/v1'}


def test_a_file_that_is_not_json_is_unverified(tmp_path):
    result = receipt_check.check_receipt(_write(tmp_path, '{ not json'))
    assert result == {'state': 'UNVERIFIED', 'reason': 'recibo ilegível: não é JSON'}


@pytest.mark.parametrize('payload', [['a', 'list'], {'run_id': 'no-schema-field'}, {'schema': 7}])
def test_a_receipt_without_a_string_schema_is_unverified(tmp_path, payload):
    result = receipt_check.check_receipt(_write(tmp_path, payload))
    assert result == {'state': 'UNVERIFIED', 'reason': 'recibo sem campo schema'}


def test_an_oversized_receipt_is_unverified_without_being_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt_check, 'MAX_BYTES', 10)
    result = receipt_check.check_receipt(_write(tmp_path, _stage_receipt()))
    assert result == {'state': 'UNVERIFIED', 'reason': 'recibo grande demais para validar'}


def test_a_missing_file_is_unverified(tmp_path):
    result = receipt_check.check_receipt(tmp_path / 'absent.json')
    assert result['state'] == 'UNVERIFIED'
    assert result['reason']
