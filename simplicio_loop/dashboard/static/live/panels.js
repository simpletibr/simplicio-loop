// DOM renderers for the Simplicio Live iteration timeline, convergence sparkline, DoD and quality panels (issue #1403).
// Text goes in through textContent or attributes only. The timeline items property is set only when its JSON changes.
import { artifactHref, formatClock, formatDuration, setAttr, setText } from '/static/live/lanes.js';

const VERDICT_LABEL = { PROGRESS: 'progresso', STALLED: 'sem avanço' };
const DOD_LABEL = { PASS: 'aprovada', FAIL: 'reprovada', UNVERIFIED: 'não verificada' };
const QUALITY_LABELS = [
  ['tests', 'Testes'],
  ['lint', 'Lint'],
  ['coverageTrend', 'Tendência de cobertura'],
  ['flaky', 'Testes instáveis'],
  ['diff', 'Diff'],
];

function timelineState(row) {
  return row.verdict === 'STALLED' && row.state === 'RUNNING' ? 'STALLED' : row.state;
}

function iterationDetail(row) {
  const parts = [];
  if (row.durationMs !== null) parts.push('duração ' + formatDuration(row.durationMs));
  if (row.verdict !== null) parts.push('veredito ' + VERDICT_LABEL[row.verdict]);
  if (row.streak !== null) parts.push('sequência ' + row.streak + (row.fingerprint === null ? '' : ' (' + row.fingerprint + ')'));
  if (row.gatesFailing.length > 0) parts.push('falhando: ' + row.gatesFailing.join(', '));
  if (row.gatesUnverified.length > 0) parts.push('não verificados: ' + row.gatesUnverified.join(', '));
  for (const retry of row.retries) {
    const step = retry.step === null ? 'sem passo' : retry.step;
    const blocker = retry.blocker === null ? 'bloqueio não informado' : retry.blocker;
    parts.push('retentativa ' + step + ': ' + blocker);
  }
  return parts.join(' · ');
}

function timelineItems(rows) {
  return rows.map((row) => ({
    time: formatClock(row.startedAt),
    title: 'Iteração ' + row.iteration,
    state: timelineState(row),
    detail: iterationDetail(row),
  }));
}

function dodRows(dod) {
  return dod.pillars.map((pillar) => ({
    key: pillar.pillar,
    label: pillar.label,
    state: pillar.state,
    detail: pillar.detail,
    ref: pillar.ref,
  }));
}

function qualityRows(quality) {
  return QUALITY_LABELS.map(([key, label]) => ({
    key,
    label,
    state: quality[key].state,
    detail: quality[key].reason,
    ref: null,
  }));
}

// Keyed rows of sl-gate-badge: the rows are created once, then only their attributes change.
function renderBadges(list, rows, runId, token) {
  if (list.children.length !== rows.length) {
    list.replaceChildren(...rows.map(() => {
      const li = document.createElement('li');
      li.append(document.createElement('sl-gate-badge'));
      return li;
    }));
  }
  rows.forEach((row, index) => {
    const li = list.children[index];
    const badge = li.firstElementChild;
    setAttr(li, 'data-key', row.key);
    setAttr(badge, 'gate', row.label);
    setAttr(badge, 'state', row.state);
    setAttr(badge, 'reason', row.detail);
    setAttr(badge, 'href', artifactHref(runId, row.ref, token));
  });
}

// The sparkline plots the gates still pending at each finish (failing plus unverified).
function renderConvergence(sparkline, note, convergence) {
  const points = convergence.points;
  setAttr(sparkline, 'values', points.map((point) => point.failing + point.unverified).join(','));
  setAttr(sparkline, 'state', convergence.state === 'OK' ? 'RUNNING' : 'UNVERIFIED');
  let text = convergence.reason || '';
  if (points.length > 0) {
    const last = points[points.length - 1];
    text = 'Última iteração finalizada (' + last.iteration + '): ' + last.failing + ' gates falhando e ' + last.unverified + ' não verificados.';
  }
  setText(note, text);
}

export function createPanels(els) {
  let timelineJson = null;
  return {
    render(model, options) {
      const items = timelineItems(model.iterations);
      const json = JSON.stringify(items);
      if (json !== timelineJson) {
        timelineJson = json;
        els.timeline.items = items;
      }
      renderConvergence(els.convergence, els.note, model.convergence);
      renderBadges(els.dod, dodRows(model.dod), options.runId, options.token);
      setAttr(els.dod, 'aria-label', 'Definição de pronto: ' + DOD_LABEL[model.dod.state]);
      renderBadges(els.quality, qualityRows(model.quality), options.runId, options.token);
    },
  };
}
