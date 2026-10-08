// Simplicio Live pipeline page: reads the run from the URL, streams its events and renders the reducer view.
import { connectStream } from '/static/live/sse.js';
import { initialState, reduce, selectCommands, selectDrill, selectView } from '/static/live/reducer.js';
import { artifactHref, renderDrill, setText } from '/static/live/lanes.js';
import { bindTabs, createDrillLists } from '/static/live/drill-tabs.js';
import { deepLinkOf, parseDeepLink } from '/static/live/deeplink.js';
import { activeAlerts, applyAlertFrame, browserNotice, diffAlerts, mergeAlerts } from '/static/live/alerts.js';
import { createAlertList } from '/static/live/alerts-view.js';
import { SlAlertToast } from '/static/components/index.js';
import { createView } from '/static/live/view.js';
import { boardOf } from '/static/live/board.js';
import { createBoard } from '/static/live/board-view.js';
import { startCoordination } from '/static/coordination/boot.js';
import { startHistory } from '/static/history/history-page.js';
import { nextRunId, rotationMs, runCommands, runUrl } from '/static/live/runs-nav.js';

const SUMMARY_DEBOUNCE_MS = 250;
const TICK_MS = 1000;
const SUMMARY_POLL_MS = 500;
const TOKENS_POLL_MS = 30000;
const BOARD_POLL_MS = 3000;
const ALERT_HOUR_MS = 60 * 60 * 1000;
const THEMES = ['dark', 'light', 'contrast'];

const params = new URLSearchParams(window.location.search);
const token = params.get('t') || '';
const runId = params.get('run') || '';
const theme = params.get('theme') || '';
if (THEMES.includes(theme)) document.documentElement.setAttribute('data-sl-theme', theme);
if (params.get('tv') === '1') document.documentElement.dataset.tv = '1';

const view = createView();
const boardView = createBoard(document.getElementById('board'), document.getElementById('board-status'));
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
  receipts: document.getElementById('drill-receipts'),
  commands: document.getElementById('drill-commands'),
  copyStatus: document.getElementById('drill-copy-status'),
};
const DRILL_TAB_NAMES = ['summary', 'logs', 'receipts', 'commands', 'contract', 'context'];
// The contract and the mapper context are raw run artifacts, read when their tab opens and shown as they are.
const DRILL_ARTIFACTS = {
  contract: { file: 'task-contract.json', tree: document.getElementById('drill-contract'), note: document.getElementById('drill-contract-note') },
  context: { file: 'mapper-context.json', tree: document.getElementById('drill-context'), note: document.getElementById('drill-context-note') },
};
const drillTabs = bindTabs(
  document.getElementById('drill-tabs'),
  DRILL_TAB_NAMES.map((name) => document.getElementById('drill-tab-' + name)),
  DRILL_TAB_NAMES.map((name) => document.getElementById('drill-panel-' + name)),
  (index) => loadDrillArtifact(DRILL_TAB_NAMES[index]),
);
const drillLists = createDrillLists(drillEls);
// The alert center: the rules run on every tick; a silenced alert stays hidden for an hour, for this page only.
const silencedAlerts = {};
let alertIds = null;
// The run alerts the server sent, by id: the snapshot replaces them, raised and cleared frames change them.
let serverAlerts = {};
// The opt-in settings from dashboard.toml (/config); null until read, and the page then keeps every extra off.
let alertSettings = null;
const alertList = createAlertList({
  toggle: document.getElementById('alerts-toggle'),
  list: document.getElementById('alerts-list'),
  status: document.getElementById('alerts-status'),
}, {
  view: (alert) => openDrill(alert.ref),
  silence: (alert) => {
    silencedAlerts[alert.id] = Date.now() + ALERT_HOUR_MS;
    render();
  },
});
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
// The runs of the last GET /api/runs: the palette jumps to them and the TV mode rotates through them.
let knownRuns = [];
let rotationTimer = null;
// The on-demand artifacts the run has written, from the last run detail; null until the first detail arrives.
let drillArtifactNames = null;

function link() {
  return { runId, token };
}

function render() {
  const now = Date.now();
  const model = selectView(shown, now);
  view.render(model, { token, runId, selectedLane });
  const alerts = mergeAlerts(serverAlerts, model.connection);
  const ids = alerts.map((alert) => alert.id);
  const previous = alertIds;
  const change = previous === null ? { raised: [], cleared: [] } : diffAlerts(previous, ids);
  for (const alert of alerts) {
    if (change.raised.includes(alert.id)) {
      SlAlertToast.notify({ state: alert.severity === 'critical' ? 'STALLED' : 'UNVERIFIED', heading: alert.heading, message: alert.why });
      notifyBrowser(alert, now);
    }
  }
  alertIds = ids;
  alertList.render(activeAlerts(alerts, silencedAlerts, now), change);
  if (drillTarget !== null) {
    renderDrill(drillEls, selectDrill(shown, drillTarget, now), link());
    drillLists.render(model, link());
  }
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
  const commands = selectCommands(shown).concat(runCommands(knownRuns, runId));
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
  drillTabs.select(target.type === 'logs' ? 1 : 0);
  drillPanel.hidden = false;
  const link = deepLinkOf(runId, target);
  if (link !== null) window.history.replaceState(null, '', link);
  render();
  drillEls.title.focus();
}

function closeDrill() {
  const opener = drillOpener;
  drillTarget = null;
  drillOpener = null;
  drillPanel.hidden = true;
  window.history.replaceState(null, '', window.location.pathname + window.location.search);
  if (opener && opener.isConnected) opener.focus();
}

// A link to a drill target opens the drawer on it. replaceState does not fire hashchange, so opening and closing cannot loop.
function applyHash() {
  const target = parseDeepLink(window.location.hash, runId);
  if (target !== null) openDrill(target);
}

async function loadDrillArtifact(name) {
  const artifact = DRILL_ARTIFACTS[name];
  if (!artifact) return;
  if (drillArtifactNames !== null && !drillArtifactNames.includes(artifact.file)) {
    setText(artifact.note, 'Arquivo ainda não gerado neste run.');
    artifact.tree.data = null;
    return;
  }
  const data = await readApi('/api/runs/' + encodeURIComponent(runId) + '/artifacts/' + encodeURIComponent(artifact.file));
  if (data === null) {
    setText(artifact.note, 'Não foi possível ler o arquivo.');
    artifact.tree.data = null;
    return;
  }
  setText(artifact.note, '');
  artifact.tree.data = data;
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

function goToRun(id) {
  window.location.assign(runUrl(window.location.pathname, window.location.search, id));
}

// TV mode: every interval the page moves to the next run. Reduced motion turns the rotation off.
function startRotation() {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const interval = rotationMs(window.location.search, reduced);
  if (interval === null || rotationTimer !== null) return;
  rotationTimer = setInterval(() => {
    const next = nextRunId(knownRuns, runId);
    if (next !== null) goToRun(next);
  }, interval);
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
  } else if (kind === 'run') {
    goToRun(value);
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
  document.getElementById('alerts-toggle').addEventListener('click', () => {
    const panel = document.getElementById('alerts-panel');
    const open = panel.hidden;
    panel.hidden = !open;
    document.getElementById('alerts-toggle').setAttribute('aria-expanded', String(open));
  });
  palette.addEventListener('sl-command', (event) => runCommand(event.detail.id));
  document.addEventListener('keydown', onKey);
}

function needsSummary(event) {
  if (event.kind === 'phase_entered' || event.kind === 'run_finished') return true;
  return event.kind === 'gate_evaluated' && Boolean(event.payload) && event.payload.gate === 'oracle';
}

// quality-matrix.json is a run artifact: a missing, unreadable or unparsable file reports no receipt (receipt null).
async function loadQuality(receipts) {
  if (!(receipts || []).some((item) => item.name === 'quality-matrix.json')) {
    dispatch({ type: 'quality', receipt: null });
    return;
  }
  let receipt = null;
  try {
    const response = await fetch(runPath() + '/artifacts/quality-matrix.json', {
      headers: { Accept: 'application/json', Authorization: 'Bearer ' + token },
      cache: 'no-store',
    });
    if (response.ok) receipt = await response.json();
  } catch (error) {
    receipt = null;
  }
  dispatch({ type: 'quality', receipt });
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
    dispatch({ type: 'receipts', receipts: detail.receipts });
    dispatch({ type: 'repo', repo: detail.state && typeof detail.state.repo === 'string' ? detail.state.repo : null });
    drillArtifactNames = Array.isArray(detail.artifacts) ? detail.artifacts : null;
    loadQuality(detail.receipts);
  } catch (error) {
    // keep the last summary read; the next phase or oracle event asks again
  }
}

// The completion receipt is written to disk without an event, so a finished run is re-read until it is ready.
function pollSummary() {
  const model = selectView(state, Date.now());
  if (model.rail.phase === 'done' && !model.rail.receiptReady) loadSummary();
}

// The summary and the quality receipt are written to disk without an event, so both are read after each phase, gate or end event.
function refreshRun() {
  loadSummary();
}

function scheduleSummary() {
  clearTimeout(summaryTimer);
  summaryTimer = setTimeout(refreshRun, SUMMARY_DEBOUNCE_MS);
}

// A failed read reports no response, and the views show that as UNVERIFIED.
async function readApi(path) {
  try {
    const reply = await fetch(path, {
      headers: { Accept: 'application/json', Authorization: 'Bearer ' + token },
      cache: 'no-store',
    });
    return reply.ok ? await reply.json() : null;
  } catch (error) {
    return null;
  }
}

async function loadTokens() {
  dispatch({ type: 'tokens', response: await readApi('/api/tokens') });
}

// The run budget and token usage are derived from the event stream, so they refresh on the tokens cadence.
async function loadBudget() {
  if (!runId) return;
  dispatch({ type: 'budget', response: await readApi('/api/runs/' + encodeURIComponent(runId) + '/budget') });
}

// The stage-agents roles come from the contract, which does not change while the page is open: one read per page.
// Browser notifications are opt-in twice: dashboard.toml turns them on, then the user grants the permission.
function notifyBrowser(alert, now) {
  if (typeof Notification === 'undefined') return;
  const notice = browserNotice(alert, alertSettings, Notification.permission, silencedAlerts, now);
  if (notice === null) return;
  try {
    new Notification(notice.title, { body: notice.body, tag: notice.tag });
  } catch (error) {
    // A browser that refuses the constructor keeps the toast and the alert center.
  }
}

async function loadAlertSettings() {
  alertSettings = await readApi(runPath() + '/config');
  const button = document.getElementById('alerts-notify');
  const ask = alertSettings !== null && alertSettings.browser_notifications === true
    && typeof Notification !== 'undefined' && Notification.permission === 'default';
  button.hidden = !ask;
  button.addEventListener('click', async () => {
    await Notification.requestPermission();
    button.hidden = true;
  }, { once: true });
}

async function loadAgents() {
  dispatch({ type: 'agents', response: await readApi('/api/agents') });
}

// The board lists every run, so it loads with or without a run in the URL; a failed read keeps the last render.
async function loadBoard() {
  const reply = await readApi('/api/runs');
  if (reply === null) {
    setText(document.getElementById('board-status'), 'Não foi possível atualizar o quadro.');
    return;
  }
  const runs = Array.isArray(reply.runs) ? reply.runs : [];
  knownRuns = runs;
  syncPalette();
  boardView.render(boardOf(runs, Date.now()), { runId, token, pathname: window.location.pathname });
}

function start() {
  if (token) {
    loadBoard();
    setInterval(loadBoard, BOARD_POLL_MS);
    startCoordination(readApi);
    startHistory(readApi, setText);
    startRotation();
  }
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
  loadTokens();
  setInterval(loadTokens, TOKENS_POLL_MS);
  loadBudget();
  setInterval(loadBudget, TOKENS_POLL_MS);
  loadAgents();
  loadAlertSettings();
  applyHash();
  window.addEventListener('hashchange', applyHash);
  connectStream({
    url: runPath() + '/events',
    token,
    getLastSeq: () => state.lastSeq,
    onAlert(name, payload) {
      serverAlerts = applyAlertFrame(serverAlerts, name, payload);
      // A snapshot is a baseline: the alerts it lists were raised before this page connected, so they are not news.
      if (name === 'alert_snapshot') alertIds = null;
      render();
    },
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
