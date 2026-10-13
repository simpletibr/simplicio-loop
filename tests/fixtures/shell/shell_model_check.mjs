// Checks the pure shell model: routes, task and inbox tabs, decisions and Painel numbers.
// Run by tests/test_dashboard_shell_static.py.
import assert from 'node:assert/strict';
import { countInbox, countTasks, decisions, filterInbox, filterTasks, overview, runHref, taskGroup, viewFromHash } from '../../../simplicio_loop/dashboard/static/shell/shell-model.js';

assert.equal(viewFromHash('#painel', true), 'painel');
assert.equal(viewFromHash('#decisoes', false), 'decisoes');
assert.equal(viewFromHash('', true), 'tarefa', 'a run in the URL opens the task view');
assert.equal(viewFromHash('', false), 'painel', 'no run and no hash opens the Painel');
assert.equal(viewFromHash('#nope', false), 'painel', 'an unknown hash falls back to the default view');

const now = Date.parse('2026-10-13T12:00:00Z');
const day = 24 * 60 * 60 * 1000;
const runs = [
  { run_id: 'a', status: 'RUNNING', updated_at: '2026-10-13T11:00:00Z' },
  { run_id: 'b', status: 'QUEUED', updated_at: '2026-10-01T00:00:00Z' },
  { run_id: 'c', status: 'PASS', updated_at: '2026-10-13T08:00:00Z' },
  { run_id: 'd', status: 'FAIL', updated_at: new Date(now - 3 * day).toISOString() },
  { run_id: 'e', status: 'BLOCKED', updated_at: '2026-10-12T20:00:00Z' },
  { run_id: 'f', status: 'CANCELLED', updated_at: '2026-09-01T00:00:00Z' },
  null,
];

assert.equal(taskGroup('RUNNING'), 'ativas');
assert.equal(taskGroup('queued'), 'backlog');
assert.equal(taskGroup('PASS'), 'concluidas');
assert.equal(taskGroup('CANCELLED'), 'concluidas', 'a cancelled run is terminal, not active');

assert.deepEqual(filterTasks(runs, 'ativas').map((r) => r.run_id), ['a']);
assert.deepEqual(filterTasks(runs, 'backlog').map((r) => r.run_id), ['b']);
assert.deepEqual(filterTasks(runs, 'concluidas').map((r) => r.run_id), ['c', 'd', 'e', 'f']);
assert.equal(filterTasks(runs, 'todas').length, 6, 'the null row is dropped');
assert.deepEqual(countTasks(runs), { ativas: 1, backlog: 1, concluidas: 4, todas: 6 });

assert.deepEqual(filterInbox(runs, 'todas', now).map((r) => r.run_id), ['d', 'e'], 'attention queue: failed and blocked');
assert.deepEqual(filterInbox(runs, 'bloqueadas', now).map((r) => r.run_id), ['e']);
assert.deepEqual(filterInbox(runs, 'falhas', now).map((r) => r.run_id), ['d']);
assert.deepEqual(filterInbox(runs, 'recentes', now).map((r) => r.run_id), ['a', 'c', 'e'], 'updated in the last 24 hours');
assert.deepEqual(countInbox(runs, now), { todas: 2, recentes: 3, bloqueadas: 1, falhas: 1 });

assert.deepEqual(decisions(runs).map((r) => r.run_id), ['e'], 'a decision is a blocked run');
assert.deepEqual(overview(runs), { ativas: 1, falhas: 2, concluidas: 4, total: 6 });
assert.deepEqual(overview(null), { ativas: 0, falhas: 0, concluidas: 0, total: 0 });

assert.equal(runHref('/', '?t=tok&run=old', 'new-run'), '/?t=tok&run=new-run#tarefa', 'keeps the token, swaps the run');
console.log('shell model: ok');
