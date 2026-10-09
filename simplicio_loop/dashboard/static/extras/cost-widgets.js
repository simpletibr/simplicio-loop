// Cost widgets of the Live cost panel (issue #1404): token bars and the cost per task and per iteration. They live in the extras
// bundle and load on demand (app.js imports this file after the first budget read), so static/live keeps its 40 KiB gzip budget.
// Pure view first (no DOM, no network, no clock), then a renderer that builds the DOM with textContent only, never as markup.
const MODELS_CAP = 8;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function stringOrNull(value) {
  return typeof value === 'string' ? value : null;
}

// Token bars and cost per task and per iteration, from GET /api/runs/<id>/budget.
// Tokens are the measured token_usage counts; USD is ESTIMADO (measured tokens times the price table). A missing piece stays
// UNVERIFIED with its reason, and a row with no price keeps its measured tokens.
const TOKENS_UNVERIFIED = 'tokens não medidos: nenhum token_usage registrado pelo run';
const NO_TASK_ID = 'nenhum token_usage com task_id: o produtor não grava a tarefa';
const NO_ITERATION = 'nenhum token_usage com iteração: o produtor não grava o número da iteração';
const NOT_LISTED = 'USD fora da lista dos maiores do run';
const NOT_MEASURED_USD = 'USD não verificado';
const COST_ROWS_CAP = 8;

function formatTokens(value) {
  return Math.round(value).toLocaleString('pt-BR') + ' tokens';
}

function formatUsd(value) {
  return 'USD ' + value.toFixed(4);
}

// A group of counts as [label, value] pairs with finite values only; anything else is dropped.
function countsOf(group) {
  if (!isObject(group)) return [];
  return Object.entries(group).filter(([, value]) => numberOrNull(value) !== null);
}

function tokenBarsOf(budget) {
  const usage = isObject(budget) && isObject(budget.usage) ? budget.usage : null;
  const total = usage ? numberOrNull(usage.tokens) : null;
  if (total === null || total <= 0) return { state: 'UNVERIFIED', reason: TOKENS_UNVERIFIED, total: null, phases: [], models: [], modelsOther: null };
  const phases = countsOf(usage.by_phase).map(([label, value]) => ({ label, value }));
  const models = countsOf(usage.by_model).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
  const rest = models.slice(MODELS_CAP);
  return {
    state: 'MEASURED',
    reason: 'Tokens medidos: ' + formatTokens(total) + ' em ' + (usage.samples ?? 0) + ' eventos token_usage.',
    total,
    phases,
    models: models.slice(0, MODELS_CAP),
    modelsOther: rest.length === 0 ? null : { models: rest.length, value: rest.reduce((sum, item) => sum + item.value, 0) },
  };
}

// One row per task (or iteration) with measured tokens, most tokens first; the USD joins in when the price table priced it.
function costRowsOf(kind, budget) {
  const usage = isObject(budget) && isObject(budget.usage) ? budget.usage : null;
  const cost = isObject(budget) && isObject(budget.cost) ? budget.cost : null;
  const priced = cost !== null && cost.state === 'ESTIMADO';
  const usdReason = cost !== null && stringOrNull(cost.reason) ? cost.reason : NOT_MEASURED_USD;
  const tokensOf = usage ? countsOf(kind === 'task' ? usage.by_task : usage.by_iteration) : [];
  const usdOf = priced ? Object.fromEntries(countsOf(kind === 'task' ? cost.by_task : cost.by_iteration)) : {};
  const label = kind === 'task' ? 'Tarefa ' : 'Iteração ';
  const keyOf = (id) => kind + ':' + id;
  const sorted = [...tokensOf].sort((a, b) => b[1] - a[1]);
  const rows = sorted.slice(0, COST_ROWS_CAP).map(([id, tokens]) => {
    const usd = numberOrNull(usdOf[id]);
    const money = usd !== null ? formatUsd(usd) + ' estimado' : NOT_MEASURED_USD + ': ' + (priced ? NOT_LISTED : usdReason);
    return { key: keyOf(id), label: label + id, state: usd !== null ? 'ESTIMADO' : 'UNVERIFIED', detail: formatTokens(tokens) + ' medidos · ' + money };
  });
  const unattributedTokens = usage && isObject(usage.unattributed_tokens) ? numberOrNull(usage.unattributed_tokens[kind]) : null;
  if (unattributedTokens !== null && unattributedTokens > 0) {
    const usd = priced && isObject(cost.unattributed_usd) ? numberOrNull(cost.unattributed_usd[kind]) : null;
    const money = usd !== null ? formatUsd(usd) + ' estimado' : NOT_MEASURED_USD + ': ' + usdReason;
    rows.push({
      key: 'unattributed-' + kind,
      label: kind === 'task' ? 'Sem tarefa identificada' : 'Sem iteração identificada',
      state: usd !== null ? 'ESTIMADO' : 'UNVERIFIED',
      detail: formatTokens(unattributedTokens) + ' medidos · ' + money,
    });
  }
  const attributed = tokensOf.length;
  // The split is estimated only when a listed task (or iteration) carries USD; an unattributed remainder alone is not a split.
  const state = rows.some((row) => row.key.startsWith(kind + ':') && row.state === 'ESTIMADO') ? 'ESTIMADO' : 'UNVERIFIED';
  let reason;
  if (state === 'ESTIMADO') reason = 'USD estimado com a tabela de preços de ' + (stringOrNull(cost.as_of) || 'data não informada') + '; tokens medidos.';
  else if (attributed === 0) reason = kind === 'task' ? NO_TASK_ID : NO_ITERATION;
  else reason = usdReason;
  return { state, reason, rows, more: Math.max(0, attributed - COST_ROWS_CAP) };
}

// The cost widgets of the panel: the token bars, the cost per task and the cost per iteration.
export function costWidgetsView(budget) {
  return {
    tokenBars: tokenBarsOf(budget),
    taskCosts: costRowsOf('task', budget),
    iterationCosts: costRowsOf('iteration', budget),
  };
}

// Renderer. Every name from an event reaches the page as textContent or an attribute value, never as markup.
function make(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props || {}).forEach(([name, value]) => node.setAttribute(name, value));
  node.append(...children);
  return node;
}

function formatInt(value) {
  return Math.round(value).toLocaleString('pt-BR');
}

function barRow(label, value, total) {
  const bar = make('progress', { 'aria-label': label + ': ' + formatInt(value) + ' tokens' });
  bar.max = total;
  bar.value = value;
  const percent = Math.round((value / total) * 100);
  return make('li', {}, make('span', { class: 'bar-label' }, label), bar, make('span', { class: 'bar-value' }, formatInt(value) + ' tokens (' + percent + '%)'));
}

function barGroups(bars) {
  const groups = [['Por fase', bars.phases], ['Por modelo', bars.models]];
  return groups.filter(([, items]) => items.length > 0).map(([caption, items]) => {
    const rows = items.map((item) => barRow(item.label, item.value, bars.total));
    if (caption === 'Por modelo' && bars.modelsOther) rows.push(barRow('outros ' + bars.modelsOther.models + ' modelos', bars.modelsOther.value, bars.total));
    return make('div', {}, make('p', { class: 'bars-caption' }, caption), make('ul', { class: 'bars' }, ...rows));
  });
}

function costNote(costs) {
  return costs.more > 0 ? costs.reason + ' Mais ' + costs.more + ' não listadas.' : costs.reason;
}

// Keyed rows of sl-gate-badge: the rows are created once, then only their attributes change.
function renderBadges(list, rows) {
  if (list.children.length !== rows.length) {
    list.replaceChildren(...rows.map(() => make('li', {}, document.createElement('sl-gate-badge'))));
  }
  rows.forEach((row, index) => {
    const li = list.children[index];
    li.setAttribute('data-key', row.key);
    li.firstElementChild.setAttribute('gate', row.label);
    li.firstElementChild.setAttribute('state', row.state);
    li.firstElementChild.setAttribute('reason', row.detail);
  });
}

function block(id, title, content) {
  return make('section', { class: 'cost-block', 'aria-labelledby': id + '-title' },
    make('h3', { id: id + '-title' }, title), make('p', { id: id + '-note', class: 'note' }), content);
}

function buildInto(host) {
  host.replaceChildren(
    block('token-bars', 'Tokens por fase e modelo', make('div', { id: 'token-bars' })),
    block('task-cost', 'Custo por tarefa', make('ul', { id: 'task-cost', class: 'checks', 'aria-label': 'Custo por tarefa' })),
    block('iteration-cost', 'Custo por iteração', make('ul', { id: 'iteration-cost', class: 'checks', 'aria-label': 'Custo por iteração' })),
  );
}

let shownBars = null;

// Draws the widgets for one GET /api/runs/<id>/budget body under the agents list, building the host on the first call.
export function renderCostWidgets(budget) {
  let host = document.getElementById('cost-widgets');
  if (!host) {
    host = make('div', { id: 'cost-widgets', class: 'cost-widgets' });
    document.getElementById('agents-cost').after(host);
    buildInto(host);
  }
  const view = costWidgetsView(budget);
  const barsText = JSON.stringify(view.tokenBars);
  if (barsText !== shownBars) {
    shownBars = barsText;
    document.getElementById('token-bars').replaceChildren(...barGroups(view.tokenBars));
  }
  document.getElementById('token-bars-note').textContent = view.tokenBars.reason || '';
  document.getElementById('task-cost-note').textContent = costNote(view.taskCosts);
  renderBadges(document.getElementById('task-cost'), view.taskCosts.rows);
  document.getElementById('iteration-cost-note').textContent = costNote(view.iterationCosts);
  renderBadges(document.getElementById('iteration-cost'), view.iterationCosts.rows);
}
