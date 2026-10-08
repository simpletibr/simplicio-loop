// Coordination view of the Simplicio Live page: kanban, DAG, drain and slots from coordinationOf(). In-place updates,
// textContent only; every lamp is a disc plus a glyph, so colour is never the only signal.
function setAttr(el, name, value) {
  if (value === null || value === undefined || value === false) {
    if (el.hasAttribute(name)) el.removeAttribute(name);
    return;
  }
  const text = value === true ? '' : String(value);
  if (el.getAttribute(name) !== text) el.setAttribute(name, text);
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

const STATE_LABEL = {
  RUNNING: 'Em execução',
  PASS: 'Aprovado',
  FAIL: 'Falhou',
  UNVERIFIED: 'Não verificado',
  STALLED: 'Travado',
  BLOCKED: 'Bloqueado',
  PENDING: 'Pendente',
};
const LAMP = { RUNNING: '▶', PASS: '✓', FAIL: '✕', UNVERIFIED: '◇', STALLED: '❚❚', BLOCKED: '⊘', PENDING: '○' };
const LEASE = {
  live: { state: 'RUNNING', label: 'Lease vivo' },
  stale: { state: 'UNVERIFIED', label: 'Lease desatualizado' },
  expired: { state: 'STALLED', label: 'Lease expirado' },
  unknown: { state: 'PENDING', label: 'Lease sem registro' },
};
const EMPTY = 'Nenhum item na fila deste repositório.';
const NO_DRAIN = 'Sem métrica de drenagem para mostrar.';
const NO_DAG = 'Nenhuma dependência entre os itens.';
const NO_SLOTS = 'Nenhum worker com lease.';

function element(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.setAttribute('class', cls);
  return el;
}

function show(el, text) {
  const shown = text !== null && text !== undefined && text !== '';
  setText(el, shown ? text : '');
  setAttr(el, 'hidden', shown ? null : true);
}

function durationText(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return total + ' s';
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return minutes + ' min';
  const rest = minutes % 60;
  return Math.floor(minutes / 60) + ' h' + (rest ? ' ' + rest + ' min' : '');
}

function lamp() {
  const el = element('span', 'lamp');
  el.setAttribute('aria-hidden', 'true');
  return el;
}

function fillLamp(el, state) {
  setAttr(el, 'data-state', state);
  setText(el, LAMP[state] ?? LAMP.PENDING);
}

function leaseKey(state) {
  return Object.hasOwn(LEASE, state) ? state : 'unknown';
}

function leaseBadge() {
  const badge = element('span', 'lease');
  const lampEl = lamp();
  const label = element('span', 'lease-label');
  badge.append(lampEl, label);
  return { badge, lampEl, label };
}

function fillLease(view, leaseState) {
  const key = leaseKey(leaseState);
  setAttr(view.badge, 'data-lease', key);
  fillLamp(view.lampEl, LEASE[key].state);
  setText(view.label, LEASE[key].label);
}

function blockedLine(card) {
  const by = Array.isArray(card.blockedBy) ? card.blockedBy : [];
  return by.length > 0 ? 'Bloqueado por: ' + by.join(', ') : null;
}

function columnView(key) {
  const section = element('section');
  section.setAttribute('data-column', key);
  const heading = element('h3');
  const list = element('ol');
  section.append(heading, list);
  return { section, heading, list };
}

function cardView() {
  const item = element('li', 'coord-card');
  const id = element('strong', 'card-id');
  const goal = element('p', 'card-goal');
  const meta = element('p', 'card-meta');
  const worker = element('span', 'card-worker');
  const lease = leaseBadge();
  const remaining = element('span', 'card-remaining');
  meta.append(worker, lease.badge, remaining);
  const blocked = element('p', 'card-blocked');
  const blockedLampEl = lamp();
  const blockedText = element('span', 'card-blocked-text');
  blocked.append(blockedLampEl, blockedText);
  fillLamp(blockedLampEl, 'BLOCKED');
  item.append(id, goal, meta, blocked);
  return { item, id, goal, worker, lease, remaining, blocked, blockedText };
}

function fillCard(view, card) {
  const text = blockedLine(card);
  setAttr(view.item, 'data-lease', leaseKey(card.leaseState));
  setAttr(view.item, 'data-blocked', text === null ? null : 'true');
  setText(view.id, card.id);
  show(view.goal, card.goal);
  show(view.worker, card.worker ? 'Worker: ' + card.worker : null);
  fillLease(view.lease, card.leaseState);
  show(view.remaining, Number.isFinite(card.remainingS) ? 'restam ' + durationText(card.remainingS) : null);
  show(view.blockedText, text);
  setAttr(view.blocked, 'hidden', text === null ? true : null);
}

// Puts the nodes in model order. A node already in place is not touched, and nodes left over are removed.
function placeCards(list, items) {
  items.forEach((item, index) => {
    if (list.children[index] !== item) list.insertBefore(item, list.children[index] ?? null);
  });
  while (list.children.length > items.length) list.children[items.length].remove();
}

function ensure(cache, key, make) {
  let view = cache.get(key);
  if (view === undefined) {
    view = make(key);
    cache.set(key, view);
  }
  return view;
}

// Removes the cached views whose key is no longer in the model.
function prune(cache, keep, nodeOf) {
  for (const [key, view] of cache) {
    if (!keep.has(key)) {
      nodeOf(view).remove();
      cache.delete(key);
    }
  }
}

function layerView(index) {
  const item = element('li', 'dag-layer');
  item.setAttribute('data-layer', String(index));
  const heading = element('h3');
  const list = element('ol', 'dag-nodes');
  item.append(heading, list);
  return { item, heading, list };
}

function nodeView(id, onSelect) {
  const item = element('li', 'dag-node');
  item.setAttribute('data-node', id);
  const button = element('button', 'dag-node-button');
  button.setAttribute('type', 'button');
  button.setAttribute('aria-pressed', 'false');
  setText(button, id);
  button.addEventListener('click', () => onSelect(id));
  const deps = element('ul', 'dag-deps');
  item.append(button, deps);
  return { item, button, deps };
}

function edgeView() {
  const item = element('li', 'dag-edge');
  const edgeLamp = lamp();
  const text = element('span', 'dag-edge-text');
  item.append(edgeLamp, text);
  return { item, lampEl: edgeLamp, text };
}

function fillEdge(view, edge) {
  const satisfied = Boolean(edge.satisfied);
  view.from = edge.from;
  view.to = edge.to;
  setAttr(view.item, 'data-from', edge.from);
  setAttr(view.item, 'data-to', edge.to);
  setAttr(view.item, 'data-satisfied', String(satisfied));
  fillLamp(view.lampEl, satisfied ? 'PASS' : 'BLOCKED');
  setText(view.text, edge.from + (satisfied ? ': satisfeita' : ': não satisfeita'));
}

function slotView(worker) {
  const item = element('li', 'slot');
  item.setAttribute('data-worker', worker);
  const name = element('strong', 'slot-worker');
  const items = element('span', 'slot-items');
  const lease = leaseBadge();
  const reclaim = element('span', 'slot-reclaim');
  item.append(name, items, lease.badge, reclaim);
  return { item, name, items, lease, reclaim };
}

function itemsText(items) {
  if (Array.isArray(items)) return items.length > 0 ? 'Itens: ' + items.join(', ') : 'Sem itens';
  return items === null || items === undefined ? null : 'Itens: ' + items;
}

function statusText(model) {
  const head = [model.status ? (STATE_LABEL[model.status] ?? model.status) : null, model.reason]
    .filter(Boolean)
    .join(': ');
  if (model.total !== 0) return head;
  return (head ? head + '. ' : '') + EMPTY;
}

export function createCoordination({ kanban, dag, drain, slots, status }) {
  const columns = new Map();
  const cards = new Map();
  const layers = new Map();
  const dagNodes = new Map();
  const dagEdges = new Map();
  const slotViews = new Map();
  let selected = null;
  let lastKey = null;

  // The kanban has no note of its own: the status line says when the queue is empty.
  const dagNote = element('p', 'coord-none');
  const dagLayers = element('ol', 'dag-layers');
  dag.append(dagNote, dagLayers);

  const drainCounts = element('p', 'drain-counts');
  const meter = element('progress', 'drain-meter');
  meter.setAttribute('max', '100');
  meter.setAttribute('aria-label', 'Fila concluída');
  const drainPercent = element('p', 'drain-percent');
  const drainEta = element('p', 'drain-eta');
  const drainReason = element('p', 'drain-reason');
  drain.append(drainCounts, meter, drainPercent, drainEta, drainReason);

  const slotNote = element('p', 'coord-none');
  const slotList = element('ol', 'coord-slot-list');
  slots.append(slotNote, slotList);

  function select(id) {
    selected = selected === id ? null : id;
    applySelection();
  }

  // Marks the selected node's button and every edge that touches it (in or out). Other edges carry no highlight.
  function applySelection() {
    for (const [id, node] of dagNodes) setAttr(node.button, 'aria-pressed', id === selected ? 'true' : 'false');
    for (const edge of dagEdges.values()) {
      const touches = selected !== null && (edge.from === selected || edge.to === selected);
      setAttr(edge.item, 'data-highlight', touches ? 'true' : null);
    }
  }

  function renderKanban(model) {
    const cardIds = new Set(model.columns.flatMap((column) => column.cards.map((card) => card.id)));
    prune(cards, cardIds, (view) => view.item);
    prune(columns, new Set(model.columns.map((column) => column.key)), (view) => view.section);
    const sections = model.columns.map((column) => {
      const view = ensure(columns, column.key, columnView);
      setText(view.heading, column.label + ' (' + column.count + ')');
      const items = column.cards.map((card) => {
        const view = ensure(cards, card.id, cardView);
        fillCard(view, card);
        return view.item;
      });
      placeCards(view.list, items);
      return view.section;
    });
    placeCards(kanban, sections);
  }

  function renderDag(model) {
    const layerRows = model.dag.layers ?? [];
    const nodeIds = new Set(layerRows.flat());
    const visible = (model.dag.edges ?? []).filter((edge) => nodeIds.has(edge.to));
    const incoming = new Map();
    for (const edge of visible) {
      if (!incoming.has(edge.to)) incoming.set(edge.to, []);
      incoming.get(edge.to).push(edge);
    }
    if (selected !== null && !nodeIds.has(selected)) selected = null;
    show(dagNote, layerRows.length > 0 ? null : NO_DAG);
    setAttr(dagLayers, 'hidden', layerRows.length > 0 ? null : true);

    prune(dagNodes, nodeIds, (view) => view.item);
    prune(dagEdges, new Set(visible.map((edge) => JSON.stringify([edge.from, edge.to]))), (view) => view.item);
    prune(layers, new Set(layerRows.map((_, index) => index)), (view) => view.item);

    const layerItems = layerRows.map((ids, index) => {
      const layer = ensure(layers, index, layerView);
      setText(layer.heading, 'Camada ' + (index + 1));
      const nodes = ids.map((id) => {
        const node = ensure(dagNodes, id, (key) => nodeView(key, select));
        const edges = (incoming.get(id) ?? []).map((edge) => {
          const edgeKey = JSON.stringify([edge.from, edge.to]);
          const view = ensure(dagEdges, edgeKey, edgeView);
          fillEdge(view, edge);
          return view.item;
        });
        placeCards(node.deps, edges);
        setAttr(node.deps, 'hidden', edges.length > 0 ? null : true);
        return node.item;
      });
      placeCards(layer.list, nodes);
      return layer.item;
    });
    placeCards(dagLayers, layerItems);
  }

  function renderDrain(model) {
    const drainRow = model.drain;
    if (!drainRow) {
      show(drainCounts, NO_DRAIN);
      show(drainPercent, null);
      show(drainEta, null);
      show(drainReason, null);
      setAttr(meter, 'value', null);
      setAttr(meter, 'hidden', true);
      return;
    }
    const blockedPart = drainRow.blocked > 0 ? ' (' + drainRow.blocked + (drainRow.blocked === 1 ? ' bloqueado)' : ' bloqueados)') : '';
    show(drainCounts, 'Concluídos ' + drainRow.done + ' de ' + drainRow.total + '. Restam ' + drainRow.remaining + blockedPart + '.');
    const percent = Number.isFinite(drainRow.percent) ? drainRow.percent : null;
    show(drainPercent, percent === null ? null : percent + '% da fila concluída');
    setAttr(meter, 'value', percent === null ? null : String(percent));
    setAttr(meter, 'hidden', percent === null ? true : null);
    const etaValue = Number.isFinite(drainRow.etaS) ? durationText(drainRow.etaS) : 'sem estimativa';
    show(drainEta, 'ETA: ' + etaValue + ' (' + (drainRow.etaLabel || 'UNVERIFIED') + ')');
    show(drainReason, drainRow.reason || null);
  }

  function renderSlots(model) {
    const rows = model.slots ?? [];
    prune(slotViews, new Set(rows.map((row) => row.worker)), (view) => view.item);
    const items = rows.map((row) => {
      const view = ensure(slotViews, row.worker, slotView);
      show(view.name, row.worker);
      show(view.items, itemsText(row.items));
      fillLease(view.lease, row.state);
      setAttr(view.reclaim, 'hidden', row.reclaimable ? null : true);
      setText(view.reclaim, 'reclamável');
      return view.item;
    });
    placeCards(slotList, items);
    show(slotNote, rows.length > 0 ? null : NO_SLOTS);
    setAttr(slotList, 'hidden', rows.length > 0 ? null : true);
  }

  return {
    render(model) {
      const key = JSON.stringify(model);
      if (key === lastKey) return;
      lastKey = key;
      renderKanban(model);
      renderDag(model);
      renderDrain(model);
      renderSlots(model);
      applySelection();
      setText(status, statusText(model));
    },
  };
}
