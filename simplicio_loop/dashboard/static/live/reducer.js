// Simplicio Live pipeline reducer (issue #1402). Pure: no DOM, no network, no clock.
// Time enters only through selectView(state, nowMs) and the timestamps carried by actions.
export const GATES = ['evidence', 'watcher', 'oracle', 'dod', 'quality', 'action'];
export const READY_VERDICTS = ['COMPLETE', 'DRAINED', 'VERIFIED'];
export const STALE_AFTER_MS = 45000;

const SCHEMA = 'simplicio.dashboard-event/v1';
const RAIL = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done'];
const RATE_WINDOW_MS = 60000;
const NO_EVENT = 'nenhum evento recebido';
const OUTCOME_PENDING = 'aguardando recibo de conclusão';
const COMMAND_REASON = 'nenhum comando medido nesta visão';

function emptyPhase() {
  return { entries: 0, openSince: null, closedMs: 0 };
}

// Closes an open interval at stamp, or at its own start when stamp is unknown.
function closed(phase, stamp) {
  if (phase.openSince === null) return phase;
  const end = stamp === null ? phase.openSince : stamp;
  return { entries: phase.entries, openSince: null, closedMs: phase.closedMs + Math.max(0, end - phase.openSince) };
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function gateStateOf(verdict) {
  if (verdict === 'pass') return 'PASS';
  if (verdict === 'fail') return 'FAIL';
  if (verdict === 'blocked') return 'BLOCKED';
  return 'UNVERIFIED';
}

function isReceiptReady(summary) {
  return Boolean(summary && summary.completion && summary.completion.ready === true
    && READY_VERDICTS.includes(summary.verdict));
}

export function initialState(runId) {
  const phases = {};
  for (const name of RAIL) phases[name] = emptyPhase();
  const gates = {};
  for (const name of GATES) gates[name] = null;
  return {
    runId: runId || '',
    lastSeq: 0,
    phases,
    railPhase: null,
    railAt: null,
    railReason: null,
    offRail: null,
    gates,
    last: null,
    eventTimes: [],
    lastEventAt: null,
    stall: null,
    summary: null,
    connection: 'connecting',
    lastActivity: null,
    heartbeatAt: null,
  };
}
function enterPhase(state, event, stamp, payload) {
  const phase = event.phase;
  if (!phase) return state;
  const stall = state.stall && state.stall.phase === phase ? state.stall : null;
  const reason = typeof payload.reason === 'string' ? payload.reason : null;
  if (!RAIL.includes(phase)) return { ...state, offRail: phase, stall };
  const phases = { ...state.phases };
  if (state.railPhase && state.railPhase !== phase) {
    phases[state.railPhase] = closed(phases[state.railPhase], stamp);
  }
  const previous = closed(phases[phase], stamp);
  phases[phase] = { entries: previous.entries + 1, openSince: stamp, closedMs: previous.closedMs };
  return { ...state, phases, railPhase: phase, railAt: stamp, railReason: reason, offRail: null, stall };
}

function exitPhase(state, event, stamp) {
  const phase = event.phase;
  if (!RAIL.includes(phase)) return state;
  return { ...state, phases: { ...state.phases, [phase]: closed(state.phases[phase], stamp) } };
}

function evaluateGate(state, event, stamp, payload) {
  const gate = payload.gate;
  if (!GATES.includes(gate)) return state;
  const verdict = typeof payload.verdict === 'string' ? payload.verdict.toLowerCase() : '';
  const entry = {
    state: gateStateOf(verdict),
    reason: typeof payload.message === 'string' ? payload.message : '',
    ref: Array.isArray(event.refs) && event.refs.length > 0 ? String(event.refs[0]) : null,
    at: stamp,
  };
  return { ...state, gates: { ...state.gates, [gate]: entry } };
}

function applyEvent(state, event) {
  if (!event || typeof event !== 'object') return state;
  if (typeof event.seq !== 'number' || event.seq <= state.lastSeq) return state;
  if (event.schema !== SCHEMA) return state;
  if (state.runId && event.run_id !== state.runId) return state;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const parsed = typeof event.ts === 'string' ? Date.parse(event.ts) : NaN;
  const stamp = Number.isFinite(parsed) ? parsed : null;
  const eventTimes = stamp === null ? state.eventTimes
    : state.eventTimes.filter((time) => time > stamp - RATE_WINDOW_MS).concat([stamp]);
  const next = {
    ...state,
    runId: state.runId || String(event.run_id || ''),
    lastSeq: event.seq,
    eventTimes,
    lastEventAt: stamp === null ? state.lastEventAt : stamp,
    last: { text: String(payload.message || event.kind || ''), phase: event.phase || null, at: stamp },
  };
  if (event.kind === 'phase_entered') return enterPhase(next, event, stamp, payload);
  if (event.kind === 'phase_exited') return exitPhase(next, event, stamp);
  if (event.kind === 'stall_detected') {
    return { ...next, stall: { phase: event.phase || null, streak: Number(payload.streak) || 1, at: stamp } };
  }
  if (event.kind === 'gate_evaluated') return evaluateGate(next, event, stamp, payload);
  return next;
}

export function reduce(state, action) {
  if (!action || typeof action !== 'object') return state;
  if (action.type === 'event') return applyEvent(state, action.event);
  if (action.type === 'summary') return { ...state, summary: action.summary || null };
  if (action.type === 'connection') {
    const at = numberOrNull(action.at);
    return { ...state, connection: String(action.status || 'connecting'), lastActivity: at === null ? state.lastActivity : at };
  }
  if (action.type === 'heartbeat') {
    const at = numberOrNull(action.at);
    return { ...state, heartbeatAt: at, lastActivity: at === null ? state.lastActivity : at };
  }
  return state;
}
function nextPhase(railPhase) {
  const index = RAIL.indexOf(railPhase);
  if (index < 0) return RAIL[0];
  return index + 1 < RAIL.length ? RAIL[index + 1] : '';
}

export function selectView(state, nowMs) {
  const now = Number.isFinite(nowMs) ? nowMs : 0;
  const ready = isReceiptReady(state.summary);
  const railPhase = state.railPhase;
  const index = RAIL.indexOf(railPhase);
  const phase = state.offRail || railPhase;
  let percent = index < 0 ? 0 : Math.min(99, Math.round((index / (RAIL.length - 1)) * 100));
  if (phase === 'cancelled') percent = 0;
  if (ready && railPhase === 'done') percent = 100;
  const phases = RAIL.map((name) => {
    const item = state.phases[name];
    const open = item.openSince !== null;
    let stateName = 'pending';
    if (open) stateName = 'current';
    else if (item.entries > 0) stateName = 'done';
    return {
      phase: name,
      entries: item.entries,
      state: stateName,
      elapsedMs: item.closedMs + (open ? Math.max(0, now - item.openSince) : 0),
    };
  });
  const gates = GATES.map((name) => {
    const entry = state.gates[name];
    if (!entry) return { gate: name, state: 'UNVERIFIED', reason: NO_EVENT, ref: null, at: null };
    if (name === 'oracle' && entry.state === 'PASS' && !ready) {
      return { gate: name, state: 'UNVERIFIED', reason: OUTCOME_PENDING, ref: entry.ref, at: entry.at };
    }
    return { gate: name, state: entry.state, reason: entry.reason, ref: entry.ref, at: entry.at };
  });
  const rail = {
    phase: railPhase,
    status: state.stall ? 'STALLED' : 'RUNNING',
    receiptReady: ready,
    at: state.railAt,
    reason: state.railReason,
  };
  const last = state.last;
  const agora = {
    current: last ? { text: last.text, phase: last.phase, at: last.at } : { text: '', phase: null, at: null },
    next: { text: nextPhase(railPhase), state: 'PENDING' },
    command: { state: 'UNVERIFIED', reason: COMMAND_REASON },
    timerMs: state.railAt === null ? 0 : Math.max(0, now - state.railAt),
  };
  const health = {
    eventsPerMinute: state.eventTimes.filter((time) => time > now - RATE_WINDOW_MS && time <= now).length,
    heartbeatAgeMs: state.heartbeatAt === null ? null : now - state.heartbeatAt,
    stall: {
      detected: state.stall !== null,
      streak: state.stall ? state.stall.streak : 0,
      silenceMs: state.lastEventAt === null ? null : Math.max(0, now - state.lastEventAt),
    },
  };
  let connection = state.connection;
  if (connection === 'live' && state.lastActivity !== null && now - state.lastActivity > STALE_AFTER_MS) {
    connection = 'stale';
  }
  return { runId: state.runId, lastSeq: state.lastSeq, connection, phase, rail, percent, phases, gates, agora, health };
}

