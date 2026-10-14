// Measured agent map of the Live page (issue #1550): the agent instances, the slots in use, the lease each one holds and the
// lease heartbeat, read from the run's Mapper operations store by GET /api/runs/<id>/extras (field "agents"). extras.js loads
// this file on the first reply. Pure view first (no DOM, no network, no clock), then a renderer that builds the DOM with
// textContent only. A figure the store did not record stays UNVERIFIED with the reason; nothing is invented.
import { make, renderBadges } from './dom-badges.js';

const MAX_ROWS = 20;
const NO_AGENTS = 'instâncias não medidas: o run não informou o mapa de agentes';
const NO_SLOTS = 'slots não medidos';
const STATUS_TEXT = {
  pending: 'aguardando', running: 'em execução', completed: 'concluído', shutdown: 'encerrado', reclaimable: 'recuperável',
};

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = (value) => typeof value === 'string' && value.trim() !== '';
const isCount = (value) => Number.isFinite(value) && value >= 0;

// Share of part in total as a percent clamped to 0..100; anything that is not a finite positive total reads as 0.
function percentOf(part, total) {
  if (!isCount(part) || !isCount(total) || total <= 0) return 0;
  return Math.min(100, (part / total) * 100);
}

function slotsOf(slots) {
  const source = isObject(slots) ? slots : {};
  if (source.state === 'MEASURED' && isCount(source.capacity) && isCount(source.used)) {
    const free = isCount(source.free) ? source.free : Math.max(0, source.capacity - source.used);
    return {
      state: 'PASS',
      detail: source.used + ' de ' + source.capacity + ' slots em uso, ' + free + ' livres',
      percent: percentOf(source.used, source.capacity),
    };
  }
  return { state: 'UNVERIFIED', detail: NO_SLOTS + ': ' + (isText(source.reason) ? source.reason : 'o store não informou a capacidade'), percent: null };
}

// The heartbeat sentence of one instance: the age of the last beat, or why it is not measured.
function heartbeatText(beat) {
  if (isObject(beat) && beat.state === 'MEASURED' && isCount(beat.age_s)) {
    return (beat.stale === true ? 'batimento obsoleto, último há ' : 'último batimento há ') + beat.age_s + ' s';
  }
  return 'batimento não medido: ' + (isObject(beat) && isText(beat.reason) ? beat.reason : 'sem registro');
}

// Only a running agent is judged by its heartbeat; a finished one is not flagged for a lease nobody beats any more.
function instanceState(row) {
  if (row.status === 'completed') return 'PASS';
  if (row.status === 'shutdown' || row.status === 'reclaimable') return 'STALLED';
  if (row.status === 'pending') return 'PENDING';
  const beat = isObject(row.heartbeat) ? row.heartbeat : {};
  if (beat.state !== 'MEASURED') return 'UNVERIFIED';
  return beat.stale === true ? 'STALLED' : 'RUNNING';
}

function instanceRow(row) {
  const parts = [isText(row.status) ? (STATUS_TEXT[row.status] || row.status) : 'sem status'];
  if (isCount(row.attempt)) parts.push('tentativa ' + row.attempt);
  if (isText(row.worktree)) parts.push('worktree ' + row.worktree);
  parts.push(isText(row.lease_id) ? 'lease ' + row.lease_id : 'sem lease');
  parts.push(heartbeatText(row.heartbeat));
  return { key: 'agent:' + row.agent_id, label: row.agent_id, state: instanceState(row), detail: parts.join(' · ') };
}

// The agent map of one extras reply: a summary row, the slots, and one row per measured instance (the first 20).
export function agentMapView(agents) {
  const source = isObject(agents) ? agents : {};
  const slots = slotsOf(source.slots);
  const slotsRow = { key: 'slots', label: 'Slots', state: slots.state, detail: slots.detail };
  if (source.state !== 'MEASURED') {
    const reason = isText(source.reason) ? source.reason : NO_AGENTS;
    return { state: 'UNVERIFIED', reason, slots, more: 0, rows: [{ key: 'summary', label: 'Instâncias', state: 'UNVERIFIED', detail: reason }, slotsRow] };
  }
  const found = Array.isArray(source.instances) ? source.instances.filter((row) => isObject(row) && isText(row.agent_id)) : [];
  const total = Number.isInteger(source.instances_total) && source.instances_total >= found.length ? source.instances_total : found.length;
  const counts = isObject(source.counts) ? source.counts : {};
  const summary = Object.keys(STATUS_TEXT).filter((status) => isCount(counts[status]) && counts[status] > 0)
    .map((status) => counts[status] + ' ' + STATUS_TEXT[status]).join(', ');
  const rows = [
    { key: 'summary', label: 'Instâncias', state: 'PASS', detail: total + (total === 1 ? ' instância medida' : ' instâncias medidas') + ' no store de operações' + (summary ? ': ' + summary : '') },
    slotsRow,
    ...found.slice(0, MAX_ROWS).map(instanceRow),
  ];
  return { state: 'MEASURED', reason: null, slots, more: Math.max(0, total - Math.min(found.length, MAX_ROWS)), rows };
}

function build() {
  const slots = make('div', { id: 'agent-map-bar', class: 'extras-bar' }, make('span', { class: 'extras-seg extras-seg-0' }));
  return make('section', { id: 'agent-map', class: 'panel agent-map', 'aria-labelledby': 'agent-map-title' },
    make('h2', { id: 'agent-map-title' }, 'Instâncias, slots e leases'),
    make('p', { id: 'agent-map-note', class: 'note' }),
    make('ul', { id: 'agent-map-list', class: 'checks', 'aria-label': 'Instâncias, slots e leases' }),
    slots);
}

// Draws the agent map under the worker signals panel, building the section on the first call. The slots bar is a share of
// the slot capacity, with its width set through the CSSOM (a clamped percent), never a style attribute.
export function renderAgentMap(agents) {
  let host = document.getElementById('agent-map');
  if (!host) {
    host = build();
    document.getElementById('live-extras').after(host);
  }
  const view = agentMapView(agents);
  document.getElementById('agent-map-note').textContent = view.more > 0 ? 'Mais ' + view.more + ' instâncias não listadas.' : '';
  renderBadges(document.getElementById('agent-map-list'), view.rows);
  const bar = document.getElementById('agent-map-bar');
  bar.hidden = view.slots.percent === null;
  if (view.slots.percent !== null) bar.firstElementChild.style.setProperty('width', Math.round(view.slots.percent * 100) / 100 + '%');
}
