'''Pure reducer unit tests for the Simplicio Live quality panel (TDD: written red before quality.js exists).

quality.js is a pure ES module with no DOM, no clock and no network. It runs through node with a small driver
script passed as an argument, so this file needs no fixture. The driver deep-freezes every state and event it
passes in: a reducer that mutates its input throws in strict mode, and the run fails.

JSON cannot carry NaN or Infinity, so those values travel as the marker strings below and the driver revives them.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'quality.js'
MODULE_URL = MODULE.as_uri()
NAN = '__NaN__'
INF = '__Inf__'
NEG_INF = '__-Inf__'
ABSENT = object()
MINUS = '−'
NO_PRODUCER = 'sem produtor no fluxo atual'
NO_IDS = 'sem ids por teste: o produtor emite contagens, não identidade de teste'
UNVERIFIED = {'state': 'UNVERIFIED', 'reason': NO_PRODUCER}
KEYS = ['tests', 'lint', 'coverageTrend', 'diff']
DRIVER = '''
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const revive = (key, value) => {
  if (value === '__NaN__') return NaN;
  if (value === '__Inf__') return Infinity;
  if (value === '__-Inf__') return -Infinity;
  return value;
};
const input = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}', revive);
const quality = await import(input.moduleUrl);
const { initialQuality, reduceQuality } = quality;
const { selectFlaky } = await import(input.flakyUrl);
const selectQuality = (state) => ({ ...quality.selectQuality(state), flaky: selectFlaky(state) });

function deepFreeze(value) {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value)) deepFreeze(value[key]);
  }
  return value;
}

if (input.mode === 'exports') {
  const initial = initialQuality();
  process.stdout.write(JSON.stringify({
    QUALITY_CAP: quality.QUALITY_CAP,
    COVERAGE_TARGET: quality.COVERAGE_TARGET,
    names: Object.keys(quality).sort(),
    initial,
    empty: selectQuality(initial),
  }) + '\\n');
} else if (input.mode === 'purity') {
  const first = input.steps[0];
  const base = reduceQuality(initialQuality(), first.event, first.current);
  const before = JSON.stringify(base);
  deepFreeze(base);
  const second = input.steps[1];
  const once = reduceQuality(base, second.event, second.current);
  const again = reduceQuality(base, second.event, second.current);
  process.stdout.write(JSON.stringify({
    unchanged: JSON.stringify(base) === before,
    repeatable: JSON.stringify(once) === JSON.stringify(again),
    changed: once !== base,
  }) + '\\n');
} else {
  let state = initialQuality();
  const steps = [];
  for (const step of input.steps) {
    deepFreeze(state);
    deepFreeze(step.event);
    const next = reduceQuality(state, step.event, step.current);
    steps.push({ same: next === state, selection: selectQuality(next) });
    state = next;
  }
  process.stdout.write(JSON.stringify({ steps, state, selection: selectQuality(state) }) + '\\n');
}
'''


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text=''):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(mode, **fields):
    payload = dict(fields, mode=mode, moduleUrl=MODULE_URL, flakyUrl=MODULE_URL.replace('live/quality.js', 'quality-flaky.js'))
    return _run_node(['--input-type=module', '-e', DRIVER], json.dumps(payload))


def _steps(steps):
    return _drive('steps', steps=steps)


def _selection(steps):
    return _steps(steps)['selection']


def _apply(base, changes):
    payload = dict(base)
    for key, value in changes.items():
        if value is ABSENT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _tests(**changes):
    base = {'passed': 12, 'failed': 2, 'skipped': 1, 'errors': 0, 'total': 15, 'duration_s': 3.4,
            'status': 'FAIL', 'tool': 'pytest'}
    return _apply(base, changes)


def _lint(**changes):
    return _apply({'errors': 0, 'warnings': 0, 'by_rule': {}, 'tool': 'ruff', 'status': 'PASS'}, changes)


def _coverage(**changes):
    return _apply({'percent': 85.0, 'scope': 'dashboard', 'tool': 'pytest-cov'}, changes)


def _diff(**changes):
    return _apply({'step': 'diff', 'files': ['a.py'], 'files_total': 1, 'added': 1, 'deleted': 0}, changes)


def _step(kind, payload=ABSENT, iteration=ABSENT, current=None):
    event = {'kind': kind, 'payload': {} if payload is ABSENT else payload}
    if iteration is not ABSENT:
        event['iteration'] = iteration
    return {'event': event, 'current': current}


@pytest.fixture(scope='module')
def exports():
    return _drive('exports')


# Exports and the empty state.

def test_quality_cap_is_200(exports):
    assert exports['QUALITY_CAP'] == 200


def test_coverage_target_is_85(exports):
    assert exports['COVERAGE_TARGET'] == 85


def test_the_module_exports_the_constants_and_the_three_functions(exports):
    assert {'QUALITY_CAP', 'COVERAGE_TARGET', 'initialQuality', 'reduceQuality', 'selectQuality'} <= set(
        exports['names'])


def test_initial_quality_is_an_empty_by_iteration_map_and_order(exports):
    assert exports['initial'] == {'byIteration': {}, 'order': []}


def test_no_data_selects_unverified_with_the_exact_reason_for_every_key(exports):
    assert {key: exports['empty'][key] for key in KEYS} == {key: UNVERIFIED for key in KEYS}


def test_no_data_selects_flaky_unverified_for_lack_of_test_ids(exports):
    assert exports['empty']['flaky'] == {'state': 'UNVERIFIED', 'reason': NO_IDS}


# Tests.

def test_tests_fail_with_the_reason_counts_and_duration_on_failure():
    tests = _selection([_step('test_result', _tests(), iteration=4)])['tests']
    assert tests['state'] == 'FAIL'
    assert tests['reason'] == '12 passaram, 2 falharam, 1 ignorado em 3,4 s (iteração 4)'
    assert tests['counts'] == {'passed': 12, 'failed': 2, 'skipped': 1, 'errors': 0, 'total': 15}
    assert tests['durationS'] == 3.4
    assert tests['iteration'] == 4
    assert tests['series'] == [{'iteration': 4, 'failed': 2}]
    assert tests['deltaFailed'] is None


def test_tests_pass_when_nothing_failed_or_errored():
    tests = _selection([_step('test_result', _tests(passed=5, failed=0, skipped=0, duration_s=1.0),
                              iteration=1)])['tests']
    assert (tests['state'], tests['reason']) == ('PASS', '5 passaram, 0 falharam, 0 ignorados em 1,0 s (iteração 1)')


def test_errors_alone_fail_the_tests_and_are_named_in_the_reason():
    tests = _selection([_step('test_result', _tests(passed=3, failed=0, errors=1, skipped=0, duration_s=2.0),
                              iteration=1)])['tests']
    assert (tests['state'], tests['reason']) == ('FAIL', '3 passaram, 0 falharam, 1 erro, 0 ignorados em 2,0 s (iteração 1)')


def test_tests_reason_uses_the_singular_forms_for_one():
    tests = _selection([_step('test_result', _tests(passed=1, failed=1, errors=0, skipped=1, duration_s=0.5),
                              iteration=1)])['tests']
    assert tests['reason'] == '1 passou, 1 falhou, 1 ignorado em 0,5 s (iteração 1)'


def test_an_invalid_duration_is_dropped_from_the_reason_only():
    tests = _selection([_step('test_result', _tests(duration_s=NAN), iteration=4)])['tests']
    assert (tests['state'], tests['durationS']) == ('FAIL', None)
    assert tests['reason'] == '12 passaram, 2 falharam, 1 ignorado (iteração 4)'


def test_an_invalid_skipped_count_is_dropped_from_the_counts_and_the_reason():
    tests = _selection([_step('test_result', _tests(skipped=INF), iteration=4)])['tests']
    assert tests['counts']['skipped'] is None
    assert tests['reason'] == '12 passaram, 2 falharam em 3,4 s (iteração 4)'


@pytest.mark.parametrize('field, value', [
    ('passed', ABSENT), ('failed', NAN), ('failed', INF), ('passed', -1),
    ('errors', 2.5), ('errors', '2'), ('failed', None),
])
def test_a_test_result_with_a_missing_or_bad_required_count_is_ignored_whole(field, value):
    good = _step('test_result', _tests(passed=5, failed=0, errors=0, skipped=0, duration_s=1.0), iteration=1)
    bad = _step('test_result', _tests(**{field: value}), iteration=2)
    result = _steps([good, bad])
    assert result['steps'][1]['same'] is True
    assert (result['selection']['tests']['iteration'], result['selection']['tests']['state']) == (1, 'PASS')


def test_the_last_test_result_of_an_iteration_wins():
    steps = [_step('test_result', _tests(failed=5, errors=0), iteration=4),
             _step('test_result', _tests(passed=9, failed=0, skipped=0, duration_s=2.0), iteration=4)]
    tests = _selection(steps)['tests']
    assert (tests['state'], tests['counts']['passed'], tests['counts']['failed']) == ('PASS', 9, 0)
    assert tests['reason'] == '9 passaram, 0 falharam, 0 ignorados em 2,0 s (iteração 4)'


def test_delta_failed_compares_failed_plus_errors_with_the_previous_iteration_that_had_tests():
    steps = [_step('test_result', _tests(failed=1, errors=0), iteration=3),
             _step('test_result', _tests(failed=2, errors=1), iteration=4)]
    assert _selection(steps)['tests']['deltaFailed'] == 2


def test_series_lists_every_iteration_with_tests_and_skips_the_others():
    steps = [_step('test_result', _tests(failed=0), iteration=2),
             _step('lint_result', _lint(), iteration=3),
             _step('test_result', _tests(failed=1, errors=0), iteration=5)]
    tests = _selection(steps)['tests']
    assert tests['series'] == [{'iteration': 2, 'failed': 0}, {'iteration': 5, 'failed': 1}]
    assert tests['deltaFailed'] == 1


def test_each_key_uses_its_own_latest_iteration_with_data():
    steps = [_step('test_result', _tests(passed=7, failed=0), iteration=2),
             _step('lint_result', _lint(errors=1), iteration=5)]
    selection = _selection(steps)
    assert selection['tests']['iteration'] == 2
    assert selection['lint']['iteration'] == 5


# Lint.

def test_lint_fails_on_errors_and_counts_new_and_resolved_rules_against_the_previous_lint():
    steps = [_step('lint_result', _lint(errors=0, warnings=0, by_rule={'A': 2, 'B': 0}), iteration=3),
             _step('lint_result', _lint(errors=3, warnings=1, by_rule={'A': 0, 'C': 1}), iteration=4)]
    lint = _selection(steps)['lint']
    assert (lint['state'], lint['reason']) == ('FAIL', '3 erros, 1 aviso (iteração 4); novos 1, resolvidos 2')
    assert (lint['newCount'], lint['resolvedCount']) == (1, 2)


def test_lint_without_a_previous_lint_has_no_comparison_clause():
    lint = _selection([_step('lint_result', _lint(errors=0, warnings=2, by_rule={'A': 1}), iteration=1)])['lint']
    assert (lint['state'], lint['reason']) == ('PASS', '0 erros, 2 avisos (iteração 1)')
    assert (lint['newCount'], lint['resolvedCount']) == (None, None)


def test_lint_extras_carry_counts_by_rule_and_the_error_and_warning_series():
    steps = [_step('lint_result', _lint(errors=0, warnings=0, by_rule={'A': 2}), iteration=3),
             _step('lint_result', _lint(errors=3, warnings=1, by_rule={'C': 1}), iteration=4)]
    lint = _selection(steps)['lint']
    assert lint['byRule'] == {'C': 1}
    assert (lint['errors'], lint['warnings'], lint['iteration']) == (3, 1, 4)
    assert lint['series'] == [{'iteration': 3, 'errors': 0, 'warnings': 0},
                              {'iteration': 4, 'errors': 3, 'warnings': 1}]


def test_a_by_rule_that_is_not_an_object_drops_the_rule_comparison():
    steps = [_step('lint_result', _lint(by_rule={'A': 1}), iteration=3),
             _step('lint_result', _lint(by_rule='E501'), iteration=4)]
    lint = _selection(steps)['lint']
    assert (lint['byRule'], lint['newCount'], lint['resolvedCount']) == (None, None, None)
    assert lint['reason'] == '0 erros, 0 avisos (iteração 4)'


def test_non_finite_or_negative_rule_counts_are_dropped_one_by_one():
    lint = _selection([_step('lint_result', _lint(by_rule={'A': 1, 'B': NAN, 'C': -1, 'D': 2.5}),
                             iteration=1)])['lint']
    assert lint['byRule'] == {'A': 1}


def test_the_rule_comparison_uses_the_previous_lint_that_has_rules():
    steps = [_step('lint_result', _lint(by_rule={'A': 5}), iteration=2),
             _step('lint_result', _lint(by_rule='x'), iteration=3),
             _step('lint_result', _lint(by_rule={'A': 4}), iteration=4)]
    lint = _selection(steps)['lint']
    assert (lint['newCount'], lint['resolvedCount']) == (0, 1)
    assert lint['reason'] == '0 erros, 0 avisos (iteração 4); novos 0, resolvidos 1'


@pytest.mark.parametrize('changes', [{'errors': NAN}, {'warnings': '1'}, {'errors': ABSENT}])
def test_a_lint_result_with_a_bad_required_count_is_ignored_whole(changes):
    result = _steps([_step('lint_result', _lint(**changes), iteration=2)])
    assert result['steps'][0]['same'] is True
    assert result['selection']['lint'] == UNVERIFIED


# Coverage.

def test_coverage_at_the_target_passes():
    cov = _selection([_step('coverage_result', _coverage(percent=85), iteration=1)])['coverageTrend']
    assert (cov['state'], cov['reason']) == ('PASS', 'cobertura 85,0% de 85% (iteração 1)')


def test_coverage_below_the_target_fails_with_the_point_delta():
    steps = [_step('coverage_result', _coverage(percent=81.3), iteration=3),
             _step('coverage_result', _coverage(percent=82.5), iteration=4)]
    cov = _selection(steps)['coverageTrend']
    assert (cov['state'], cov['reason']) == ('FAIL', 'cobertura 82,5% de 85% (iteração 4), +1,2 pp')


def test_a_coverage_drop_uses_the_minus_sign():
    steps = [_step('coverage_result', _coverage(percent=90), iteration=4),
             _step('coverage_result', _coverage(percent=88.4), iteration=5)]
    cov = _selection(steps)['coverageTrend']
    assert (cov['state'], cov['reason']) == ('PASS', 'cobertura 88,4% de 85% (iteração 5), ' + MINUS + '1,6 pp')


def test_coverage_extras_carry_percent_target_and_series(exports):
    steps = [_step('coverage_result', _coverage(percent=81.3), iteration=3),
             _step('coverage_result', _coverage(percent=82.5), iteration=4)]
    cov = _selection(steps)['coverageTrend']
    assert (cov['percent'], cov['target'], cov['iteration']) == (82.5, exports['COVERAGE_TARGET'], 4)
    assert cov['series'] == [{'iteration': 3, 'percent': 81.3}, {'iteration': 4, 'percent': 82.5}]


@pytest.mark.parametrize('value', [NAN, INF, NEG_INF, ABSENT, None, '80', 150, -1])
def test_an_invalid_percent_is_ignored(value):
    result = _steps([_step('coverage_result', _coverage(percent=value), iteration=2)])
    assert result['steps'][0]['same'] is True
    assert result['selection']['coverageTrend'] == UNVERIFIED


# Diff.

def test_diff_reports_files_and_lines_with_the_pt_br_reason():
    step = _step('apply_result', _diff(files=['a.py', 'b.py', 'c.py'], files_total=3, added=40, deleted=12),
                 iteration=4)
    diff = _selection([step])['diff']
    assert (diff['state'], diff['reason']) == ('PASS', '3 arquivos, +40 ' + MINUS + '12 (iteração 4)')
    assert diff['files'] == ['a.py', 'b.py', 'c.py']
    assert (diff['filesTotal'], diff['added'], diff['deleted'], diff['iteration']) == (3, 40, 12, 4)


def test_diff_reason_uses_the_singular_for_one_file():
    diff = _selection([_step('apply_result', _diff(files=['a.py'], files_total=1, added=1, deleted=0),
                             iteration=1)])['diff']
    assert diff['reason'] == '1 arquivo, +1 ' + MINUS + '0 (iteração 1)'


def test_diff_events_in_one_iteration_sum_the_lines_and_union_the_files():
    steps = [_step('apply_result', _diff(files=['a.py', 'b.py'], files_total=2, added=10, deleted=2), iteration=4),
             _step('apply_result', _diff(files=['b.py', 'c.py'], files_total=2, added=5, deleted=1), iteration=4)]
    diff = _selection(steps)['diff']
    assert diff['files'] == ['a.py', 'b.py', 'c.py']
    assert (diff['added'], diff['deleted'], diff['filesTotal']) == (15, 3, 3)


def test_the_files_list_is_capped_at_200_in_first_seen_order():
    first = ['f%d.py' % n for n in range(150)]
    second = ['g%d.py' % n for n in range(150)]
    steps = [_step('apply_result', _diff(files=first, files_total=150, added=1, deleted=0), iteration=4),
             _step('apply_result', _diff(files=second, files_total=150, added=1, deleted=0), iteration=4)]
    diff = _selection(steps)['diff']
    assert len(diff['files']) == 200
    assert diff['files'][:2] == ['f0.py', 'f1.py']
    assert diff['files'][-1] == 'g49.py'
    assert (diff['added'], diff['filesTotal']) == (2, 200)


def test_diff_cumulative_sums_every_iteration_and_vs_previous_is_against_the_earlier_diff():
    steps = [_step('apply_result', _diff(files=['a'], files_total=1, added=10, deleted=2), iteration=1),
             _step('apply_result', _diff(files=['b', 'c'], files_total=2, added=30, deleted=0), iteration=2),
             _step('lint_result', _lint(), iteration=3)]
    diff = _selection(steps)['diff']
    assert diff['iteration'] == 2
    assert diff['cumulative'] == {'added': 40, 'deleted': 2, 'files': 3}
    assert diff['vsPrevious'] == {'added': 20, 'deleted': -2}


def test_diff_vs_previous_is_null_without_an_earlier_diff():
    diff = _selection([_step('apply_result', _diff(files=['a'], files_total=1, added=3, deleted=1),
                             iteration=2)])['diff']
    assert diff['vsPrevious'] is None
    assert diff['cumulative'] == {'added': 3, 'deleted': 1, 'files': 1}


def test_non_string_file_names_are_dropped_and_the_total_is_kept():
    diff = _selection([_step('apply_result', _diff(files=['a.py', 3, None], files_total=2, added=1, deleted=0),
                             iteration=1)])['diff']
    assert diff['files'] == ['a.py']
    assert diff['filesTotal'] == 2


@pytest.mark.parametrize('changes', [
    {'step': 'commit'}, {'added': ABSENT}, {'deleted': NAN}, {'files_total': '3'},
    {'files': 'a.py'}, {'files_total': ABSENT},
])
def test_an_apply_result_that_is_not_a_valid_diff_is_ignored(changes):
    result = _steps([_step('apply_result', _diff(**changes), iteration=4)])
    assert result['steps'][0]['same'] is True
    assert result['selection']['diff'] == UNVERIFIED


# Iteration resolution.

def test_an_event_without_an_iteration_belongs_to_the_current_iteration():
    assert _selection([_step('test_result', _tests(), current=7)])['tests']['iteration'] == 7


def test_an_explicit_iteration_wins_over_the_current_one():
    assert _selection([_step('test_result', _tests(), iteration=3, current=7)])['tests']['iteration'] == 3


@pytest.mark.parametrize('iteration', ['4', 4.5, NAN])
def test_a_non_integer_iteration_falls_back_to_the_current_one(iteration):
    assert _selection([_step('test_result', _tests(), iteration=iteration, current=7)])['tests']['iteration'] == 7


@pytest.mark.parametrize('current', [None, '7', 2.5])
def test_an_event_with_no_usable_iteration_is_ignored(current):
    result = _steps([_step('test_result', _tests(), current=current)])
    assert result['steps'][0]['same'] is True
    assert result['selection']['tests'] == UNVERIFIED


def test_an_unknown_kind_is_ignored():
    result = _steps([_step('gate_evaluated', _tests(), iteration=1)])
    assert result['steps'][0]['same'] is True
    assert {key: result['selection'][key] for key in KEYS} == {key: UNVERIFIED for key in KEYS}
    assert result['selection']['flaky'] == {'state': 'UNVERIFIED', 'reason': NO_IDS}


def test_a_null_event_or_a_null_payload_is_ignored():
    steps = [{'event': None, 'current': 1},
             {'event': {'kind': 'test_result', 'payload': None, 'iteration': 1}, 'current': 1}]
    assert [step['same'] for step in _steps(steps)['steps']] == [True, True]


# Cap.

def test_only_the_newest_200_iterations_are_kept_in_ascending_order():
    steps = [_step('test_result', _tests(failed=0), iteration=n) for n in range(1, 206)]
    result = _steps(steps)
    assert result['state']['order'][:1] == [6]
    assert len(result['state']['order']) == 200
    assert len(result['state']['byIteration']) == 200
    assert [point['iteration'] for point in result['selection']['tests']['series']] == list(range(6, 206))


def test_an_iteration_older_than_the_kept_window_is_dropped_and_leaves_the_state_unchanged():
    steps = [_step('test_result', _tests(failed=0), iteration=n) for n in range(205, 5, -1)]
    steps.append(_step('test_result', _tests(failed=0), iteration=5))
    result = _steps(steps)
    assert result['steps'][-1]['same'] is True
    assert result['state']['order'][:1] == [6]


def test_the_cumulative_diff_counts_only_the_kept_iterations():
    steps = [_step('apply_result', _diff(files=[], files_total=0, added=1, deleted=0), iteration=n)
             for n in range(1, 202)]
    assert _selection(steps)['diff']['cumulative'] == {'added': 200, 'deleted': 0, 'files': 0}


# Purity.

def test_the_reducer_does_not_mutate_its_state_or_its_events():
    steps = [_step('test_result', _tests(), iteration=1),
             _step('lint_result', _lint(by_rule={'A': 1}), iteration=1),
             _step('coverage_result', _coverage(percent=80), iteration=1),
             _step('apply_result', _diff(), iteration=1),
             _step('test_result', _tests(failed=0), iteration=2)]
    result = _steps(steps)
    assert result['selection']['tests']['state'] == 'PASS'


def test_the_same_input_gives_the_same_output_and_leaves_the_input_unchanged():
    result = _drive('purity', steps=[_step('test_result', _tests(), iteration=1),
                                     _step('lint_result', _lint(), iteration=1)])
    assert result == {'unchanged': True, 'repeatable': True, 'changed': True}


# Flaky: a test id that flips between iterations while the iteration it flips in has no code change.

TEST_A = 'tests/test_a.py::test_one'
TEST_B = 'tests/test_a.py::test_two'


def _ids_step(iteration, failed_ids, current=None):
    return _step('test_result', _tests(failed_ids=failed_ids), iteration=iteration, current=current)


def _diff_step(iteration, **changes):
    return _step('apply_result', _diff(**changes), iteration=iteration)


@pytest.mark.parametrize('diff_steps', [[], [_diff_step(3, files=[], files_total=0, added=0, deleted=0)]],
                         ids=['no-diff-record', 'empty-diff-record'])
def test_a_test_that_fails_then_passes_with_no_code_change_is_flaky(diff_steps):
    steps = [_ids_step(2, [TEST_A]), _ids_step(3, [])] + diff_steps
    flaky = _selection(steps)['flaky']
    assert flaky['state'] == 'FAIL'
    assert flaky['ids'] == [{'id': TEST_A, 'flips': 1}]
    assert flaky['reason'] == '1 teste instável: ' + TEST_A + ' (1 virada)'


def test_the_same_flip_with_a_code_change_in_the_next_iteration_is_not_flaky():
    steps = [_ids_step(2, [TEST_A]), _ids_step(3, []), _diff_step(3, files=['a.py'], files_total=1, added=5,
                                                                 deleted=0)]
    flaky = _selection(steps)['flaky']
    assert (flaky['state'], flaky['ids']) == ('PASS', [])


def test_a_code_change_only_in_the_previous_iteration_does_not_excuse_the_flip():
    steps = [_ids_step(2, [TEST_A]), _diff_step(2, files=['a.py'], files_total=1, added=5, deleted=0),
             _ids_step(3, [])]
    flaky = _selection(steps)['flaky']
    assert flaky['ids'] == [{'id': TEST_A, 'flips': 1}]


def test_an_alternation_fail_pass_fail_with_no_diff_counts_two_flips():
    steps = [_ids_step(1, [TEST_A]), _ids_step(2, []), _ids_step(3, [TEST_A])]
    flaky = _selection(steps)['flaky']
    assert flaky['state'] == 'FAIL'
    assert flaky['ids'] == [{'id': TEST_A, 'flips': 2}]
    assert flaky['reason'] == '1 teste instável: ' + TEST_A + ' (2 viradas)'


def test_ids_are_ordered_by_flip_count_and_the_reason_lists_them_in_that_order():
    steps = [_ids_step(1, [TEST_B]), _ids_step(2, []), _ids_step(3, [TEST_A]), _ids_step(4, [])]
    flaky = _selection(steps)['flaky']
    assert flaky['ids'] == [{'id': TEST_A, 'flips': 2}, {'id': TEST_B, 'flips': 1}]
    assert flaky['reason'] == ('2 testes instáveis: ' + TEST_A + ' (2 viradas), ' + TEST_B + ' (1 virada)')


def test_ids_that_stay_failing_or_stay_passing_are_not_flaky():
    steps = [_ids_step(1, [TEST_A]), _ids_step(2, [TEST_A]), _ids_step(3, [TEST_A])]
    flaky = _selection(steps)['flaky']
    assert (flaky['state'], flaky['ids']) == ('PASS', [])
    assert flaky['reason'] == 'nenhum teste instável (ids observados em 3 iterações)'


def test_a_single_iteration_with_ids_has_nothing_to_compare_and_is_unverified():
    flaky = _selection([_ids_step(1, [TEST_A])])['flaky']
    assert flaky == {'state': 'UNVERIFIED', 'reason': NO_IDS}


def test_a_test_result_without_failed_ids_is_unverified_for_flakiness():
    flaky = _selection([_step('test_result', _tests(failed_ids=ABSENT), iteration=1)])['flaky']
    assert flaky == {'state': 'UNVERIFIED', 'reason': NO_IDS}


def test_an_empty_failed_ids_list_is_an_identity_that_nothing_failed():
    steps = [_ids_step(1, []), _ids_step(2, [TEST_A]), _ids_step(3, [])]
    flaky = _selection(steps)['flaky']
    assert flaky['ids'] == [{'id': TEST_A, 'flips': 2}]


@pytest.mark.parametrize('value', ['tests/a.py::t', 5, None, {'x': 1}, ['a', 3], [None], [['a']]])
def test_bad_failed_ids_are_ignored_and_the_test_counts_still_count(value):
    steps = [_ids_step(1, [TEST_A]), _step('test_result', _tests(failed_ids=value, failed=2), iteration=2),
             _ids_step(3, [])]
    result = _steps(steps)
    assert result['selection']['tests']['iteration'] == 3
    assert result['selection']['flaky']['ids'] == [{'id': TEST_A, 'flips': 1}]


def test_bad_failed_ids_alone_leave_flaky_unverified():
    flaky = _selection([_step('test_result', _tests(failed_ids='a'), iteration=1)])['flaky']
    assert flaky == {'state': 'UNVERIFIED', 'reason': NO_IDS}


def test_failed_ids_keep_at_most_100_entries():
    first = ['t%d' % n for n in range(150)]
    steps = [_ids_step(1, first), _ids_step(2, [])]
    flaky = _selection(steps)['flaky']
    assert flaky['reason'].startswith('100 testes instáveis: ')


def test_the_flaky_ids_list_is_capped_at_20_in_first_flip_order_on_ties():
    first = ['t%d' % n for n in range(40)]
    flaky = _selection([_ids_step(1, first), _ids_step(2, [])])['flaky']
    assert len(flaky['ids']) == 20
    assert flaky['ids'][:2] == [{'id': 't0', 'flips': 1}, {'id': 't1', 'flips': 1}]


# Module shape.

def test_the_module_has_no_imports_dom_or_clock_access():
    text = MODULE.read_text(encoding='utf-8')
    assert not re.search(r'^\s*import\s', text, re.M)
    assert not re.search(r'\b(document|window|Date|performance|setTimeout|setInterval|console)\b', text)


def test_the_module_passes_node_check():
    proc = subprocess.run([_node(), '--check', str(MODULE)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
