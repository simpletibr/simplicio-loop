// Extras panel: maps the run extras reply to four labelled rows and renders them into #live-extras.
// Only a measured value earns PASS; anything else is UNVERIFIED with the reason it could not be measured.
const SCHEMA = 'simplicio.dashboard-extras/v1';
const POLL_MS = 3000;
const LABELS = ['Último comando medido', 'Contrato por tarefa', 'Modelo por lane', 'Batimento do lease'];
const NO_COMMAND = 'nenhum teste ou lint medido';
const NO_TASKS = 'task-contract.json sem tarefas';
const NO_TOKENS = 'sem token_usage medido';
const NO_HEARTBEAT = 'sem batimento do lease medido';

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

// A null or foreign reply reads as empty sources, so every row comes back UNVERIFIED with its reason.
export function extrasOf(reply) {
  const source = isObject(reply) && reply.schema === SCHEMA ? reply : {};
  const parts = [commandOf(source.last_command), tasksOf(source.tasks), modelsOf(source.models), heartbeatOf(source.heartbeat)];
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

// Polls the run extras every 3000 ms. The panel starts with every row UNVERIFIED, and a failed read keeps the last render.
export function startExtras(readApi, runId) {
  if (!runId) return;
  const section = document.getElementById('live-extras');
  render(section, extrasOf(null));
  const load = async () => {
    const reply = await readApi('/api/runs/' + encodeURIComponent(runId) + '/extras');
    if (reply === null) return;
    render(section, extrasOf(reply));
  };
  load();
  setInterval(load, POLL_MS);
}
