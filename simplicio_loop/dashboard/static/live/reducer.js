// Simplicio Live pipeline reducer (issue #1402). Pure: no DOM, no network, no clock.
// Time enters only through selectView(state, nowMs) and the timestamps carried by actions.
import { applyIteration, initialIterations, selectConvergence, selectIterations } from './iterations.js';
import { agentsCostView, economyView } from './economy.js';

export const GATES = ['evidence', 'watcher', 'oracle', 'dod', 'quality', 'action'];
export const READY_VERDICTS = ['COMPLETE', 'DRAINED', 'VERIFIED'];
export const STALE_AFTER_MS = 45000;

const SCHEMA = 'simplicio.dashboard-event/v1';
const RAIL = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done'];
const RATE_WINDOW_MS = 60000;
const NO_EVENT = 'nenhum evento recebido';
const OUTCOME_PENDING = 'aguardando recibo de conclusão';
const COMMAND_REASON = 'nenhum comando medido nesta visão';
const AGENT_REASON = 'sinal do agente não medido nesta visão';
const HEARTBEAT_REASON = 'batimento da lane não medido nesta visão';
const LANE_BLOCK_CAP = 50;
const LOG_CAP = 200;
const FILE_COMMAND_CAP = 50;
const LANE_GATES = ['evidence', 'quality'];
const GATE_CLOSE = { pass: 'PASS', fail: 'FAIL', blocked: 'BLOCKED' };
const OUTCOME_CLOSE = { pass: 'PASS', blocked: 'BLOCKED', refeed: 'UNVERIFIED' };
const PHASE_LABEL = {
  intake: 'Contrato recebido',
  mapping: 'Contexto mapeado',
  planning: 'Plano congelado',
  executing: 'Execução em andamento',
  validating: 'Validação e evidências',
  watching: 'Watcher verificando',
  delivering: 'Entrega reconciliada',
  done: 'Concluído pelo oracle',
};

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
    lanes: {},
    laneOrder: [],
    taskLane: {},
    log: [],
    alerts: [],
    iterations: initialIterations(),
    quality: null,
    tokens: null,
    agents: null,
    budget: null,
    receipts: [],
    repo: null,
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

function countIteration(state, event, stamp, payload) {
  return { ...state, iterations: applyIteration(state.iterations, event, stamp, payload, state.gates) };
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
  const logged = appendLog(next, event, stamp, payload);
  const laned = countIteration(applyLane(logged, event, stamp, payload), event, stamp, payload);
  if (event.kind === 'phase_entered') return enterPhase(laned, event, stamp, payload);
  if (event.kind === 'phase_exited') return exitPhase(laned, event, stamp);
  if (event.kind === 'stall_detected') return recordStall(laned, event, stamp, payload);
  if (event.kind === 'gate_evaluated') return evaluateGate(laned, event, stamp, payload);
  return laned;
}

function lineOf(event, stamp, payload) {
  return {
    at: stamp,
    level: typeof event.severity === 'string' ? event.severity : 'info',
    source: typeof event.source === 'string' ? event.source : '',
    text: String(payload.message || event.kind || ''),
    phase: event.phase || null,
    refs: Array.isArray(event.refs) ? event.refs.map(String) : [],
  };
}

function appendLog(state, event, stamp, payload) {
  return { ...state, log: state.log.concat([lineOf(event, stamp, payload)]).slice(-LOG_CAP) };
}

function mapped(table, key) {
  return typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : null;
}

function resolveLane(taskLane, event) {
  if (typeof event.lane === 'string' && event.lane) return event.lane;
  const taskId = typeof event.task_id === 'string' ? event.task_id : '';
  return taskId && Object.hasOwn(taskLane, taskId) ? taskLane[taskId] : null;
}

// The verdict an event sets on an open block, or null when the event does not close a block.
function closingOf(event, payload) {
  let state = null;
  if (event.kind === 'apply_result' && payload.execution_state === 'blocked') state = 'BLOCKED';
  if (event.kind === 'gate_evaluated' && LANE_GATES.includes(payload.gate)) {
    state = mapped(GATE_CLOSE, typeof payload.verdict === 'string' ? payload.verdict.toLowerCase() : '');
  }
  if (event.kind === 'iteration_finished') state = mapped(OUTCOME_CLOSE, payload.outcome);
  if (state === null) return null;
  return {
    state,
    reason: typeof payload.message === 'string' ? payload.message : '',
    ref: Array.isArray(event.refs) && event.refs.length > 0 ? String(event.refs[0]) : null,
  };
}

function advanceBlock(block, event, stamp, payload) {
  let next = { ...block, lastAt: stamp, lines: block.lines.concat([lineOf(event, stamp, payload)]) };
  if (event.kind === 'stall_detected') {
    if (next.state === 'RUNNING') next = { ...next, state: 'STALLED' };
    return next;
  }
  if (next.state === 'STALLED') next = { ...next, state: 'RUNNING' };
  const closing = next.state === 'RUNNING' ? closingOf(event, payload) : null;
  if (closing === null) return next;
  return { ...next, ...closing, endedAt: stamp === null ? next.startedAt : stamp };
}

function applyLane(state, event, stamp, payload) {
  const explicit = typeof event.lane === 'string' && event.lane ? event.lane : null;
  const taskId = typeof event.task_id === 'string' && event.task_id ? event.task_id : null;
  const taskLane = explicit && taskId ? { ...state.taskLane, [taskId]: explicit } : state.taskLane;
  const laneId = resolveLane(taskLane, event);
  if (laneId === null) return state;
  const known = Object.hasOwn(state.lanes, laneId)
    ? state.lanes[laneId]
    : { id: laneId, taskId: null, leaseId: null, nextIndex: 0, blocks: [] };
  const iteration = Number.isInteger(event.iteration) ? event.iteration : null;
  const last = known.blocks.length > 0 ? known.blocks[known.blocks.length - 1] : null;
  const opens = last === null || event.kind === 'worker_claimed'
    || (iteration !== null && last.iteration !== null && last.iteration !== iteration);
  let block;
  if (opens) {
    block = { index: known.nextIndex, iteration, state: 'RUNNING', startedAt: stamp, endedAt: null, lastAt: stamp, lines: [], reason: null, ref: null };
  } else {
    block = last.iteration === null && iteration !== null ? { ...last, iteration } : last;
  }
  const kept = opens ? known.blocks : known.blocks.slice(0, -1);
  const lane = {
    id: laneId,
    taskId: taskId || known.taskId,
    leaseId: event.kind === 'worker_claimed' ? (typeof payload.lease_id === 'string' ? payload.lease_id : null) : known.leaseId,
    nextIndex: opens ? known.nextIndex + 1 : known.nextIndex,
    blocks: kept.concat([advanceBlock(block, event, stamp, payload)]).slice(-LANE_BLOCK_CAP),
  };
  return {
    ...state,
    taskLane,
    lanes: { ...state.lanes, [laneId]: lane },
    laneOrder: Object.hasOwn(state.lanes, laneId) ? state.laneOrder : state.laneOrder.concat([laneId]),
  };
}

function recordStall(state, event, stamp, payload) {
  const streak = Number(payload.streak) || 1;
  const laneId = resolveLane(state.taskLane, event);
  const alert = {
    id: 'stall-' + event.seq,
    state: 'STALLED',
    heading: laneId === null ? 'Run sem avanço' : 'Lane sem avanço',
    message: laneId === null
      ? 'O run ficou sem avanço (sequência ' + streak + ').'
      : 'A lane ' + laneId + ' ficou sem avanço (sequência ' + streak + ').',
    at: stamp,
  };
  return {
    ...state,
    stall: { phase: event.phase || null, streak, at: stamp, seq: event.seq },
    alerts: state.alerts.concat([alert]),
  };
}

export function reduce(state, action) {
  if (!action || typeof action !== 'object') return state;
  if (action.type === 'event') return applyEvent(state, action.event);
  if (action.type === 'summary') return { ...state, summary: action.summary || null };
  if (action.type === 'quality') return { ...state, quality: action.receipt && typeof action.receipt === 'object' ? action.receipt : null };
  if (action.type === 'connection') {
    const at = numberOrNull(action.at);
    return { ...state, connection: String(action.status || 'connecting'), lastActivity: at === null ? state.lastActivity : at };
  }
  if (action.type === 'tokens') return { ...state, tokens: action.response === undefined ? null : action.response };
  if (action.type === 'budget') return { ...state, budget: action.response && typeof action.response === 'object' && !Array.isArray(action.response) ? action.response : null };
  if (action.type === 'agents') return { ...state, agents: action.response === undefined ? null : action.response };
  if (action.type === 'receipts') return { ...state, receipts: receiptRowsOf(action.receipts) };
  if (action.type === 'repo') return { ...state, repo: typeof action.repo === 'string' && action.repo !== '' ? action.repo : null };
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

const PILLARS = [
  ['implementation', 'Implementação'],
  ['unit', 'Testes unitários'],
  ['integration', 'Testes de integração'],
  ['system', 'Testes de sistema'],
  ['regression', 'Regressão'],
  ['benchmark', 'Benchmark'],
  ['coverage', 'Cobertura'],
];
const TEST_PILLARS = ['unit', 'integration', 'system', 'regression'];
const PILLAR_STATUS = { pass: 'PASS', fail: 'FAIL', not_applicable: 'PENDING' };
const RECEIPT_MISSING = 'quality-matrix.json ainda nao gerado';
const REQUIREMENT_MISSING = 'sem registro no quality-matrix.json';
const NO_PRODUCER = 'sem produtor no fluxo atual';
const RECEIPT_STATES = ['VALID', 'INVALID', 'UNVERIFIED'];
const NO_VERDICT = 'validação não informada';
const RUN_ID_PATTERN = /^[A-Za-z0-9._-]+$/;
const PLAIN_WORD = /^[A-Za-z0-9_./:@%+=,-]+$/;

function textOrNull(value) {
  return typeof value === 'string' && value !== '' ? value : null;
}

// The proof path after the run segment (evidence/unit.json), or null when the run is not in the path.
function refOf(proofRef, runId) {
  const text = textOrNull(proofRef);
  if (text === null || !runId) return null;
  const marker = '/' + runId + '/';
  const at = text.indexOf(marker);
  return at < 0 ? null : textOrNull(text.slice(at + marker.length));
}

function coverageOf(receipt) {
  if (receipt === null) return { measured: null, threshold: null, status: null, proofRef: null };
  const coverage = receipt.coverage && typeof receipt.coverage === 'object' ? receipt.coverage : {};
  return {
    measured: numberOrNull(coverage.measured),
    threshold: numberOrNull(receipt.coverage_threshold),
    status: typeof coverage.status === 'string' ? coverage.status : null,
    proofRef: coverage.proof_ref,
  };
}

function coverageStateOf(measured, threshold, status) {
  if (measured !== null && threshold !== null) return measured >= threshold ? 'PASS' : 'FAIL';
  if (measured === null && status === 'not_applicable') return 'PENDING';
  return 'UNVERIFIED';
}

function coveragePillar(coverage, runId, label) {
  let detail = 'cobertura não medida';
  if (coverage.measured !== null) {
    detail = 'cobertura ' + coverage.measured + '%' + (coverage.threshold === null ? '' : ' (limite ' + coverage.threshold + '%)');
  }
  return {
    pillar: 'coverage',
    label,
    state: coverageStateOf(coverage.measured, coverage.threshold, coverage.status),
    detail,
    ref: refOf(coverage.proofRef, runId),
  };
}

function requirementPillar(receipt, key, label, runId) {
  const requirements = receipt.requirements && typeof receipt.requirements === 'object' ? receipt.requirements : {};
  const entry = Object.hasOwn(requirements, key) && requirements[key] && typeof requirements[key] === 'object' ? requirements[key] : null;
  if (entry === null) return { pillar: key, label, state: 'UNVERIFIED', detail: REQUIREMENT_MISSING, ref: null };
  return {
    pillar: key,
    label,
    state: mapped(PILLAR_STATUS, entry.status) || 'UNVERIFIED',
    detail: textOrNull(entry.detail) || 'sem detalhe registrado',
    ref: refOf(entry.proof_ref, runId),
  };
}

function pillarsOf(receipt, runId) {
  const coverage = coverageOf(receipt);
  return PILLARS.map(([key, label]) => {
    if (receipt === null) return { pillar: key, label, state: 'UNVERIFIED', detail: RECEIPT_MISSING, ref: null };
    if (key === 'coverage') return coveragePillar(coverage, runId, label);
    return requirementPillar(receipt, key, label, runId);
  });
}

// Definition of done: FAIL if any pillar fails; PASS only when all seven pillars pass; otherwise UNVERIFIED (PENDING is not proven).
function dodView(receipt, runId) {
  const pillars = pillarsOf(receipt, runId);
  const coverage = coverageOf(receipt);
  let state = 'UNVERIFIED';
  if (pillars.some((item) => item.state === 'FAIL')) state = 'FAIL';
  else if (pillars.every((item) => item.state === 'PASS')) state = 'PASS';
  const coverageItem = pillars.find((item) => item.pillar === 'coverage');
  return {
    state,
    pillars,
    coverage: { measured: coverage.measured, threshold: coverage.threshold, state: coverageItem.state },
  };
}

function testsOf(receipt, dod) {
  if (receipt === null) return { state: 'UNVERIFIED', reason: RECEIPT_MISSING };
  const states = dod.pillars.filter((item) => TEST_PILLARS.includes(item.pillar)).map((item) => item.state);
  if (states.includes('FAIL')) return { state: 'FAIL', reason: 'teste de nível falhou' };
  if (states.every((item) => item === 'PASS')) return { state: 'PASS', reason: 'testes de unidade, integração, sistema e regressão aprovados' };
  return { state: 'UNVERIFIED', reason: 'testes sem aprovação completa no quality-matrix' };
}

function qualityView(receipt, dod) {
  return {
    tests: testsOf(receipt, dod),
    lint: { state: 'UNVERIFIED', reason: NO_PRODUCER },
    coverageTrend: { state: 'UNVERIFIED', reason: NO_PRODUCER },
    flaky: { state: 'UNVERIFIED', reason: NO_PRODUCER },
    diff: { state: 'UNVERIFIED', reason: NO_PRODUCER },
  };
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
  const lanes = state.laneOrder.map((id) => laneView(state.lanes[id], now));
  const iterations = selectIterations(state.iterations, now, state.gates);
  const dod = dodView(state.quality, state.runId);
  const quality = qualityView(state.quality, dod);
  const economy = economyView(state.tokens);
  return {
    runId: state.runId,
    lastSeq: state.lastSeq,
    connection,
    phase,
    rail,
    percent,
    phases,
    gates,
    agora,
    health,
    lanes,
    alerts: state.alerts,
    iterations,
    convergence: selectConvergence(iterations),
    dod,
    quality,
    economy,
    agentsCost: agentsCostView(economy, state.agents, state.budget),
    receipts: state.receipts,
    runCommands: runCommandsOf(state.runId, state.repo),
  };
}

// A verdict is VALID or INVALID only when the server validated the receipt; anything else is UNVERIFIED with no claim.
function verdictOf(value) {
  if (value && typeof value === 'object' && RECEIPT_STATES.includes(value.state) && typeof value.reason === 'string') {
    return { state: value.state, reason: value.reason };
  }
  return { state: 'UNVERIFIED', reason: NO_VERDICT };
}

// Keeps only entries the drawer can show: a non-empty name and a finite size. Anything else is dropped.
function receiptRowsOf(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && typeof item === 'object' && typeof item.name === 'string' && item.name !== ''
      && typeof item.size === 'number' && Number.isFinite(item.size))
    .map((item) => ({ name: item.name, size: item.size, validation: verdictOf(item.validation) }));
}

// A word goes to the shell as it is when it has no special character; anything else is single-quoted.
function shellWord(text) {
  return PLAIN_WORD.test(text) ? text : "'" + text.replace(/'/g, "'\\''") + "'";
}

// The exact CLI lines that reproduce the run's state. Empty until the run id and the repo path are both known.
function runCommandsOf(runId, repo) {
  if (!runId || !RUN_ID_PATTERN.test(runId) || !repo) return [];
  const base = 'simplicio-loop progress ' + runId + ' --repo ' + shellWord(repo);
  return [
    { id: 'progress', label: 'Estado do run', command: base },
    { id: 'progress-json', label: 'Estado em JSON, uma leitura', command: base + ' --format json --once' },
  ];
}

function laneView(lane, now) {
  const blocks = lane.blocks.map((block) => {
    const end = block.endedAt === null ? now : block.endedAt;
    return {
      index: block.index,
      iteration: block.iteration,
      state: block.state,
      startedAt: block.startedAt,
      endedAt: block.endedAt,
      elapsedMs: block.startedAt === null ? 0 : Math.max(0, end - block.startedAt),
      events: block.lines.length,
      reason: block.reason,
      ref: block.ref,
    };
  });
  return {
    id: lane.id,
    state: blocks[blocks.length - 1].state,
    taskId: lane.taskId,
    leaseId: lane.leaseId,
    agent: { state: 'UNVERIFIED', reason: AGENT_REASON },
    heartbeat: { state: 'UNVERIFIED', reason: HEARTBEAT_REASON },
    blocks,
  };
}

function lineView(line) {
  return { at: line.at, level: line.level, source: line.source, text: line.text };
}

function formatMs(ms) {
  return Math.round(Math.max(0, ms) / 1000) + ' s';
}

function emptyDrill() {
  return { title: 'Sem dados disponíveis', facts: [], lines: [] };
}

function phaseDrill(state, phase, now) {
  if (!RAIL.includes(phase)) return emptyDrill();
  const item = state.phases[phase];
  const open = item.openSince !== null;
  const elapsed = item.closedMs + (open ? Math.max(0, now - item.openSince) : 0);
  let status = 'Pendente';
  if (open) status = 'Em andamento';
  else if (item.entries > 0) status = 'Concluída';
  return {
    title: PHASE_LABEL[phase],
    facts: [
      { label: 'Situação', value: status },
      { label: 'Entradas', value: String(item.entries) },
      { label: 'Tempo acumulado', value: formatMs(elapsed) },
    ],
    lines: state.log.filter((line) => line.phase === phase).map(lineView),
  };
}

function laneOwned(state, laneId) {
  return typeof laneId === 'string' && Object.hasOwn(state.lanes, laneId) ? state.lanes[laneId] : null;
}

function blockDrill(state, laneId, index, now) {
  const lane = laneOwned(state, laneId);
  const block = lane ? lane.blocks.find((item) => item.index === index) : undefined;
  if (!block) return emptyDrill();
  const end = block.endedAt === null ? now : block.endedAt;
  const facts = [
    { label: 'Estado', value: block.state },
    { label: 'Iteração', value: block.iteration === null ? 'não informada' : String(block.iteration) },
    { label: 'Duração', value: formatMs(block.startedAt === null ? 0 : Math.max(0, end - block.startedAt)) },
    { label: 'Motivo', value: block.reason || 'sem motivo registrado' },
  ];
  if (block.ref) facts.push({ label: 'Recibo', value: block.ref, ref: block.ref });
  return { title: 'Bloco ' + (block.index + 1) + ' de ' + laneId, facts, lines: block.lines.map(lineView) };
}

function laneDrill(state, laneId) {
  const lane = laneOwned(state, laneId);
  if (!lane) return emptyDrill();
  return {
    title: 'Lane ' + laneId,
    facts: [
      { label: 'Tarefa', value: lane.taskId || 'sem tarefa' },
      { label: 'Lease', value: lane.leaseId || 'não registrado' },
      { label: 'Blocos', value: String(lane.blocks.length) },
      { label: 'Estado atual', value: lane.blocks[lane.blocks.length - 1].state },
    ],
    lines: lane.blocks.flatMap((block) => block.lines).map(lineView),
  };
}

function logsDrill(state) {
  return {
    title: 'Registro do run',
    facts: [
      { label: 'Eventos no registro', value: String(state.log.length) },
      { label: 'Último evento', value: String(state.lastSeq) },
    ],
    lines: state.log.map(lineView),
  };
}

function iterationDrill(state, n, now) {
  if (!Number.isInteger(n) || n < 0) return emptyDrill();
  const row = selectIterations(state.iterations, now, state.gates).find((item) => item.iteration === n);
  if (!row) return emptyDrill();
  const blocks = state.laneOrder.flatMap((laneId) => state.lanes[laneId].blocks.filter((block) => block.iteration === n));
  return {
    title: 'Iteração ' + n,
    facts: [
      { label: 'Situação', value: row.state },
      { label: 'Duração', value: row.durationMs === null ? 'não informada' : formatMs(row.durationMs) },
      { label: 'Gates falhando', value: String(row.gatesFailing.length) },
      { label: 'Gates não verificados', value: String(row.gatesUnverified.length) },
      { label: 'Parada', value: row.verdict === 'STALLED' ? 'sim, repetição ' + row.streak : 'não' },
    ],
    lines: blocks.flatMap((block) => block.lines).map(lineView),
  };
}

export function selectDrill(state, target, nowMs) {
  const now = Number.isFinite(nowMs) ? nowMs : 0;
  const kind = target && typeof target === 'object' ? target.type : null;
  if (kind === 'phase') return phaseDrill(state, target.phase, now);
  if (kind === 'block') return blockDrill(state, target.lane, target.index, now);
  if (kind === 'lane') return laneDrill(state, target.lane);
  if (kind === 'iteration') return iterationDrill(state, target.iteration, now);
  if (kind === 'logs') return logsDrill(state);
  return emptyDrill();
}

export function selectCommands(state) {
  const commands = RAIL.map((phase) => ({
    id: 'phase:' + phase,
    label: PHASE_LABEL[phase],
    group: 'Fases',
    hint: 'Abrir detalhe da fase',
  }));
  const taskIds = [];
  for (const laneId of state.laneOrder) {
    const taskId = state.lanes[laneId].taskId;
    if (taskId && !taskIds.includes(taskId)) {
      taskIds.push(taskId);
      commands.push({ id: 'task:' + taskId, label: 'Tarefa ' + taskId, group: 'Tarefas', hint: 'Abrir a lane ' + laneId });
    }
  }
  const refs = [];
  for (let index = state.log.length - 1; index >= 0 && refs.length < FILE_COMMAND_CAP; index -= 1) {
    for (const ref of state.log[index].refs) {
      if (refs.length < FILE_COMMAND_CAP && !refs.includes(ref)) refs.push(ref);
    }
  }
  for (const ref of refs) {
    commands.push({ id: 'file:' + ref, label: ref, group: 'Arquivos', hint: 'Abrir o recibo' });
  }
  return commands;
}

