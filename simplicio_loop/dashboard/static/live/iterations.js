// Simplicio Live iteration timeline and convergence (issue #1403, slice 1403a). Pure: no DOM, no network, no clock.
// Time enters only as the event stamp (a number or null) and nowMs, both passed in by reducer.js.
export const ITERATION_CAP = 200;
const OUTCOME_STATE = { pass: 'PASS', blocked: 'BLOCKED', refeed: 'UNVERIFIED' };
const FAILING_GATES = ['FAIL', 'BLOCKED'];

export function initialIterations() {
  return { byNumber: {}, order: [], current: null, pendingStart: null };
}

function integerOrNull(value) {
  return Number.isInteger(value) ? value : null;
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function textOrNull(value) {
  return typeof value === 'string' ? value : null;
}

// The earlier of two stamps. A null stamp is unknown and never wins.
function earliest(first, second) {
  if (first === null) return second;
  if (second === null) return first;
  return Math.min(first, second);
}

function blankRow(number) {
  return {
    number,
    startedAt: null,
    finished: false,
    endedAt: null,
    outcome: null,
    stall: null,
    retries: [],
    gatesFailing: [],
    gatesUnverified: [],
  };
}

function rowOf(state, number) {
  return Object.hasOwn(state.byNumber, number) ? state.byNumber[number] : blankRow(number);
}

// Stores the row and keeps only the newest ITERATION_CAP iterations, in ascending order.
function withRow(state, row) {
  const grown = Object.hasOwn(state.byNumber, row.number) ? state.order.slice() : state.order.concat([row.number]);
  const order = grown.sort((a, b) => a - b).slice(-ITERATION_CAP);
  const byNumber = {};
  for (const number of order) byNumber[number] = number === row.number ? row : state.byNumber[number];
  return { ...state, byNumber, order };
}

// Gate names by state, read from the reducer gate map: failing (FAIL or BLOCKED) and unverified (never evaluated or UNVERIFIED).
function gateLists(gates) {
  const failing = [];
  const unverified = [];
  for (const name of Object.keys(gates)) {
    const entry = gates[name];
    if (!entry || entry.state === 'UNVERIFIED') unverified.push(name);
    else if (FAILING_GATES.includes(entry.state)) failing.push(name);
  }
  return { failing, unverified };
}

// The first start of an iteration is the earliest of its own stamp and a pending start, which it then consumes.
// A finish passes a null stamp: it can claim a pending start but never sets one.
function claimStart(state, row, stamp) {
  if (row.startedAt !== null) {
    return { row: { ...row, startedAt: earliest(row.startedAt, stamp) }, pending: state.pendingStart };
  }
  return { row: { ...row, startedAt: earliest(stamp, state.pendingStart) }, pending: null };
}

function openIteration(state, number, stamp) {
  const claimed = claimStart(state, rowOf(state, number), stamp);
  return withRow({ ...state, pendingStart: claimed.pending }, claimed.row);
}

function finishIteration(state, number, stamp, payload, gates) {
  const claimed = claimStart(state, rowOf(state, number), null);
  const lists = gateLists(gates);
  const outcome = Object.hasOwn(OUTCOME_STATE, payload.outcome) ? OUTCOME_STATE[payload.outcome] : 'UNVERIFIED';
  const row = {
    ...claimed.row,
    finished: true,
    endedAt: stamp,
    outcome,
    gatesFailing: lists.failing,
    gatesUnverified: lists.unverified,
  };
  return withRow({ ...state, pendingStart: claimed.pending }, row);
}

function stallIteration(state, number, payload) {
  const row = rowOf(state, number);
  const stall = { streak: numberOrNull(payload.streak), fingerprint: textOrNull(payload.fingerprint) };
  return withRow(state, { ...row, stall });
}

function retryIteration(state, number, payload) {
  const row = rowOf(state, number);
  const retry = { step: textOrNull(payload.step), blocker: textOrNull(payload.blocker) };
  return withRow(state, { ...row, retries: row.retries.concat([retry]) });
}

// Counts one event in the iteration timeline. An event without an integer iteration belongs to the current one.
// Before any iteration exists, an iteration_started without a number is a pending start.
export function applyIteration(state, event, stamp, payload, gates) {
  const explicit = integerOrNull(event.iteration);
  const base = explicit === null ? state : { ...state, current: explicit };
  const current = base.current;
  if (event.kind === 'iteration_started') {
    if (current === null) return { ...base, pendingStart: earliest(base.pendingStart, stamp) };
    return openIteration(base, current, stamp);
  }
  if (current === null) return base;
  if (event.kind === 'iteration_finished') return finishIteration(base, current, stamp, payload, gates);
  if (event.kind === 'stall_detected') return stallIteration(base, current, payload);
  if (event.kind === 'retry_scheduled') return retryIteration(base, current, payload);
  return base;
}

function rowView(row, now, gates) {
  const live = row.finished ? null : gateLists(gates);
  const endAt = row.finished ? row.endedAt : now;
  let verdict = null;
  if (row.stall !== null) verdict = 'STALLED';
  else if (row.finished) verdict = 'PROGRESS';
  return {
    iteration: row.number,
    state: row.finished ? row.outcome : 'RUNNING',
    startedAt: row.startedAt,
    endedAt: row.finished ? row.endedAt : null,
    durationMs: row.startedAt === null || endAt === null ? null : Math.max(0, endAt - row.startedAt),
    verdict,
    streak: row.stall === null ? null : row.stall.streak,
    fingerprint: row.stall === null ? null : row.stall.fingerprint,
    retries: row.retries.map((retry) => ({ step: retry.step, blocker: retry.blocker })),
    gatesFailing: row.finished ? row.gatesFailing.slice() : live.failing,
    gatesUnverified: row.finished ? row.gatesUnverified.slice() : live.unverified,
  };
}

// Rows for the kept iterations, ascending by number.
export function selectIterations(state, now, gates) {
  return state.order.map((number) => rowView(state.byNumber[number], now, gates));
}

// One point per finished iteration, with its gate counts at finish. An open iteration is not a point.
export function selectConvergence(rows) {
  const points = rows
    .filter((row) => row.state !== 'RUNNING')
    .map((row) => ({ iteration: row.iteration, failing: row.gatesFailing.length, unverified: row.gatesUnverified.length }));
  if (points.length > 0) return { state: 'OK', points, reason: null };
  return { state: 'UNVERIFIED', points, reason: 'nenhuma iteração finalizada para medir a convergência' };
}
