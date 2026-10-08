// Coordination model for the Simplicio Live dashboard. Turns the GET /api/coordination payload (backlog items with
// their dependencies, leases and worker slots) into six coordination columns, a layered DAG, a drain summary and the
// worker slots. Pure: no DOM and no clock. The caller passes nowMs (null when it has no clock to offer).

export const COORD_COLUMNS = ['ready', 'claimed', 'running', 'verifying', 'done', 'blocked'];
export const COORD_LABELS = {
  ready: 'Pronto',
  claimed: 'Reservado',
  running: 'Em execução',
  verifying: 'Verificando',
  done: 'Concluído',
  blocked: 'Bloqueado',
};

const LEASE_STATES = ['live', 'stale', 'expired'];
const PAYLOAD_STATUSES = ['MEASURED', 'UNVERIFIED'];

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function columnOf(item) {
  return COORD_COLUMNS.includes(item.column) ? item.column : 'blocked';
}

// Keeps the first item of each id, skips anything that is not an object with a non-empty string id.
function itemsOf(payload) {
  const seen = new Set();
  const items = [];
  for (const item of Array.isArray(payload.items) ? payload.items : []) {
    if (!isObject(item) || typeof item.id !== 'string' || item.id === '' || seen.has(item.id)) continue;
    seen.add(item.id);
    items.push(item);
  }
  return items;
}

// A dependency counts only when it is an item of this payload; a repeated dependency is one edge.
function depsOf(item, ids) {
  const deps = Array.isArray(item.depends_on) ? item.depends_on : [];
  return [...new Set(deps)].filter((dep) => ids.has(dep));
}

// With nowMs, a lease is judged against its expires_at on the caller's clock; without it, the payload values stand.
function leaseOf(lease, nowMs) {
  if (!isObject(lease)) return { leaseState: null, remainingS: null };
  const state = LEASE_STATES.includes(lease.state) ? lease.state : null;
  const expires = Date.parse(lease.expires_at);
  if (Number.isFinite(nowMs) && !Number.isNaN(expires)) {
    if (expires <= nowMs) return { leaseState: 'expired', remainingS: 0 };
    return { leaseState: state, remainingS: Math.floor((expires - nowMs) / 1000) };
  }
  return { leaseState: state, remainingS: Number.isFinite(lease.remaining_s) ? lease.remaining_s : null };
}

function cardOf(item, nowMs) {
  const { leaseState, remainingS } = leaseOf(item.lease, nowMs);
  return {
    id: item.id,
    goal: item.goal ?? null,
    column: columnOf(item),
    blockedBy: Array.isArray(item.blocked_by) ? [...item.blocked_by] : [],
    worker: item.worker ?? null,
    leaseState,
    remainingS,
  };
}

// Longest-path depth from the roots. An item whose dependencies never all get a layer (a cycle, or something that
// waits on one) goes to the layer after the deepest placed item. Each layer lists its ids in sorted order.
function layersOf(items, ids) {
  const depsById = new Map(items.map((item) => [item.id, depsOf(item, ids)]));
  const layerById = new Map();
  let placed = true;
  while (placed) {
    placed = false;
    for (const id of ids) {
      if (layerById.has(id)) continue;
      const parents = depsById.get(id);
      if (!parents.every((parent) => layerById.has(parent))) continue;
      const depth = parents.length ? 1 + Math.max(...parents.map((parent) => layerById.get(parent))) : 0;
      layerById.set(id, depth);
      placed = true;
    }
  }
  const deepest = Math.max(-1, ...layerById.values());
  for (const id of ids) {
    if (!layerById.has(id)) layerById.set(id, deepest + 1);
  }
  const layers = Array.from({ length: deepest + 2 }, () => []);
  for (const id of [...ids].sort()) layers[layerById.get(id)].push(id);
  return layers.filter((layer) => layer.length > 0);
}

function edgesOf(items, ids, columnById) {
  const edges = [];
  for (const item of items) {
    for (const dep of depsOf(item, ids)) {
      edges.push({ from: dep, to: item.id, satisfied: columnById.get(dep) === 'done' });
    }
  }
  return edges;
}

function drainOf(drain) {
  if (!isObject(drain)) return null;
  return {
    total: drain.total ?? 0,
    done: drain.done ?? 0,
    remaining: drain.remaining ?? 0,
    blocked: drain.blocked ?? 0,
    percent: drain.percent ?? null,
    etaS: drain.eta_s ?? null,
    etaLabel: drain.eta_label ?? 'UNVERIFIED',
    reason: drain.reason ?? null,
  };
}

function slotsOf(payload) {
  const slots = Array.isArray(payload.slots) ? payload.slots : [];
  return slots.filter(isObject).map((slot) => ({
    worker: slot.worker ?? null,
    items: Array.isArray(slot.items) ? [...slot.items] : [],
    state: slot.state ?? null,
    reclaimable: slot.reclaimable === true,
  }));
}

export function coordinationOf(payload, nowMs) {
  const source = isObject(payload) ? payload : {};
  const status = PAYLOAD_STATUSES.includes(source.status) ? source.status : 'UNVERIFIED';
  const reason = source.reason ?? (status === 'UNVERIFIED' ? 'coordination payload missing or invalid' : null);
  const items = itemsOf(source);
  const ids = new Set(items.map((item) => item.id));
  const columnById = new Map(items.map((item) => [item.id, columnOf(item)]));

  const columns = COORD_COLUMNS.map((key) => ({ key, label: COORD_LABELS[key], count: 0, cards: [] }));
  const byKey = new Map(columns.map((column) => [column.key, column]));
  for (const item of items) {
    const card = cardOf(item, nowMs);
    const column = byKey.get(card.column);
    column.cards.push(card);
    column.count += 1;
  }

  return {
    status,
    reason,
    total: items.length,
    columns,
    dag: { layers: layersOf(items, ids), edges: edgesOf(items, ids, columnById) },
    drain: drainOf(source.drain),
    slots: slotsOf(source),
  };
}

export function blockedText(card) {
  const blockers = card && Array.isArray(card.blockedBy) ? card.blockedBy : [];
  return blockers.length ? 'Bloqueado por: ' + blockers.join(', ') : '';
}
