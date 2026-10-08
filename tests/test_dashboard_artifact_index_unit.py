'''Unit tests for the run artifact index of the Simplicio Live drill-down (issue #1405, slice 1405b, TDD red).

run_detail lists the on-demand artifacts that exist (task-contract.json, mapper-context.json), so the page reads only
files the run has written and never asks for a missing one. Symlinks and directories are not listed.
'''
import json
import os
from pathlib import Path

import pytest

from simplicio_loop.dashboard import runs


def _run(tmp_path):
    run_dir = tmp_path / 'repo' / '.simplicio-loop' / 'loop-runs' / 'run-a1'
    run_dir.mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': 'run-a1', 'status': 'running', 'phase': 'intake'}), encoding='utf-8')
    return run_dir


def test_the_run_detail_carries_an_artifacts_list(tmp_path):
    detail = runs.run_detail(_run(tmp_path))
    assert detail['artifacts'] == []


def test_a_written_contract_and_context_are_listed_in_their_order(tmp_path):
    run_dir = _run(tmp_path)
    (run_dir / 'mapper-context.json').write_text('{}', encoding='utf-8')
    (run_dir / 'task-contract.json').write_text('{}', encoding='utf-8')
    assert runs.run_detail(run_dir)['artifacts'] == ['task-contract.json', 'mapper-context.json']


def test_a_directory_with_an_artifact_name_is_not_listed(tmp_path):
    run_dir = _run(tmp_path)
    (run_dir / 'task-contract.json').mkdir()
    assert runs.run_detail(run_dir)['artifacts'] == []


@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='symlinks are not available')
def test_a_symlinked_artifact_is_not_listed(tmp_path):
    run_dir = _run(tmp_path)
    outside = tmp_path / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    os.symlink(outside, run_dir / 'mapper-context.json')
    assert runs.run_detail(run_dir)['artifacts'] == []


def test_listing_never_reads_the_artifact_contents(tmp_path):
    run_dir = _run(tmp_path)
    (run_dir / 'task-contract.json').write_text('not json at all', encoding='utf-8')
    assert runs.run_detail(run_dir)['artifacts'] == ['task-contract.json']
