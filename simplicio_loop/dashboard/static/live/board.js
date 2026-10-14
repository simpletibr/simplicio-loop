// Board model for the Simplicio Live dashboard. Groups the run summaries of GET /api/runs into the eight phase
// columns and one off-track column. Pure: no DOM and no clock. The caller passes nowMs.

export const BOARD_PHASES = ['intake', 'mapping', 'planning', 'executing', 'validating', 'watching', 'delivering', 'done'];
export const OFF_TRACK = 'off';
export const COLUMN_LABELS = {
  intake: 'Contrato',
  mapping: 'Mapeamento',
  planning: 'Plano',
  executing: 'Execução',
  validating: 'Validação',
  watching: 'Watcher',
  delivering: 'Entrega',
  done: 'Concluído',
  off: 'Fora do trilho',
};

const COLUMN_KEYS = [...BOARD_PHASES, OFF_TRACK];
const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export function columnOf(phase) {
  return BOARD_PHASES.includes(phase) ? phase : OFF_TRACK;
}

function ageOf(updatedAt, nowMs) {
  const updated = Date.parse(updatedAt);
  return Number.isNaN(updated) ? null : Math.max(0, nowMs - updated);
}

function cardOf(row, nowMs) {
  return {
    runId: row.run_id,
    phase: row.phase,
    state: row.progress_status || 'UNVERIFIED',
    percent: row.percent ?? null,
    currentAction: row.current_action ?? null,
    repo: row.repo ?? null,
    updatedAt: row.updated_at ?? null,
    ageMs: ageOf(row.updated_at, nowMs),
  };
}

export function boardOf(runs, nowMs) {
  const rows = Array.isArray(runs) ? runs : [];
  const columns = COLUMN_KEYS.map((key) => ({ key, label: COLUMN_LABELS[key], count: 0, cards: [] }));
  const byKey = new Map(columns.map((column) => [column.key, column]));
  for (const row of rows) {
    const column = byKey.get(columnOf(row.phase));
    column.cards.push(cardOf(row, nowMs));
    column.count += 1;
  }
  return { total: rows.length, columns };
}

// A run id becomes a URL query value only when it is a plain identifier: no slash, no space, no leading dot or dash.
export function runHref(runId, token, pathname) {
  if (typeof runId !== 'string' || !RUN_ID.test(runId)) return null;
  return pathname + '?run=' + encodeURIComponent(runId) + '&t=' + encodeURIComponent(token);
}
