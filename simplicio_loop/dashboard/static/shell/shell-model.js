// App shell for the Simplicio dashboard, in the layout of Paperclip: a sidebar of sections, status tabs on the
// task (run) list, an inbox and a decisions queue. Pure: no DOM, no location, no clock.

export const VIEWS = [
  { id: 'painel', label: 'Painel', hint: 'Visão geral dos runs' },
  { id: 'tarefas', label: 'Tarefas', hint: 'Runs por estado' },
  { id: 'tarefa', label: 'Tarefa', hint: 'Detalhe do run aberto' },
  { id: 'caixa', label: 'Caixa de entrada', hint: 'Runs que pedem atenção' },
  { id: 'decisoes', label: 'Decisões', hint: 'Runs bloqueados que esperam uma escolha' },
  { id: 'custos', label: 'Custos', hint: 'Economia de tokens e agentes' },
  { id: 'historico', label: 'Histórico', hint: 'Runs anteriores e tendências' },
];

// Paperclip's Tasks tabs: Active, Backlog, Done, All.
export const TASK_TABS = [
  { id: 'ativas', label: 'Ativas' },
  { id: 'backlog', label: 'Na fila' },
  { id: 'concluidas', label: 'Concluídas' },
  { id: 'todas', label: 'Todas' },
];

// Paperclip's Inbox tabs, with the signals a run has: recent (updated in the last day), blocked, failed.
export const INBOX_TABS = [
  { id: 'todas', label: 'Todas' },
  { id: 'recentes', label: 'Recentes' },
  { id: 'bloqueadas', label: 'Bloqueadas' },
  { id: 'falhas', label: 'Falhas' },
];

const DAY_MS = 24 * 60 * 60 * 1000;
const ACTIVE = new Set(['RUNNING']);
const BACKLOG = new Set(['QUEUED', 'PENDING']);
const FAILED = new Set(['FAIL', 'ERROR']);
const BLOCKED = new Set(['BLOCKED']);

export function viewFromHash(hash, hasRun) {
  const id = String(hash || '').replace(/^#\/?/, '');
  if (VIEWS.some((view) => view.id === id)) return id;
  return hasRun ? 'tarefa' : 'painel';
}

function key(status) {
  return String(status || '').toUpperCase();
}

// Which task tab a status belongs to. Terminal states that did not fail are Concluídas.
export function taskGroup(status) {
  if (ACTIVE.has(key(status))) return 'ativas';
  if (BACKLOG.has(key(status))) return 'backlog';
  return 'concluidas';
}

export function isFailed(status) {
  return FAILED.has(key(status));
}

export function isBlocked(status) {
  return BLOCKED.has(key(status));
}

// A decision is a run blocked on a choice that a person has to make.
export function isDecision(run) {
  return Boolean(run) && isBlocked(run.status);
}

function clean(runs) {
  return Array.isArray(runs) ? runs.filter(Boolean) : [];
}

export function filterTasks(runs, tab) {
  const rows = clean(runs);
  if (tab === 'todas') return rows;
  return rows.filter((row) => taskGroup(row.status) === tab);
}

export function countTasks(runs) {
  const rows = clean(runs);
  const counts = { ativas: 0, backlog: 0, concluidas: 0, todas: rows.length };
  for (const row of rows) counts[taskGroup(row.status)] += 1;
  return counts;
}

// Inbox rows. "Todas" is the attention queue (blocked or failed); "Recentes" is any run updated in the last day.
// The time is passed in by the caller, so the rule stays pure.
export function filterInbox(runs, tab, now) {
  const rows = clean(runs);
  const attention = rows.filter((row) => isBlocked(row.status) || isFailed(row.status));
  if (tab === 'todas') return attention;
  if (tab === 'bloqueadas') return attention.filter((row) => isBlocked(row.status));
  if (tab === 'falhas') return attention.filter((row) => isFailed(row.status));
  return rows.filter((row) => isRecent(row, now));
}

export function isRecent(run, now) {
  const updated = Date.parse(run && run.updated_at);
  if (!Number.isFinite(updated) || !Number.isFinite(now)) return false;
  return now - updated <= DAY_MS;
}

export function countInbox(runs, now) {
  const rows = clean(runs);
  return {
    todas: rows.filter((row) => isBlocked(row.status) || isFailed(row.status)).length,
    recentes: rows.filter((row) => isRecent(row, now)).length,
    bloqueadas: rows.filter((row) => isBlocked(row.status)).length,
    falhas: rows.filter((row) => isFailed(row.status)).length,
  };
}

export function decisions(runs) {
  return clean(runs).filter(isDecision);
}

// The numbers of the Painel, the same ones the sidebar badges show.
export function overview(runs) {
  const rows = clean(runs);
  return {
    ativas: rows.filter((row) => taskGroup(row.status) === 'ativas').length,
    falhas: rows.filter((row) => isFailed(row.status) || isBlocked(row.status)).length,
    concluidas: rows.filter((row) => taskGroup(row.status) === 'concluidas').length,
    total: rows.length,
  };
}

export function runHref(pathname, search, runId) {
  const params = new URLSearchParams(search);
  params.set('run', runId);
  return pathname + '?' + params.toString() + '#tarefa';
}
