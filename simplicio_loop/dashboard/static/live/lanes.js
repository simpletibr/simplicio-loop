// Lanes and drill renderers for the Simplicio Live pipeline page. Keyed, in-place updates: a node stays while
// the model keeps its key, so focus and animation are not reset on every tick. Payload text goes through textContent only.
import { STATES } from '/static/components/index.js';

const GLYPH = { RUNNING: '●', PASS: '✓', FAIL: '✕', UNVERIFIED: '◇', STALLED: '‖', BLOCKED: '⊘', PENDING: '○' };
const logSignatures = new WeakMap();
const pad = (value) => String(value).padStart(2, '0');

export function setAttr(el, name, value) {
  if (value === null || value === undefined || value === false) {
    if (el.hasAttribute(name)) el.removeAttribute(name);
    return;
  }
  const text = value === true ? '' : String(value);
  if (el.getAttribute(name) !== text) el.setAttribute(name, text);
}

export function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

export function formatClock(ms) {
  if (ms === null || ms === undefined) return '—';
  const date = new Date(ms);
  return pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}

export function formatDuration(ms) {
  const total = Math.floor(Math.max(0, ms) / 1000);
  const hours = Math.floor(total / 3600);
  const clock = pad(Math.floor((total % 3600) / 60)) + ':' + pad(total % 60);
  return hours > 0 ? pad(hours) + ':' + clock : clock;
}

export function artifactHref(runId, ref, token) {
  if (!ref || !runId || !token) return null;
  return '/api/runs/' + encodeURIComponent(runId) + '/artifacts/' + encodeURIComponent(ref)
    + '?t=' + encodeURIComponent(token);
}

const stateLabel = (state) => STATES[state] || state;
const glyphOf = (state) => GLYPH[state] || GLYPH.PENDING;
const blockKey = (laneId, index) => laneId + '#' + index;

function formatSeconds(ms) {
  return (Math.max(0, ms) / 1000).toFixed(1).replace('.', ',') + ' s';
}

function createLane(laneId) {
  const item = document.createElement('li');
  item.dataset.lane = laneId;
  const head = document.createElement('p');
  head.className = 'lane-head';
  const open = document.createElement('button');
  open.type = 'button';
  open.className = 'lane-open';
  const state = document.createElement('span');
  state.className = 'lane-state';
  const glyph = document.createElement('span');
  glyph.className = 'glyph';
  glyph.setAttribute('aria-hidden', 'true');
  const label = document.createElement('span');
  label.className = 'lane-label';
  state.append(glyph, label);
  const meta = document.createElement('span');
  meta.className = 'lane-meta';
  head.append(open, state, meta);
  const blocks = document.createElement('ol');
  blocks.className = 'blocks';
  item.append(head, blocks);
  return item;
}

function createBlock(key) {
  const item = document.createElement('li');
  item.dataset.key = key;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'block';
  button.dataset.key = key;
  const glyph = document.createElement('span');
  glyph.className = 'glyph';
  glyph.setAttribute('aria-hidden', 'true');
  button.append(glyph);
  item.append(button);
  return item;
}

function updateBlock(item, laneId, block) {
  const button = item.firstElementChild;
  const label = stateLabel(block.state);
  const duration = formatSeconds(block.elapsedMs);
  const number = block.index + 1;
  setAttr(button, 'data-state', block.state);
  setAttr(button, 'data-index', block.index);
  setAttr(button, 'data-tip', 'Bloco ' + number + ', ' + label + ', ' + duration);
  setAttr(button, 'aria-label', 'Bloco ' + number + ' da lane ' + laneId + ', ' + label + ', ' + duration);
  setText(button.firstElementChild, glyphOf(block.state));
}

function renderBlocks(list, lane) {
  const keys = lane.blocks.map((block) => blockKey(lane.id, block.index));
  const wanted = new Set(keys);
  const existing = new Map();
  for (const item of Array.from(list.children)) {
    if (wanted.has(item.dataset.key)) existing.set(item.dataset.key, item);
    else item.remove();
  }
  lane.blocks.forEach((block, position) => {
    const key = keys[position];
    const item = existing.get(key) || createBlock(key);
    if (list.children[position] !== item) list.insertBefore(item, list.children[position] || null);
    updateBlock(item, lane.id, block);
  });
}

function updateLane(item, lane, selected) {
  const last = lane.blocks[lane.blocks.length - 1];
  setAttr(item, 'aria-current', selected ? 'true' : null);
  setText(item.querySelector('.lane-open'), lane.id);
  setText(item.querySelector('.lane-state .glyph'), glyphOf(last.state));
  setText(item.querySelector('.lane-label'), stateLabel(last.state));
  setText(item.querySelector('.lane-meta'), 'Tarefa ' + (lane.taskId || 'sem tarefa') + ', ' + (lane.leaseId ? 'lease ' + lane.leaseId : 'sem lease registrado'));
  renderBlocks(item.querySelector('ol.blocks'), lane);
}

export function renderLanes(list, lanes, selectedId) {
  const wanted = new Set(lanes.map((lane) => lane.id));
  const existing = new Map();
  for (const item of Array.from(list.children)) {
    if (wanted.has(item.dataset.lane)) existing.set(item.dataset.lane, item);
    else item.remove();
  }
  lanes.forEach((lane, position) => {
    const item = existing.get(lane.id) || createLane(lane.id);
    if (list.children[position] !== item) list.insertBefore(item, list.children[position] || null);
    updateLane(item, lane, lane.id === selectedId);
  });
}

export function renderDrill(els, drill, link) {
  setText(els.title, drill.title);
  renderFacts(els.facts, drill.facts, link);
  setLogLines(els.logs, drill.lines);
}

function renderFacts(list, facts, link) {
  while (list.children.length > facts.length) list.lastElementChild.remove();
  while (list.children.length < facts.length) {
    const row = document.createElement('div');
    row.append(document.createElement('dt'), document.createElement('dd'));
    list.append(row);
  }
  facts.forEach((fact, index) => {
    const row = list.children[index];
    setText(row.firstElementChild, fact.label);
    renderValue(row.lastElementChild, fact, link);
  });
}

function renderValue(dd, fact, link) {
  const href = fact.ref ? artifactHref(link.runId, fact.ref, link.token) : null;
  if (href === null) {
    if (dd.firstElementChild) dd.replaceChildren();
    setText(dd, fact.value);
    return;
  }
  let anchor = dd.firstElementChild;
  if (!anchor || anchor.tagName !== 'A') {
    anchor = document.createElement('a');
    dd.replaceChildren(anchor);
  }
  setAttr(anchor, 'href', href);
  setText(anchor, fact.value);
}

function setLogLines(viewer, lines) {
  const mapped = lines.map((line) => ({
    ts: formatClock(line.at),
    level: line.level,
    source: line.source,
    text: line.text,
  }));
  const signature = JSON.stringify(mapped);
  if (logSignatures.get(viewer) === signature) return;
  logSignatures.set(viewer, signature);
  viewer.lines = mapped;
}

