'''Unit tests for the drill-down deep links of the Simplicio Live page (issue #1405, slice 1405b, TDD red).

deeplink.js is pure: it parses and writes the URL fragment for one run. The routes are
#/run/<run>/phase/<phase>, #/run/<run>/lane/<lane>, #/run/<run>/lane/<lane>/block/<index> and #/run/<run>/logs.
Anything else, including another run id, parses to null. The module runs in node.
'''
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'deeplink.js'
RUN = 'run-q1'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


SCRIPT = '''
import fs from 'node:fs';
import { parseDeepLink, deepLinkOf } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = input.map((step) => step.op === 'parse'
  ? parseDeepLink(step.hash, step.run)
  : deepLinkOf(step.run, step.target));
process.stdout.write(JSON.stringify(out));
'''


def _run_steps(steps):
    script = SCRIPT % json.dumps(MODULE.as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(steps),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _parse(hash_text, run=RUN):
    return _run_steps([{'op': 'parse', 'hash': hash_text, 'run': run}])[0]


def _write(target, run=RUN):
    return _run_steps([{'op': 'write', 'run': run, 'target': target}])[0]


def test_the_module_exists():
    assert MODULE.is_file(), MODULE


@pytest.mark.parametrize('hash_text, expected', [
    ('#/run/run-q1/phase/executing', {'type': 'phase', 'phase': 'executing'}),
    ('#/run/run-q1/logs', {'type': 'logs'}),
    ('#/run/run-q1/lane/lane-1', {'type': 'lane', 'lane': 'lane-1'}),
    ('#/run/run-q1/lane/lane-1/block/3', {'type': 'block', 'lane': 'lane-1', 'index': 3}),
])
def test_each_route_parses_to_its_drill_target(hash_text, expected):
    assert _parse(hash_text) == expected


@pytest.mark.parametrize('hash_text', [
    '',
    '#',
    None,
    42,
    '#/run/other-run/logs',
    '#/run/run-q1',
    '#/run/run-q1/phase',
    '#/run/run-q1/phase/Executing!',
    '#/run/run-q1/phase/executing/extra',
    '#/run/run-q1/lane/..',
    '#/run/run-q1/lane/lane-1/block/-1',
    '#/run/run-q1/lane/lane-1/block/x',
    '#/run/run-q1/lane/lane-1/block',
    '#/elsewhere/run-q1/logs',
])
def test_anything_else_parses_to_null(hash_text):
    assert _parse(hash_text) is None


def test_a_run_id_outside_the_safe_set_parses_to_null():
    assert _parse('#/run/run;rm/logs', run='run;rm') is None


@pytest.mark.parametrize('target, expected', [
    ({'type': 'logs'}, '#/run/run-q1/logs'),
    ({'type': 'phase', 'phase': 'validating'}, '#/run/run-q1/phase/validating'),
    ({'type': 'lane', 'lane': 'lane-1'}, '#/run/run-q1/lane/lane-1'),
    ({'type': 'block', 'lane': 'lane-1', 'index': 0}, '#/run/run-q1/lane/lane-1/block/0'),
])
def test_each_target_writes_its_route(target, expected):
    assert _write(target) == expected


@pytest.mark.parametrize('target', [
    {'type': 'phase', 'phase': 'bad phase'},
    {'type': 'block', 'lane': 'lane-1', 'index': -1},
    {'type': 'block', 'lane': 'lane/1', 'index': 0},
    {'type': 'unknown'},
    None,
])
def test_an_unsafe_target_writes_null(target):
    assert _write(target) is None


def test_an_unsafe_run_id_writes_null():
    assert _write({'type': 'logs'}, run='../etc') is None


@pytest.mark.parametrize('target', [
    {'type': 'logs'},
    {'type': 'phase', 'phase': 'executing'},
    {'type': 'lane', 'lane': 'lane-1'},
    {'type': 'block', 'lane': 'lane-1', 'index': 7},
])
def test_writing_then_parsing_gives_the_same_target(target):
    link = _write(target)
    assert _parse(link) == target
