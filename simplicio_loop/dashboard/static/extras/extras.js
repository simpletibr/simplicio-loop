// Extras panel: maps the run extras reply and the stage-agents reply to six labelled rows and renders them into #live-extras.
// Only a measured value earns PASS; anything else is UNVERIFIED with the reason it could not be measured.
const SCHEMA = 'simplicio.dashboard-extras/v1';
const STAGE_SCHEMA = 'simplicio.dashboard-stage-agents/v1';
const POLL_MS = 3000;
const LABELS = ['Último comando medido', 'Contrato por tarefa', 'Modelo por lane', 'Batimento do lease', 'Agentes por etapa', 'Custo do run'];
const NO_COMMAND = 'nenhum teste ou lint medido';
const NO_TASKS = 'task-contract.json sem tarefas';
const NO_TOKENS = 'sem token_usage medido';
const NO_HEARTBEAT = 'sem batimento do lease medido';
const NO_STAGES = 'sem token_usage por etapa medido';
const NO_COST = 'custo do run não estimado';

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = (value) => typeof value === 'string' && value.trim() !== '';
const isCount = (value) => Number.isFinite(value) && value >= 0;

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

// Role, model and tokens are measured; the cost of a stage is always an estimate.
function stageText(row) {
  const who = isText(row.role) ? row.role + (isText(row.effort) ? '/' + row.effort : '') : 'sem papel';
  const usd = Number.isFinite(row.cost_usd)
    ? 'US$ ' + row.cost_usd.toFixed(4) + ' estimado'
    : 'custo UNVERIFIED (' + (isText(row.reason) ? row.reason : NO_COST) + ')';
  return (isText(row.phase) ? row.phase : 'sem fase') + ': ' + who + ' ' + (isText(row.model) ? row.model : 'sem modelo')
    + ', entrada ' + (isCount(row.tokens_in) ? row.tokens_in : 0) + ', saída ' + (isCount(row.tokens_out) ? row.tokens_out : 0)
    + ', ' + usd;
}

function stagesOf(stages) {
  const rows = isObject(stages) && stages.schema === STAGE_SCHEMA && Array.isArray(stages.rows)
    ? stages.rows.filter(isObject) : [];
  if (rows.length === 0) return { state: 'UNVERIFIED', text: NO_STAGES };
  return { state: rows.some((row) => Number.isFinite(row.cost_usd)) ? 'ESTIMADO' : 'UNVERIFIED', text: rows.map(stageText).join('; ') };
}

function runCostOf(stages) {
  const cost = isObject(stages) && stages.schema === STAGE_SCHEMA && isObject(stages.cost) ? stages.cost : {};
  if (Number.isFinite(cost.usd)) return { state: 'ESTIMADO', text: 'US$ ' + cost.usd.toFixed(4) + ' estimado' };
  return { state: 'UNVERIFIED', text: isText(cost.reason) ? cost.reason : NO_COST };
}

// A null or foreign reply reads as empty sources, so every row comes back UNVERIFIED with its reason.
export function extrasOf(reply, stages) {
  const source = isObject(reply) && reply.schema === SCHEMA ? reply : {};
  const parts = [commandOf(source.last_command), tasksOf(source.tasks), modelsOf(source.models), heartbeatOf(source.heartbeat),
    stagesOf(stages), runCostOf(stages)];
  return LABELS.map((label, index) => ({ label, state: parts[index].state, text: parts[index].text }));
}

function rowNode(row) {
  const term = document.createElement('dt');
  term.textContent = row.label;
  const state = document.createElement('span');
  state.className = 'extras-state';
  state.textContent = row.state;
  const text = document.createElement('span');
  text.textContent = row.text;
  const detail = document.createElement('dd');
  detail.append(state, text);
  const group = document.createElement('div');
  group.dataset.state = row.state;
  group.append(term, detail);
  return group;
}

function render(section, rows) {
  const title = document.createElement('h2');
  title.textContent = 'Sinais do worker';
  const list = document.createElement('dl');
  list.className = 'extras-list';
  list.append(...rows.map(rowNode));
  section.replaceChildren(title, list);
}

// Polls the run extras and the stage agents every 3000 ms. The panel starts with every row UNVERIFIED, and a failed read keeps that reply's last value.
export function startExtras(readApi, runId) {
  if (!runId) return;
  const section = document.getElementById('live-extras');
  render(section, extrasOf(null, null));
  const base = '/api/runs/' + encodeURIComponent(runId);
  let extras = null;
  let stages = null;
  const load = async () => {
    const [reply, stageReply] = await Promise.all([readApi(base + '/extras'), readApi(base + '/stage-agents')]);
    if (reply === null && stageReply === null) return;
    extras = reply === null ? extras : reply;
    stages = stageReply === null ? stages : stageReply;
    render(section, extrasOf(extras, stages));
  };
  load();
  setInterval(load, POLL_MS);
}
