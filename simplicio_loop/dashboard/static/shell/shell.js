// App shell of the Simplicio dashboard: sidebar, hash routes, the Tarefas and Caixa de entrada tabs, the Decisões
// queue and the properties of the open run. Reads /api/runs with the token from the URL. Text is set with
// textContent only: run data is never HTML.
import { INBOX_TABS, TASK_TABS, countInbox, countTasks, decisions, filterInbox, filterTasks, overview, runHref, viewFromHash } from '/static/shell/shell-model.js';

const POLL_MS = 5000;
const params = new URLSearchParams(window.location.search);
const token = params.get('t') || '';
const runId = params.get('run') || '';
const hasRun = Boolean(runId);
const state = { runs: [], task: 'ativas', inbox: 'todas', error: '' };

const body = document.body;
const nav = document.getElementById('shell-nav');
const alertsPanel = document.getElementById('alerts-panel');

function el(tag, attrs, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function current() {
  return viewFromHash(window.location.hash, hasRun);
}

function applyView() {
  const view = current();
  body.dataset.view = view;
  for (const node of document.querySelectorAll('[data-view]')) {
    node.dataset.shown = node.dataset.view.split(' ').includes(view) ? '1' : '0';
  }
  // The alerts list is part of the Caixa de entrada: open there, closed on the other views.
  if (alertsPanel) alertsPanel.hidden = view !== 'caixa';
  for (const link of nav.querySelectorAll('a[data-view-link]')) {
    if (link.dataset.viewLink === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  render();
}

function render() {
  const view = current();
  renderBadges();
  if (view === 'painel') renderOverview();
  if (view === 'tarefas') renderTasks();
  if (view === 'caixa') renderInbox();
  if (view === 'decisoes') renderDecisions();
  if (view === 'tarefa') renderProperties();
}

function renderBadges() {
  const counts = overview(state.runs);
  const inbox = countInbox(state.runs, Date.now());
  const values = { tarefas: counts.ativas, caixa: inbox.todas, decisoes: decisions(state.runs).length };
  for (const [view, value] of Object.entries(values)) {
    const badge = nav.querySelector('[data-badge="' + view + '"]');
    if (!badge) continue;
    badge.textContent = String(value);
    badge.hidden = value === 0;
  }
}

function renderOverview() {
  const counts = overview(state.runs);
  const values = { 'kpi-ativas': counts.ativas, 'kpi-falhas': counts.falhas, 'kpi-concluidas': counts.concluidas, 'kpi-total': counts.total };
  for (const [id, value] of Object.entries(values)) {
    const card = document.getElementById(id);
    if (card) card.setAttribute('value', String(value));
  }
  const recent = document.getElementById('painel-recent');
  if (!recent) return;
  recent.replaceChildren();
  for (const run of state.runs.slice(0, 5)) recent.append(runItem(run));
  if (!state.runs.length) recent.append(el('li', {}, state.error || 'Nenhum run ainda.'));
}

function runItem(run) {
  const link = el('a', { href: runHref(window.location.pathname, window.location.search, run.run_id) }, run.run_id);
  const status = el('span', { class: 'shell-status', 'data-state': String(run.status || '').toUpperCase() }, String(run.status || '–'));
  const repo = String(run.repo || '').split('/').filter(Boolean).pop() || '';
  const item = el('li', { class: 'shell-run' });
  item.append(link, ' ', status, ' ', el('span', { class: 'shell-muted' }, repo));
  if (run.updated_at) item.append(' ', el('time', { datetime: String(run.updated_at) }, String(run.updated_at)));
  return item;
}

// One row of tabs, each with its count. Paperclip shows the same pattern on Tasks and Inbox.
function renderTabs(container, tabs, counts, selected, onPick) {
  if (!container) return;
  container.replaceChildren();
  for (const tab of tabs) {
    const button = el('button', { type: 'button', role: 'tab', 'aria-selected': String(tab.id === selected), 'data-tab': tab.id }, tab.label + ' (' + counts[tab.id] + ')');
    button.addEventListener('click', () => onPick(tab.id));
    container.append(button);
  }
}

function fillList(list, rows, empty) {
  if (!list) return;
  list.replaceChildren();
  for (const run of rows) list.append(runItem(run));
  if (!rows.length) list.append(el('li', {}, state.error || empty));
}

function renderTasks() {
  renderTabs(document.getElementById('tarefas-tabs'), TASK_TABS, countTasks(state.runs), state.task, (id) => {
    state.task = id;
    renderTasks();
  });
  fillList(document.getElementById('tarefas-list'), filterTasks(state.runs, state.task), 'Nenhuma tarefa nesta aba.');
}

function renderInbox() {
  renderTabs(document.getElementById('caixa-tabs'), INBOX_TABS, countInbox(state.runs, Date.now()), state.inbox, (id) => {
    state.inbox = id;
    renderInbox();
  });
  fillList(document.getElementById('caixa-list'), filterInbox(state.runs, state.inbox, Date.now()), 'Nada pede atenção nesta aba.');
}

function renderDecisions() {
  fillList(document.getElementById('decisoes-list'), decisions(state.runs), 'Nenhum run esperando uma decisão.');
}

// The open run's properties, in the right-hand column Paperclip uses for an issue. Cost is shown only when measured.
function renderProperties() {
  const list = document.getElementById('props-list');
  if (!list) return;
  list.replaceChildren();
  const run = state.runs.find((row) => row && row.run_id === runId);
  if (!run) {
    list.append(el('dt', {}, 'Run'), el('dd', {}, runId || 'nenhum run aberto'));
    if (state.error) list.append(el('dt', {}, 'Aviso'), el('dd', {}, state.error));
    return;
  }
  const rows = [
    ['Status', run.status],
    ['Repositório', run.repo],
    ['Início', run.started_at],
    ['Fim', run.finished_at || 'em andamento'],
    ['Duração (s)', run.duration_s],
    ['Atualizado', run.updated_at],
    ['Custo (USD)', run.cost_usd == null ? 'não medido' : run.cost_usd],
  ];
  for (const [label, value] of rows) {
    list.append(el('dt', {}, label), el('dd', {}, value == null || value === '' ? '–' : String(value)));
  }
}

async function refresh() {
  try {
    const response = await fetch('/api/runs', { headers: { Accept: 'application/json', Authorization: 'Bearer ' + token }, cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const reply = await response.json();
    state.runs = Array.isArray(reply.runs) ? reply.runs : [];
    state.error = '';
  } catch (error) {
    state.error = 'Não foi possível ler os runs (' + error.message + '). Abra o painel com o link que tem ?t=.';
  }
  render();
}

window.addEventListener('hashchange', applyView);
// The board and coordination panels keep the markup the live page defined; the shell gives them their view here.
for (const selector of ['.board-panel', '.coord-panel']) document.querySelector(selector)?.setAttribute('data-view', 'tarefa');
applyView();
refresh();
setInterval(refresh, POLL_MS);
