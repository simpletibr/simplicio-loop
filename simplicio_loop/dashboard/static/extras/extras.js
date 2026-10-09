// Extras panel: maps the run extras reply and the stage-agents reply to seven labelled rows and renders them into #live-extras.
// Only a measured value earns PASS; anything else is UNVERIFIED with the reason it could not be measured.
// The stage-agents breakdown (issue #1550) adds widgets under the seven rows: tokens by phase/lane/model as stacked bars,
// cost per task and per iteration, the agent map and a sparkline of the polled token total. Every name is shown with
// textContent; a bar width is a clamped percent set through the CSSOM, never a style attribute.
const SCHEMA = 'simplicio.dashboard-extras/v1';
const STAGE_SCHEMA = 'simplicio.dashboard-stage-agents/v1';
const POLL_MS = 3000;
const LABELS = ['Último comando medido', 'Comando em execução', 'Contrato por tarefa', 'Modelo por lane', 'Batimento do lease', 'Agentes por etapa', 'Custo do run'];
const NO_COMMAND = 'nenhum teste ou lint medido';
const NO_RUNNING = 'nenhum command_started medido';
const NO_TASKS = 'task-contract.json sem tarefas';
const NO_TOKENS = 'sem token_usage medido';
const NO_HEARTBEAT = 'sem batimento do lease medido';
const NO_STAGES = 'sem token_usage por etapa medido';
const NO_COST = 'custo do run não estimado';
const NO_CLAIMS = 'nenhum worker_claimed no run';
const NO_LEASE = 'worker_claimed sem lease_id';
const NO_SLOTS = 'slots não medidos';
const NO_BREAKDOWN_TOKENS = 'tokens do provedor não medidos';
const MAX_POINTS = 60;
const SEGMENT_CLASSES = 6;
const MAX_ROWS = 20;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = (value) => typeof value === 'string' && value.trim() !== '';
const isCount = (value) => Number.isFinite(value) && value >= 0;
const isOthers = (row) => Number.isInteger(row.others) && row.others > 0;
const countOf = (row) => (isOthers(row) ? row.others : 1);

function commandOf(value) {
  if (!isObject(value) || !isText(value.command)) return { state: 'UNVERIFIED', text: NO_COMMAND };
  const text = isText(value.kind) ? value.command + ' (' + value.kind + ')' : value.command;
  return { state: 'PASS', text };
}

function tasksOf(value) {
  const tasks = Array.isArray(value)
    ? value.filter((task) => isObject(task) && isText(task.task_id) && typeof task.title === 'string')
    : [];
  if (tasks.length === 0) return { state: 'UNVERIFIED', text: NO_TASKS };
  return { state: 'PASS', text: tasks.map((task) => task.task_id + ': ' + task.title).join('; ') };
}

function modelsOf(value) {
  const models = Array.isArray(value)
    ? value.filter((row) => isObject(row) && isText(row.lane) && isText(row.model)
      && isCount(row.input_tokens) && isCount(row.output_tokens))
    : [];
  if (models.length === 0) return { state: 'UNVERIFIED', text: NO_TOKENS };
  const text = models
    .map((row) => row.lane + ': ' + row.model + ', entrada ' + row.input_tokens + ', saída ' + row.output_tokens)
    .join('; ');
  return { state: 'PASS', text };
}

function heartbeatOf(value) {
  const reason = isObject(value) && isText(value.reason) ? value.reason : NO_HEARTBEAT;
  const live = isObject(value) && value.state === 'PASS' && isText(value.reason);
  return { state: live ? 'PASS' : 'UNVERIFIED', text: reason };
}

function runningOf(value) {
  const reason = isObject(value) && isText(value.reason) ? value.reason : NO_RUNNING;
  const live = isObject(value) && value.state === 'PASS' && isText(value.reason);
  return { state: live ? 'PASS' : 'UNVERIFIED', text: reason };
}

// Model and tokens are measured; role and effort are the model-roles table default and say so; the cost of a stage is always an estimate.
function stageText(row) {
  const usd = Number.isFinite(row.cost_usd)
    ? 'US$ ' + row.cost_usd.toFixed(4) + ' estimado'
    : 'custo UNVERIFIED (' + (isText(row.reason) ? row.reason : NO_COST) + ')';
  const tokens = ', entrada ' + (isCount(row.tokens_in) ? row.tokens_in : 0) + ', saída ' + (isCount(row.tokens_out) ? row.tokens_out : 0);
  if (isOthers(row)) return 'outros (' + row.others + '):' + tokens.slice(1) + ', ' + usd;
  const who = isText(row.role) ? row.role + (isText(row.effort) ? '/' + row.effort : '') + ' (padrão da tabela)' : 'sem papel';
  return (isText(row.phase) ? row.phase : 'sem fase') + ': ' + who + ' ' + (isText(row.model) ? row.model : 'sem modelo')
    + tokens + ', ' + usd;
}

function stagesOf(stages) {
  const rows = isObject(stages) && stages.schema === STAGE_SCHEMA && Array.isArray(stages.rows)
    ? stages.rows.filter(isObject) : [];
  if (rows.length === 0) return { state: 'UNVERIFIED', text: NO_STAGES };
  const limited = foldRows(rows);
  return { state: limited.some((row) => Number.isFinite(row.cost_usd)) ? 'ESTIMADO' : 'UNVERIFIED', text: limited.map(stageText).join('; ') };
}

function runCostOf(stages) {
  const cost = isObject(stages) && stages.schema === STAGE_SCHEMA && isObject(stages.cost) ? stages.cost : {};
  if (Number.isFinite(cost.usd)) return { state: 'ESTIMADO', text: 'US$ ' + cost.usd.toFixed(4) + ' estimado' };
  return { state: 'UNVERIFIED', text: isText(cost.reason) ? cost.reason : NO_COST };
}

// Share of part in total as a percent clamped to 0..100; anything that is not a finite positive total reads as 0.
export function percentOf(part, total) {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(100, Math.max(0, (part / total) * 100));
}

// The polled-total history: a new array holding at most the last 60 points, so the sparkline cannot grow.
export function pushPoint(history, value) {
  return history.concat([value]).slice(-MAX_POINTS);
}

const NONE = { phase: 'sem fase', lane: 'sem lane', model: 'sem modelo', task: 'sem tarefa', iteration: 'sem iteração' };

function nameOf(row, none) {
  if (isOthers(row)) return 'outros (' + row.others + ')';
  if (isText(row.key)) return row.key;
  if (Number.isInteger(row.key) && row.key >= 0) {
    return 'iteração ' + row.key + (isText(row.source) && row.source !== 'evento' ? ' (' + row.source + ')' : '');
  }
  return none;
}

// A reply longer than the server's cap (an older server or a hostile reply) is cut to MAX_ROWS rows plus one "outros (N)"
// row that sums the rest, so the totals stay true and the DOM stays small. A tail with an unpriced row has no cost.
function foldRows(rows) {
  if (rows.length <= MAX_ROWS + 1) return rows;
  const rest = { key: null, others: 0, tokens: 0, tokens_in: 0, tokens_out: 0, claims: 0, cost_usd: 0, reason: null };
  let priced = true;
  for (let i = MAX_ROWS; i < rows.length; i += 1) {
    const row = rows[i];
    rest.others += countOf(row);
    for (const field of ['tokens', 'tokens_in', 'tokens_out', 'claims']) rest[field] += isCount(row[field]) ? row[field] : 0;
    if (Number.isFinite(row.cost_usd) && row.cost_usd >= 0) rest.cost_usd += row.cost_usd;
    else {
      priced = false;
      if (rest.reason === null && isText(row.reason)) rest.reason = row.reason;
    }
  }
  if (!priced) rest.cost_usd = null;
  return rows.slice(0, MAX_ROWS).concat([rest]);
}

function tokenWidget(label, rows, none, tokens) {
  const limited = foldRows(rows);
  const usable = limited.filter((row) => isCount(row.tokens) && row.tokens > 0);
  if (usable.length === 0) {
    const reason = isObject(tokens) && isText(tokens.reason) ? tokens.reason : NO_BREAKDOWN_TOKENS;
    return { label, state: 'UNVERIFIED', text: reason, segments: [], legend: [] };
  }
  const total = usable.reduce((sum, row) => sum + row.tokens, 0);
  const segments = usable.map((row) => ({ text: nameOf(row, none) + ': ' + row.tokens, pct: percentOf(row.tokens, total) }));
  return { label, state: 'PASS', text: total + ' tokens medidos', segments, legend: segments.map((seg) => ({ text: seg.text })) };
}

const isPriced = (row) => Number.isFinite(row.cost_usd) && row.cost_usd >= 0;

function costWidget(label, rows, none) {
  if (rows.length === 0) return { label, state: 'UNVERIFIED', text: NO_COST, segments: [], legend: [] };
  const limited = foldRows(rows);
  const priced = limited.filter(isPriced);
  const total = priced.reduce((sum, row) => sum + row.cost_usd, 0);
  const unpriced = limited.reduce((sum, row) => sum + (isPriced(row) ? 0 : countOf(row)), 0);
  const usd = (row) => 'US$ ' + row.cost_usd.toFixed(4) + ' estimado';
  const legend = limited.map((row) => ({
    text: nameOf(row, none) + ': ' + (isPriced(row) ? usd(row) : 'custo UNVERIFIED (' + (isText(row.reason) ? row.reason : NO_COST) + ')'),
  }));
  const segments = priced.filter((row) => row.cost_usd > 0)
    .map((row) => ({ text: nameOf(row, none) + ': ' + usd(row), pct: percentOf(row.cost_usd, total) }));
  if (priced.length === 0) {
    const reason = limited.find((row) => isText(row.reason));
    return { label, state: 'UNVERIFIED', text: reason ? reason.reason : NO_COST, segments, legend };
  }
  // The headline sums only the priced rows, so it says how many it left out.
  const partial = unpriced > 0 ? ' (parcial: ' + unpriced + ' sem preço)' : '';
  return { label, state: 'ESTIMADO', text: 'US$ ' + total.toFixed(4) + ' estimado' + partial, segments, legend };
}

// "a, b (+K)": the listed values (at most MAX_ROWS) and how many more the lane has when its reply says so.
function listOf(list, total) {
  const shown = (Array.isArray(list) ? list.filter(isText) : []).slice(0, MAX_ROWS);
  const more = Number.isInteger(total) ? total - shown.length : 0;
  return { empty: shown.length === 0, text: shown.join(', ') + (more > 0 ? ' (+' + more + ')' : '') };
}

function agentMapWidget(map) {
  const label = 'Mapa de agentes';
  const lanes = isObject(map) && Array.isArray(map.lanes) ? map.lanes.filter(isObject) : [];
  if (lanes.length === 0) {
    return { label, state: 'UNVERIFIED', text: isText(map && map.reason) ? map.reason : NO_CLAIMS, segments: [], legend: [] };
  }
  const limited = foldRows(lanes);
  const legend = limited.map((lane) => {
    const head = nameOf(lane, NONE.lane) + ': ' + (isCount(lane.claims) ? lane.claims : 0) + ' claims';
    if (isOthers(lane)) return { text: head };
    const tasks = listOf(lane.tasks, lane.tasks_total);
    const leases = listOf(lane.lease_ids, lane.lease_ids_total);
    const lease = leases.empty ? ', lease UNVERIFIED (' + (isText(lane.lease_reason) ? lane.lease_reason : NO_LEASE) + ')'
      : ', leases ' + leases.text;
    return { text: head + (tasks.empty ? '' : ', tarefas ' + tasks.text) + lease };
  });
  const slots = isObject(map.slots) ? map.slots : {};
  legend.push({ text: 'slots ' + (slots.state === 'PASS' ? 'PASS' : 'UNVERIFIED (' + (isText(slots.reason) ? slots.reason : NO_SLOTS) + ')') });
  const claims = limited.reduce((sum, lane) => sum + (isCount(lane.claims) ? lane.claims : 0), 0);
  const count = limited.reduce((sum, lane) => sum + countOf(lane), 0);
  return { label, state: 'PASS', text: count + ' lanes, ' + claims + ' claims (worker_claimed)', segments: [], legend };
}

// The #1550 widgets of the stage-agents reply; an older reply without a breakdown adds none.
export function widgetsOf(stages) {
  if (!isObject(stages) || stages.schema !== STAGE_SCHEMA || !isObject(stages.breakdown)) return [];
  const rows = (name) => (Array.isArray(stages.breakdown[name]) ? stages.breakdown[name].filter(isObject) : []);
  const tokens = stages.breakdown.tokens;
  return [
    tokenWidget('Tokens por fase', rows('by_phase'), NONE.phase, tokens),
    tokenWidget('Tokens por lane', rows('by_lane'), NONE.lane, tokens),
    tokenWidget('Tokens por modelo', rows('by_model'), NONE.model, tokens),
    costWidget('Custo por tarefa', rows('by_task'), NONE.task),
    costWidget('Custo por iteração', rows('by_iteration'), NONE.iteration),
    agentMapWidget(stages.agent_map),
  ];
}

// A null or foreign reply reads as empty sources, so every row comes back UNVERIFIED with its reason.
export function extrasOf(reply, stages) {
  const source = isObject(reply) && reply.schema === SCHEMA ? reply : {};
  const parts = [commandOf(source.last_command), runningOf(source.running_command), tasksOf(source.tasks), modelsOf(source.models), heartbeatOf(source.heartbeat),
    stagesOf(stages), runCostOf(stages)];
  return LABELS.map((label, index) => ({ label, state: parts[index].state, text: parts[index].text }));
}

function barNode(segments) {
  const bar = document.createElement('div');
  bar.className = 'extras-bar';
  bar.append(...segments.map((seg, index) => {
    const part = document.createElement('span');
    part.className = 'extras-seg extras-seg-' + (index % SEGMENT_CLASSES);
    part.style.setProperty('width', Math.round(percentOf(seg.pct, 100) * 100) / 100 + '%');
    return part;
  }));
  return bar;
}

function legendNode(items) {
  const list = document.createElement('ul');
  list.className = 'extras-legend';
  list.append(...items.map((item) => {
    const entry = document.createElement('li');
    entry.textContent = item.text;
    return entry;
  }));
  return list;
}

function sparkNode(history) {
  const spark = document.createElement('sl-sparkline');
  spark.setAttribute('values', history.join(','));
  spark.setAttribute('label', 'Tokens medidos acumulados');
  return spark;
}

function rowNode(row, ...more) {
  const term = document.createElement('dt');
  term.textContent = row.label;
  const state = document.createElement('span');
  state.className = 'extras-state';
  state.textContent = row.state;
  const text = document.createElement('span');
  text.textContent = row.text;
  const detail = document.createElement('dd');
  detail.append(state, text, ...more);
  const group = document.createElement('div');
  group.dataset.state = row.state;
  group.append(term, detail);
  return group;
}

function widgetNode(widget) {
  const more = [];
  if (widget.segments.length) more.push(barNode(widget.segments));
  if (widget.legend.length) more.push(legendNode(widget.legend));
  return rowNode(widget, ...more);
}

function trendRow(history) {
  const last = history[history.length - 1];
  return rowNode({ label: 'Tokens medidos (tendência)', state: 'PASS', text: 'últimos ' + history.length + ' pontos, atual ' + last },
    sparkNode(history));
}

function render(section, rows, widgets, history) {
  const title = document.createElement('h2');
  title.textContent = 'Sinais do worker';
  const list = document.createElement('dl');
  list.className = 'extras-list';
  list.append(...rows.map((row) => rowNode(row)), ...widgets.map(widgetNode), ...(history.length ? [trendRow(history)] : []));
  section.replaceChildren(title, list);
}

// Polls the run extras and the stage agents every 3000 ms. The panel starts with every row UNVERIFIED, and a failed read keeps that reply's last value.
export function startExtras(readApi, runId) {
  if (!runId) return;
  const section = document.getElementById('live-extras');
  render(section, extrasOf(null, null), [], []);
  const base = '/api/runs/' + encodeURIComponent(runId);
  let extras = null;
  let stages = null;
  let history = [];
  const load = async () => {
    const [reply, stageReply] = await Promise.all([readApi(base + '/extras'), readApi(base + '/stage-agents')]);
    if (reply === null && stageReply === null) return;
    extras = reply === null ? extras : reply;
    stages = stageReply === null ? stages : stageReply;
    const total = isObject(stageReply) && isObject(stageReply.breakdown) && isObject(stageReply.breakdown.tokens)
      ? stageReply.breakdown.tokens.total : null;
    if (Number.isFinite(total) && total > 0) history = pushPoint(history, total);
    render(section, extrasOf(extras, stages), widgetsOf(stages), history);
  };
  load();
  setInterval(load, POLL_MS);
}
