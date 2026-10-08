// Simplicio Live pipeline page: reads the run from the URL, streams its events and renders the reducer view.
import { connectStream } from '/static/live/sse.js';
import { initialState, reduce, selectView } from '/static/live/reducer.js';
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

const view = createView();
const controller = new AbortController();
let state = initialState(runId);
let summaryTimer = null;

function runPath() {
  return '/api/runs/' + encodeURIComponent(runId);
}

function render() {
  view.render(selectView(state, Date.now()), { token, runId });
  if (document.documentElement.dataset.ready !== '1') document.documentElement.dataset.ready = '1';
}

function dispatch(action) {
  const before = state.lastSeq;
  state = reduce(state, action);
  if (state.lastSeq !== before) document.body.dataset.lastSeq = String(state.lastSeq);
  render();
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

window.addEventListener('pagehide', () => controller.abort());
start();
