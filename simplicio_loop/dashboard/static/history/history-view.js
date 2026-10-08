// The history view of the Simplicio Live page: past runs with a compare picker, a side-by-side comparison, trend lines,
// an activity heatmap and the lessons from learn. The five sections are built once in createHistory() and updated in
// place on every render, so a focused control (a checkbox, the compare button, a scrollable region) keeps its focus.
// Text goes in through textContent and attributes only.
import { rowsOf, heatLevels, trendSeries, deltaText, phaseBars } from './history-model.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const HOURS = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, '0'));
const TRENDS = [
  { key: 'complete_rate', label: 'Taxa de conclusão' },
  { key: 'iterations_per_task', label: 'Iterações por tarefa' },
  { key: 'cost_per_task_usd', label: 'Custo por tarefa (USD)' },
];
// One shape per tone, so a lamp is never told apart by colour alone. The shapes match the state lamps of the kit.
const SHAPE = {
  running: 'play',
  pass: 'check',
  fail: 'cross',
  unverified: 'diamond',
  stalled: 'pause',
  blocked: 'barred',
  pending: 'ring',
};
const RUN_HEADERS = ['Comparar', 'Run', 'Veredito', 'Duração', 'Iterações', 'Custo', 'Início'];
const METRIC_HEADERS = ['Métrica', 'A', 'B', 'Delta'];
const CHART_W = 320;
const CHART_H = 96;
const PAD = 8;
const MARKER_R = 4;
const EMPTY_RUNS = 'Nenhum run no histórico.';
const COMPARE_PROMPT = 'Escolha dois runs na tabela para comparar.';
const PHASE_NOTE = 'Os runs pararam em fases diferentes.';
const NO_TRENDS = 'Sem tendências ainda.';
const NO_ACTIVITY = 'Sem dados de atividade.';
const NO_LESSONS = 'Nenhuma lição registrada.';

let instances = 0;

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

function element(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.setAttribute('class', cls);
  return el;
}

function svgElement(tag, cls) {
  const el = document.createElementNS(SVG_NS, tag);
  if (cls) el.setAttribute('class', cls);
  return el;
}

// A part without a value is emptied and hidden, so it takes no room and says nothing.
function show(el, text) {
  const shown = text !== null && text !== undefined && text !== '';
  setText(el, shown ? text : '');
  setAttr(el, 'hidden', shown ? null : true);
}

function dash(value) {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

function headerCell(label) {
  const th = element('th');
  th.setAttribute('scope', 'col');
  setText(th, label);
  return th;
}

// Keeps the first `count` views of a list, appends new ones at the end and removes the extra ones from the end.
function fit(parent, views, count, make) {
  while (views.length < count) {
    const view = make();
    views.push(view);
    parent.append(view.node);
  }
  while (views.length > count) views.pop().node.remove();
  return views;
}

// Puts nodes in model order. A node already in place is not moved, and nodes left over are removed.
function placeNodes(parent, nodes) {
  nodes.forEach((node, index) => {
    if (parent.children[index] !== node) parent.insertBefore(node, parent.children[index] ?? null);
  });
  while (parent.children.length > nodes.length) parent.children[nodes.length].remove();
}

function section(prefix, id, title) {
  const node = element('section', 'hist-section');
  const heading = element('h3');
  const headingId = prefix + id + '-title';
  heading.setAttribute('id', headingId);
  setText(heading, title);
  node.setAttribute('aria-labelledby', headingId);
  node.append(heading);
  return { node, headingId };
}

// The wrapping section already names a landmark from its heading, so the scroll region gets its own name.
function scrollRegion(label) {
  const region = element('div', 'hist-scroll');
  region.setAttribute('role', 'region');
  region.setAttribute('tabindex', '0');
  region.setAttribute('aria-label', label);
  return region;
}

// ---- Runs -------------------------------------------------------------------------------------------------------

function buildRuns(prefix) {
  const { node } = section(prefix, 'runs', 'Histórico de runs');
  const region = scrollRegion('Tabela de runs, rolável');
  const table = element('table', 'hist-table');
  const thead = element('thead');
  const head = element('tr');
  for (const label of RUN_HEADERS) head.append(headerCell(label));
  thead.append(head);
  const tbody = element('tbody');
  table.append(thead, tbody);
  region.append(table);
  const hint = element('p', 'hist-hint');
  const button = element('button', 'hist-compare');
  button.setAttribute('type', 'button');
  setText(button, 'Comparar 2 runs');
  const view = { node, tbody, hint, button, rows: new Map(), selected: new Set(), order: [], handlers: {} };
  button.addEventListener('click', () => {
    const picked = view.order.filter((id) => view.selected.has(id));
    if (picked.length === 2 && typeof view.handlers.onCompare === 'function') {
      view.handlers.onCompare(picked[0], picked[1]);
    }
  });
  node.append(region, hint, button);
  return view;
}

function updateCompare(view) {
  const count = view.selected.size;
  setAttr(view.button, 'disabled', count === 2 ? null : true);
  setText(view.hint, count === 2 ? 'Dois runs escolhidos.'
    : count + (count === 1 ? ' escolhido: escolha exatamente dois.' : ' escolhidos: escolha exatamente dois.'));
}

function newRunRow(view, runId) {
  const tr = element('tr');
  const pick = element('td', 'hist-pick');
  const box = element('input');
  box.setAttribute('type', 'checkbox');
  box.setAttribute('aria-label', 'Comparar ' + runId);
  box.addEventListener('change', () => {
    if (box.checked) view.selected.add(runId);
    else view.selected.delete(runId);
    updateCompare(view);
  });
  pick.append(box);
  const run = element('td', 'hist-run');
  const verdict = element('td', 'hist-verdict');
  const lamp = element('span', 'lamp');
  const glyph = element('span', 'lamp-glyph');
  glyph.setAttribute('aria-hidden', 'true');
  const lampText = element('span', 'lamp-text');
  lamp.append(glyph, lampText);
  verdict.append(lamp);
  const duration = element('td');
  const iterations = element('td');
  const cost = element('td');
  const started = element('td');
  tr.append(pick, run, verdict, duration, iterations, cost, started);
  return { tr, box, run, lamp, lampText, duration, iterations, cost, started };
}

function fillRun(row, data, selected) {
  const named = String(data.tone ?? '').toLowerCase();
  const tone = Object.hasOwn(SHAPE, named) ? named : 'pending';
  setText(row.run, dash(data.runId));
  setAttr(row.lamp, 'class', 'lamp lamp-' + tone);
  setAttr(row.lamp, 'data-shape', SHAPE[tone]);
  setText(row.lampText, dash(data.verdict));
  setText(row.duration, dash(data.durationText));
  setText(row.iterations, dash(data.iterations));
  setText(row.cost, dash(data.costText));
  setText(row.started, dash(data.startedAt));
  if (row.box.checked !== selected) row.box.checked = selected;
}

function renderRuns(view, runs, statusEl) {
  const present = new Set(runs.map((run) => run.runId));
  view.order = runs.map((run) => run.runId);
  for (const id of [...view.selected]) {
    if (!present.has(id)) view.selected.delete(id);
  }
  for (const [id, row] of view.rows) {
    if (!present.has(id)) {
      row.tr.remove();
      view.rows.delete(id);
    }
  }
  const nodes = runs.map((run) => {
    let row = view.rows.get(run.runId);
    if (row === undefined) {
      row = newRunRow(view, run.runId);
      view.rows.set(run.runId, row);
    }
    fillRun(row, run, view.selected.has(run.runId));
    return row.tr;
  });
  placeNodes(view.tbody, nodes);
  updateCompare(view);
  setText(statusEl, runs.length === 0 ? EMPTY_RUNS : '');
}

// ---- Comparison -------------------------------------------------------------------------------------------------

function buildCompare(prefix) {
  const { node } = section(prefix, 'compare', 'Comparação');
  const note = element('p', 'hist-note');
  const empty = element('p', 'hist-empty');
  const table = element('table', 'hist-compare-table');
  const thead = element('thead');
  const head = element('tr');
  for (const label of METRIC_HEADERS) head.append(headerCell(label));
  thead.append(head);
  const tbody = element('tbody');
  table.append(thead, tbody);
  const phasesHeading = element('h4');
  setText(phasesHeading, 'Fases');
  const phases = element('ul', 'hist-phases');
  node.append(note, empty, table, phasesHeading, phases);
  return { node, note, empty, table, tbody, phasesHeading, phases, metrics: [], phaseRows: [] };
}

function metricRow() {
  const tr = element('tr');
  const label = element('th');
  label.setAttribute('scope', 'row');
  const a = element('td');
  const b = element('td');
  const delta = element('td');
  tr.append(label, a, b, delta);
  return { node: tr, label, a, b, delta };
}

function barView(run) {
  const node = element('div', 'hist-bar');
  const track = element('span', 'hist-track');
  const fill = element('span', 'hist-fill');
  const label = element('span', 'hist-bar-label');
  track.append(fill);
  node.append(track, label);
  return { run, node, fill, label };
}

function phaseRow() {
  const node = element('li', 'hist-phase');
  const name = element('span', 'hist-phase-name');
  const bars = element('div', 'hist-bars');
  const bar = [barView('A'), barView('B')];
  bars.append(bar[0].node, bar[1].node);
  node.append(name, bars);
  return { node, name, bar };
}

function fillBar(view, pct) {
  const reached = Number.isFinite(pct);
  const share = reached ? Math.min(100, Math.max(0, pct)) : 0;
  setText(view.label, view.run + ': ' + (reached ? pct + '%' : 'não alcançada'));
  setAttr(view.node, 'class', 'hist-bar hist-bar-' + view.run.toLowerCase() + (reached ? '' : ' hist-bar-empty'));
  view.fill.style.setProperty('--fill', share + '%');
}

// The API sends compare.metrics as {key: {a, b, delta}}; the table shows them in this order with a label and a unit kind.
const METRIC_COLUMNS = [
  ['duration_s', 'Duração', 'seconds'], ['iterations', 'Iterações', 'count'], ['stalls', 'Stalls', 'count'],
  ['tests_passed', 'Testes aprovados', 'count'], ['tests_failed', 'Testes com falha', 'count'],
  ['tokens', 'Tokens', 'count'], ['cost_usd', 'Custo', 'usd'],
];

function metricList(metrics) {
  if (!metrics || typeof metrics !== 'object') return [];
  return METRIC_COLUMNS.filter(([key]) => metrics[key]).map(([key, label, kind]) => ({ ...metrics[key], label, kind }));
}

function renderCompare(view, compare) {
  const paired = compare !== null && compare !== undefined;
  show(view.empty, paired ? null : COMPARE_PROMPT);
  show(view.note, paired && compare.comparable === false ? PHASE_NOTE : null);
  setAttr(view.table, 'hidden', paired ? null : true);
  setAttr(view.phasesHeading, 'hidden', paired ? null : true);
  setAttr(view.phases, 'hidden', paired ? null : true);
  const metrics = paired ? metricList(compare.metrics) : [];
  const bars = paired ? phaseBars(compare) : [];
  fit(view.tbody, view.metrics, metrics.length, metricRow);
  metrics.forEach((metric, index) => {
    const row = view.metrics[index];
    setText(row.label, dash(metric.label ?? metric.key));
    setText(row.a, dash(metric.a));
    setText(row.b, dash(metric.b));
    setText(row.delta, deltaText(metric, metric.kind));
  });
  fit(view.phases, view.phaseRows, bars.length, phaseRow);
  bars.forEach((bar, index) => {
    const row = view.phaseRows[index];
    setText(row.name, dash(bar.phase));
    fillBar(row.bar[0], bar.aPct);
    fillBar(row.bar[1], bar.bPct);
  });
}

// ---- Trends -----------------------------------------------------------------------------------------------------

function trendChart(spec) {
  const node = element('figure', 'hist-trend');
  const caption = element('figcaption');
  setText(caption, spec.label);
  const svg = svgElement('svg', 'hist-chart');
  svg.setAttribute('viewBox', '0 0 ' + CHART_W + ' ' + CHART_H);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', spec.label);
  const lines = svgElement('g', 'hist-lines');
  const dots = svgElement('g', 'hist-dots');
  svg.append(lines, dots);
  const list = element('ol', 'hist-trend-values');
  node.append(caption, svg, list);
  return { key: spec.key, node, svg, lines, dots, list, lineViews: [], dotViews: [], items: [] };
}

function buildTrends(prefix) {
  const { node } = section(prefix, 'trends', 'Tendências');
  const note = element('p', 'hist-empty');
  const grid = element('div', 'hist-trends');
  const charts = TRENDS.map(trendChart);
  grid.append(...charts.map((chart) => chart.node));
  node.append(note, grid);
  return { node, note, charts };
}

// Points are grouped into runs between null values, so a missing value breaks the line instead of bridging it.
function segmentsOf(values, x, y) {
  const segments = [];
  let current = [];
  values.forEach((value, index) => {
    if (Number.isFinite(value)) {
      current.push([x(index), y(value)]);
    } else if (current.length > 0) {
      segments.push(current);
      current = [];
    }
  });
  if (current.length > 0) segments.push(current);
  return segments;
}

function fillChart(chart, series) {
  const values = series.values;
  const finite = values.filter((value) => Number.isFinite(value));
  const lo = finite.length > 0 ? Math.min(...finite) : 0;
  const hi = finite.length > 0 ? Math.max(...finite) : 0;
  const x = (index) => (values.length <= 1 ? CHART_W / 2
    : PAD + (index * (CHART_W - 2 * PAD)) / (values.length - 1));
  const y = (value) => (hi === lo ? CHART_H / 2
    : PAD + (CHART_H - 2 * PAD) * (1 - (value - lo) / (hi - lo)));
  const segments = segmentsOf(values, x, y);
  const dots = values.flatMap((value, index) => (Number.isFinite(value) ? [[x(index), y(value)]] : []));
  chart.lineViews = fit(chart.lines, chart.lineViews, segments.length, () => ({ node: svgElement('polyline', 'hist-trend-line') }));
  segments.forEach((points, index) => {
    setAttr(chart.lineViews[index].node, 'points', points.map(([px, py]) => px + ',' + py).join(' '));
  });
  chart.dotViews = fit(chart.dots, chart.dotViews, dots.length, () => {
    const node = svgElement('circle', 'hist-trend-dot');
    node.setAttribute('r', String(MARKER_R));
    return { node };
  });
  dots.forEach(([cx, cy], index) => {
    setAttr(chart.dotViews[index].node, 'cx', cx);
    setAttr(chart.dotViews[index].node, 'cy', cy);
  });
  chart.items = fit(chart.list, chart.items, values.length, () => ({ node: element('li') }));
  values.forEach((value, index) => {
    const label = series.labels[index] ?? String(index + 1);
    const text = Number.isFinite(value) ? String(Math.round(value * 100) / 100) : 'sem dado';
    setText(chart.items[index].node, label + ': ' + text);
  });
}

function renderTrends(view, trends) {
  show(view.note, trends === null || trends === undefined ? NO_TRENDS : null);
  for (const chart of view.charts) {
    const series = trends === null || trends === undefined ? { labels: [], values: [] } : trendSeries(trends, chart.key);
    fillChart(chart, series);
  }
}

// ---- Activity ---------------------------------------------------------------------------------------------------

function buildActivity(prefix) {
  const { node } = section(prefix, 'activity', 'Atividade');
  const note = element('p', 'hist-empty');
  const region = scrollRegion('Tabela de atividade, rolável');
  const table = element('table', 'hist-heat');
  const thead = element('thead');
  const head = element('tr');
  const corner = element('th');
  const cornerText = element('span', 'sr-only');
  setText(cornerText, 'Dia da semana');
  corner.append(cornerText);
  head.append(corner);
  for (const hour of HOURS) head.append(headerCell(hour));
  thead.append(head);
  const tbody = element('tbody');
  const days = DAYS.map((day) => {
    const tr = element('tr');
    const label = element('th');
    label.setAttribute('scope', 'row');
    setText(label, day);
    const cells = HOURS.map(() => element('td', 'hist-cell'));
    tr.append(label, ...cells);
    tbody.append(tr);
    return cells;
  });
  table.append(thead, tbody);
  region.append(table);
  const legend = element('p', 'hist-legend');
  const swatches = [0, 1, 2, 3, 4].map((level) => {
    const swatch = element('span', 'hist-swatch');
    swatch.setAttribute('aria-hidden', 'true');
    setAttr(swatch, 'data-level', String(level));
    return swatch;
  });
  const least = element('span');
  setText(least, 'Menos');
  const most = element('span');
  setText(most, 'Mais');
  legend.append(least, ...swatches, most);
  node.append(note, region, legend);
  return { node, note, days };
}

function renderActivity(view, heatmap) {
  const known = heatmap !== null && heatmap !== undefined;
  show(view.note, known ? null : NO_ACTIVITY);
  const levels = known ? heatLevels(heatmap) : null;
  view.days.forEach((cells, day) => {
    cells.forEach((cell, hour) => {
      const count = known ? heatmap[day][hour] : null;
      setAttr(cell, 'data-level', levels === null ? '0' : String(levels[day][hour]));
      const label = DAYS[day] + ' ' + HOURS[hour] + 'h: ' + (count === null ? 'sem dado' : count + ' runs');
      setAttr(cell, 'aria-label', label);
      setAttr(cell, 'title', label);
    });
  });
}

// ---- Lessons ----------------------------------------------------------------------------------------------------

function lessonItem() {
  const node = element('li', 'hist-lesson');
  const text = element('span', 'lesson-text');
  const hits = element('span', 'lesson-hits');
  node.append(text, hits);
  return { node, text, hits };
}

function buildLessons(prefix) {
  const { node } = section(prefix, 'lessons', 'Lições do learn');
  const empty = element('p', 'hist-empty');
  const list = element('ul', 'hist-lessons');
  node.append(empty, list);
  return { node, empty, list, items: [] };
}

function renderLessons(view, lessons) {
  const rows = lessons ?? [];
  show(view.empty, rows.length === 0 ? NO_LESSONS : null);
  setAttr(view.list, 'hidden', rows.length === 0 ? true : null);
  view.items = fit(view.list, view.items, rows.length, lessonItem);
  rows.forEach((lesson, index) => {
    const item = view.items[index];
    setText(item.text, dash(lesson.lesson));
    show(item.hits, lesson.hit_count === null || lesson.hit_count === undefined ? null : 'x' + lesson.hit_count);
  });
}

// ---- Entry point ------------------------------------------------------------------------------------------------

export function createHistory(root, statusEl) {
  instances += 1;
  const prefix = 'hist' + instances + '-';
  const runs = buildRuns(prefix);
  const compare = buildCompare(prefix);
  const trends = buildTrends(prefix);
  const activity = buildActivity(prefix);
  const lessons = buildLessons(prefix);
  root.append(runs.node, compare.node, trends.node, activity.node, lessons.node);
  return {
    render(data, handlers) {
      runs.handlers = handlers ?? {};
      renderRuns(runs, rowsOf(data.records ?? []), statusEl);
      renderCompare(compare, data.compare ?? null);
      renderTrends(trends, data.trends ?? null);
      renderActivity(activity, data.heatmap ?? null);
      renderLessons(lessons, data.lessons ?? []);
    },
  };
}
