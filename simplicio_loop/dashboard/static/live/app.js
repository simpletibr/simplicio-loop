// Simplicio Live pipeline page: reads the run from the URL, streams its events and renders the reducer view.
import { connectStream } from '/static/live/sse.js';
import { initialState, reduce, selectCommands, selectDrill, selectView } from '/static/live/reducer.js';
import { artifactHref, renderDrill } from '/static/live/lanes.js';
import { SlAlertToast } from '/static/components/index.js';
import { createView } from '/static/live/view.js';

const SUMMARY_DEBOUNCE_MS = 250;
const TICK_MS = 1000;
const SUMMARY_POLL_MS = 500;
const THEMES = ['dark', 'light', 'contrast'];

const params = new URLSearchParams(window.location.search);
const token = params.get('t') || '';
const runId = params.get('run') || '';
const theme = params.get('theme') || '';
if (THEMES.includes(theme)) document.documentElement.setAttribute('data-sl-theme', theme);
if (params.get('tv') === '1') document.documentElement.dataset.tv = '1';

const view = createView();
const controller = new AbortController();
let state = initialState(runId);
let summaryTimer = null;

function runPath() {
  return '/api/runs/' + encodeURIComponent(runId);
}

const drillPanel = document.getElementById('drill');
const drillEls = {
  title: document.getElementById('drill-title'),
  facts: document.getElementById('drill-facts'),
  logs: document.getElementById('drill-logs'),
};
const palette = document.getElementById('palette');
const follow = document.getElementById('follow');
const lanesList = document.getElementById('lanes');
const gatesList = document.getElementById('gates');
const phaseStats = document.getElementById('phase-stats');
const TOAST_WINDOW_MS = 60000;
const toasted = new Set();
let shown = state;
let following = true;
let selectedLane = null;
let drillTarget = null;
let drillOpener = null;
let commandsSignature = '';

function link() {
  return { runId, token };
}

function render() {
  const now = Date.now();
  const model = selectView(shown, now);
  view.render(model, { token, runId, selectedLane });
  if (drillTarget !== null) renderDrill(drillEls, selectDrill(shown, drillTarget, now), link());
  syncPalette();
  showAlerts(model.alerts, now);
  if (document.documentElement.dataset.ready !== '1') document.documentElement.dataset.ready = '1';
}

// While paused, events still reduce into state; the view keeps the snapshot it showed until resume.
function dispatch(action) {
  const before = state.lastSeq;
  state = reduce(state, action);
  if (state.lastSeq !== before) document.body.dataset.lastSeq = String(state.lastSeq);
  if (following) {
    shown = state;
    render();
  }
}

function syncPalette() {
  const commands = selectCommands(shown);
  const signature = JSON.stringify(commands);
  if (signature === commandsSignature) return;
  commandsSignature = signature;
  palette.commands = commands;
}

function showAlerts(alerts, now) {
  for (const alert of alerts) {
    if (toasted.has(alert.id)) continue;
    toasted.add(alert.id);
    if (alert.at !== null && Math.abs(now - alert.at) <= TOAST_WINDOW_MS) {
      SlAlertToast.notify({ state: alert.state, heading: alert.heading, message: alert.message });
    }
  }
}

function openDrill(target) {
  if (drillTarget === null) drillOpener = document.activeElement;
  drillTarget = target;
  drillPanel.hidden = false;
  render();
  drillEls.title.focus();
}

function closeDrill() {
  const opener = drillOpener;
  drillTarget = null;
  drillOpener = null;
  drillPanel.hidden = true;
  if (opener && opener.isConnected) opener.focus();
}

function selectLane(laneId) {
  selectedLane = laneId;
  const item = Array.from(lanesList.children).find((li) => li.dataset.lane === laneId);
  if (item) item.scrollIntoView({ block: 'nearest' });
  render();
}

function moveLane(step) {
  const ids = shown.laneOrder;
  if (ids.length === 0) return;
  const index = ids.indexOf(selectedLane);
  const next = index < 0 ? 0 : Math.min(ids.length - 1, Math.max(0, index + step));
  selectLane(ids[next]);
}

function focusGates() {
  gatesList.tabIndex = -1;
  gatesList.scrollIntoView({ block: 'nearest' });
  gatesList.focus();
}

function isTyping(event) {
  const origin = event.composedPath()[0];
  return origin instanceof HTMLElement
    && (origin.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(origin.tagName));
}

function onKey(event) {
  if (event.ctrlKey || event.metaKey || event.altKey || palette.isOpen || isTyping(event)) return;
  if (event.key === 'Escape') {
    if (drillTarget !== null) {
      event.preventDefault();
      closeDrill();
    }
  } else if (event.key === 'j') moveLane(1);
  else if (event.key === 'k') moveLane(-1);
  else if (event.key === 'g') focusGates();
  else if (event.key === 'l') openDrill({ type: 'logs' });
}

function runCommand(id) {
  const separator = id.indexOf(':');
  const kind = separator < 0 ? '' : id.slice(0, separator);
  const value = separator < 0 ? '' : id.slice(separator + 1);
  if (kind === 'phase') {
    openDrill({ type: 'phase', phase: value });
  } else if (kind === 'task') {
    const laneId = shown.laneOrder.find((candidate) => shown.lanes[candidate].taskId === value);
    if (laneId !== undefined) {
      selectedLane = laneId;
      openDrill({ type: 'lane', lane: laneId });
    }
  } else if (kind === 'file') {
    const href = artifactHref(runId, value, token);
    if (href) window.open(href, '_blank', 'noopener');
  }
}

function bindControls() {
  lanesList.addEventListener('click', (event) => {
    const item = event.target.closest('li[data-lane]');
    if (!item) return;
    const laneId = item.dataset.lane;
    const block = event.target.closest('button.block');
    if (block) {
      selectedLane = laneId;
      openDrill({ type: 'block', lane: laneId, index: Number(block.dataset.index) });
    } else if (event.target.closest('button.lane-open')) {
      selectedLane = laneId;
      openDrill({ type: 'lane', lane: laneId });
    }
  });
  phaseStats.addEventListener('click', (event) => {
    const item = event.target.closest('li[data-phase]');
    if (item) openDrill({ type: 'phase', phase: item.dataset.phase });
  });
  follow.addEventListener('click', () => {
    following = !following;
    follow.setAttribute('aria-pressed', String(following));
    if (following) {
      shown = state;
      render();
    }
  });
  document.getElementById('drill-close').addEventListener('click', closeDrill);
  palette.addEventListener('sl-command', (event) => runCommand(event.detail.id));
  document.addEventListener('keydown', onKey);
}

function needsSummary(event) {
  if (event.kind === 'phase_entered' || event.kind === 'run_finished') return true;
  return event.kind === 'gate_evaluated' && Boolean(event.payload) && event.payload.gate === 'oracle';
}

async function loadSummary() {
  try {
    const response = await fetch(runPath(), {
      headers: { Accept: 'application/json', Authorization: 'Bearer ' + token },
      cache: 'no-store',
    });
    if (!response.ok) return;
    const detail = await response.json();
    const completion = (detail.summary && detail.summary.completion) || {};
    dispatch({
      type: 'summary',
      summary: { completion: { ready: completion.ready === true }, verdict: completion.verdict || null },
    });
  } catch (error) {
    // keep the last summary read; the next phase or oracle event asks again
  }
}

// The completion receipt is written to disk without an event, so a finished run is re-read until it is ready.
function pollSummary() {
  const model = selectView(state, Date.now());
  if (model.rail.phase === 'done' && !model.rail.receiptReady) loadSummary();
}

function scheduleSummary() {
  clearTimeout(summaryTimer);
  summaryTimer = setTimeout(loadSummary, SUMMARY_DEBOUNCE_MS);
}

function start() {
  if (!token || !runId) {
    view.showMessage(token ? 'Informe o run na URL (parâmetro run).' : 'Abra o painel com o token na URL (parâmetro t).');
    render();
    return;
  }
  view.showMessage('Aguardando eventos do run…');
  render();
  setInterval(render, TICK_MS);
  setInterval(pollSummary, SUMMARY_POLL_MS);
  loadSummary();
  connectStream({
    url: runPath() + '/events',
    token,
    getLastSeq: () => state.lastSeq,
    onEvent(event) {
      dispatch({ type: 'event', event });
      dispatch({ type: 'connection', status: 'live', at: Date.now() });
      if (needsSummary(event)) scheduleSummary();
    },
    onHeartbeat() {
      dispatch({ type: 'heartbeat', at: Date.now() });
    },
    onStatus(status) {
      dispatch({ type: 'connection', status, at: Date.now() });
    },
    signal: controller.signal,
  });
}

bindControls();
window.addEventListener('pagehide', () => controller.abort());
start();
