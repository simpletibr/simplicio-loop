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
const WORKTREE = {
  clean: { state: 'PASS', label: 'Limpo' },
  dirty: { state: 'UNVERIFIED', label: 'Alterações não commitadas' },
  conflict: { state: 'FAIL', label: 'Conflito' },
  prunable: { state: 'STALLED', label: 'Pode ser podado' },
  locked: { state: 'BLOCKED', label: 'Bloqueado' },
  unknown: { state: 'PENDING', label: 'Estado sem registro' },
};
const CLEANUP = { none: 'Sem pendência', pending: 'Limpeza pendente', locked: 'Travado' };
const CHIP_PREFIX = { issue: 'Issue #', pr: 'PR #' };
const SHORT_HEAD = 7;
const EMPTY = 'Nenhum item na fila deste repositório.';
const NO_DRAIN = 'Sem métrica de drenagem para mostrar.';
const NO_DAG = 'Nenhuma dependência entre os itens.';
const NO_SLOTS = 'Nenhum worker com lease.';
const NO_WORKTREES = 'Nenhum worktree para mostrar.';

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

// A GitHub reference is a link when the model gives it a url, and plain text otherwise. Both nodes exist from the
// start; the one that does not apply is hidden, so a poll changes the chip in place.
function chipPair(kind) {
  const link = element('a', 'chip');
  link.setAttribute('target', '_blank');
  link.setAttribute('rel', 'noopener noreferrer');
  const plain = element('span', 'chip');
  link.setAttribute('data-kind', kind);
  plain.setAttribute('data-kind', kind);
  return { link, plain };
}

function fillChip(pair, kind, ref) {
  const text = ref ? CHIP_PREFIX[kind] + ref.number : null;
  const url = ref && ref.url ? ref.url : null;
  setAttr(pair.link, 'href', url);
  show(pair.link, url === null ? null : text);
  show(pair.plain, url === null ? text : null);
}

function cardView() {
  const item = element('li', 'coord-card');
  const id = element('strong', 'card-id');
  const goal = element('p', 'card-goal');
  const links = element('p', 'card-links');
  const issue = chipPair('issue');
  const pr = chipPair('pr');
  links.append(issue.link, issue.plain, pr.link, pr.plain);
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
  item.append(id, goal, links, meta, blocked);
  return { item, id, goal, links, issue, pr, worker, lease, remaining, blocked, blockedText };
}

function fillCard(view, card) {
  const text = blockedLine(card);
  setAttr(view.item, 'data-lease', leaseKey(card.leaseState));
  setAttr(view.item, 'data-blocked', text === null ? null : 'true');
  setText(view.id, card.id);
  show(view.goal, card.goal);
  setAttr(view.links, 'hidden', (card.issue || card.pr) ? null : true);
  fillChip(view.issue, 'issue', card.issue ?? null);
  fillChip(view.pr, 'pr', card.pr ?? null);
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

function worktreeKey(state) {
  return Object.hasOwn(WORKTREE, state) ? state : 'unknown';
}

function worktreeRowView(path) {
  const item = element('li', 'worktree-row');
  item.setAttribute('data-worktree', path);
  const lampEl = lamp();
  const branch = element('strong', 'worktree-branch');
  const head = element('span', 'worktree-head');
  const linked = element('span', 'worktree-item');
  const state = element('span', 'worktree-state');
  const cleanup = element('span', 'worktree-cleanup');
  const main = element('span', 'worktree-main');
  item.append(lampEl, branch, head, linked, state, cleanup, main);
  return { item, lampEl, branch, head, linked, state, cleanup, main };
}

function fillWorktree(view, row) {
  const key = worktreeKey(row.state);
  const cleanupKey = Object.hasOwn(CLEANUP, row.cleanup) ? row.cleanup : 'pending';
  setAttr(view.item, 'data-state', key);
  setAttr(view.item, 'data-cleanup', cleanupKey);
  fillLamp(view.lampEl, WORKTREE[key].state);
  show(view.branch, row.branch || 'sem branch');
  show(view.head, row.head ? row.head.slice(0, SHORT_HEAD) : null);
  show(view.linked, row.itemId ? 'Item: ' + row.itemId : 'Sem item vinculado');
  show(view.state, WORKTREE[key].label);
  show(view.cleanup, CLEANUP[cleanupKey]);
  show(view.main, row.main ? 'Principal' : null);
}

function statusText(model) {
  const head = [model.status ? (STATE_LABEL[model.status] ?? model.status) : null, model.reason]
    .filter(Boolean)
    .join(': ');
  if (model.total !== 0) return head;
  return (head ? head + '. ' : '') + EMPTY;
}

export function createCoordination({ kanban, dag, drain, slots, status, worktrees = null }) {
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

  // The worktree map is optional: a page without the container still gets the rest of the panel.
  const worktreeHeading = element('h3', 'worktree-heading');
  const worktreeReason = element('p', 'worktree-reason');
  const worktreeNote = element('p', 'coord-none worktree-note');
  const worktreeList = element('ol', 'worktree-map');
  const worktreeViews = new Map();
  if (worktrees !== null) worktrees.append(worktreeHeading, worktreeReason, worktreeNote, worktreeList);

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

  function renderWorktrees(model) {
    const map = model.worktrees ?? { status: 'UNVERIFIED', reason: null, rows: [] };
    const measured = map.status === 'MEASURED';
    const rows = map.rows ?? [];
    setText(worktreeHeading, measured ? 'Worktrees (' + rows.length + ')' : 'Worktrees');
    show(worktreeReason, measured ? null : STATE_LABEL.UNVERIFIED + (map.reason ? ': ' + map.reason : ''));
    show(worktreeNote, measured && rows.length === 0 ? NO_WORKTREES : null);
    prune(worktreeViews, new Set(rows.map((row) => row.path)), (view) => view.item);
    const items = rows.map((row) => {
      const view = ensure(worktreeViews, row.path, worktreeRowView);
      fillWorktree(view, row);
      return view.item;
    });
    placeCards(worktreeList, items);
    setAttr(worktreeList, 'hidden', items.length > 0 ? null : true);
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
      if (worktrees !== null) renderWorktrees(model);
      applySelection();
      setText(status, statusText(model));
    },
  };
}
