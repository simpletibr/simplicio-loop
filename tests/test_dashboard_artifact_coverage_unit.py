'''Artifact coverage for the Simplicio Live inspector (issue #1405).

The run-state/v1 contract lists no artifacts, so the real list is run_detail's ``receipts`` and ``artifacts``. Every name
in it must be readable through the artifact route, and the page must keep a way to open each kind.
'''
import json
from pathlib import Path

import pytest

from simplicio_loop.dashboard import runs

LIVE = Path(runs.__file__).parent / 'static' / 'live'


def _full_run(tmp_path):
    run_dir = tmp_path / 'repo' / '.simplicio-loop' / 'loop-runs' / 'run-cov'
    (run_dir / 'receipts').mkdir(parents=True)
    files = {
        'state.json': {'run_id': 'run-cov', 'status': 'running', 'phase': 'executing'},
        'manifest.json': {'schema': 'simplicio.manifest/v1'},
        'plan.json': {'steps': []},
        'task-contract.json': {'acs': []},
        'mapper-context.json': {'files': []},
        'quality-matrix.json': {'schema': 'simplicio.quality-matrix/v1'},
        'completion-receipt.json': {'schema': 'simplicio.completion-receipt/v1'},
        'receipts/operator-receipt.json': {'schema': 'simplicio.operator-receipt/v1'},
        'receipts/evidence-receipt.json': {'schema': 'simplicio.evidence-receipt/v1'},
        'receipts/delivery-receipt.json': {'schema': 'simplicio.delivery-receipt/v1'},
    }
    for name, body in files.items():
        (run_dir / name).write_text(json.dumps(body), encoding='utf-8')
    return run_dir


def test_every_indexed_receipt_and_artifact_is_readable_through_the_artifact_route(tmp_path):
    run_dir = _full_run(tmp_path)
    detail = runs.run_detail(run_dir)
    names = [row['name'] for row in detail['receipts']] + list(detail['artifacts'])
    assert len(names) == len(set(names)) and len(names) >= 7, names
    for name in names:
        assert json.loads(runs.read_artifact(run_dir, name)), name


def test_the_state_manifest_and_plan_are_readable_as_artifacts_too(tmp_path):
    run_dir = _full_run(tmp_path)
    for name in ('state.json', 'manifest.json', 'plan.json'):
        assert json.loads(runs.read_artifact(run_dir, name)), name


@pytest.mark.parametrize('name', runs.ON_DEMAND_ARTIFACTS)
def test_every_on_demand_artifact_has_a_drill_down_tab(name):
    tab = {'task-contract.json': 'contract', 'mapper-context.json': 'context'}[name]
    assert f"'{tab}'" in (LIVE / 'app.js').read_text(encoding='utf-8')


def test_receipts_are_linked_to_their_raw_artifact_in_the_drawer():
    source = (LIVE / 'drill-tabs.js').read_text(encoding='utf-8')
    assert "setAttr(link, 'href', artifactHref(runId, row.name, token)" in source
    assert '/artifacts/' in (LIVE / 'lanes.js').read_text(encoding='utf-8')
