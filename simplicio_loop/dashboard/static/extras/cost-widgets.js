// Cost widgets of the Live cost panel (issues #1404 and #1550): where the tokens and the USD come from (the provider's own
// report or another producer) and the cost per task and per iteration. The tokens by phase, lane and model are the stacked
// bars of the worker signals panel (extras.js), so they are not drawn twice. This file loads on demand (extras.js imports it
// after the first budget read), so static/live keeps its 40 KiB gzip budget.
// Pure view first (no DOM, no network, no clock), then a renderer that builds the DOM with textContent only, never as markup.
import { make, renderBadges } from './dom-badges.js';

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function stringOrNull(value) {
  return typeof value === 'string' ? value : null;
}

// Tokens are the measured token_usage counts. USD is MEDIDO when the provider reported the cost of every event, else
// ESTIMADO (measured tokens times the price table). A missing piece stays UNVERIFIED with its reason, and a row with no
// price keeps its measured tokens.
const TOKENS_UNVERIFIED = 'tokens não medidos: nenhum token_usage registrado pelo run';
const NO_SOURCE = 'origem dos tokens não informada pelo servidor';
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

// The provider's reported cost reads "medido"; a floor USD (a prompt above the tier limit with no per-request data) reads
// "a partir de", never as an exact estimate.
function moneyOf(usd, floor, measured) {
  if (measured) return formatUsd(usd) + ' medido (reportado pelo provedor)';
  return floor ? 'a partir de ' + formatUsd(usd) : formatUsd(usd) + ' estimado';
}

function idSet(list) {
  return new Set(Array.isArray(list) ? list.map(String) : []);
}

// A group of counts as [label, value] pairs with finite values only; anything else is dropped.
function countsOf(group) {
  if (!isObject(group)) return [];
  return Object.entries(group).filter(([, value]) => numberOrNull(value) !== null);
}

// Where the measured tokens come from and what the USD of the run is made of. Rows only exist when tokens were measured.
function provenanceOf(budget) {
  const usage = isObject(budget) && isObject(budget.usage) ? budget.usage : null;
  const cost = isObject(budget) && isObject(budget.cost) ? budget.cost : null;
  const total = usage ? numberOrNull(usage.tokens) : null;
  if (total === null || total <= 0) return { state: 'UNVERIFIED', reason: TOKENS_UNVERIFIED, rows: [] };
  const source = isObject(usage.by_source) ? usage.by_source : null;
  const provider = source ? numberOrNull(source.provider) : null;
  const other = source ? numberOrNull(source.other) : null;
  let tokens;
  if (provider === null || other === null) {
    tokens = { state: 'UNVERIFIED', detail: NO_SOURCE };
  } else if (provider > 0) {
    const percent = Math.round((provider / total) * 100);
    tokens = {
      state: 'PASS',
      detail: formatTokens(provider) + ' de ' + formatTokens(total) + ' (' + percent + '%) reportados pelo provedor'
        + (other > 0 ? ' · ' + formatTokens(other) + ' de outras fontes' : ''),
    };
  } else {
    tokens = { state: 'UNVERIFIED', detail: 'nenhum token reportado pelo provedor: ' + formatTokens(total) + ' vêm de outras fontes' };
  }
  let usd;
  if (cost !== null && cost.state === 'ESTIMADO' && numberOrNull(cost.usd) !== null) {
    const measured = cost.proof_kind === 'medido';
    const floor = !measured && cost.floor === true;
    const table = !measured && stringOrNull(cost.as_of) ? ' · tabela de preços de ' + cost.as_of : '';
    usd = { state: measured ? 'PASS' : 'ESTIMADO', detail: moneyOf(cost.usd, floor, measured) + table };
  } else {
    usd = { state: 'UNVERIFIED', detail: NOT_MEASURED_USD + ': ' + (cost !== null && stringOrNull(cost.reason) ? cost.reason : 'custo do run não estimado') };
  }
  return {
    state: 'MEASURED',
    reason: 'Tokens medidos: ' + formatTokens(total) + ' em ' + (usage.samples ?? 0) + ' eventos token_usage.',
    rows: [{ key: 'source-tokens', label: 'Tokens do provedor', ...tokens }, { key: 'source-usd', label: 'USD do run', ...usd }],
  };
}

// One row per task (or iteration) with measured tokens, most tokens first; the USD joins in when the run has a cost for it.
function costRowsOf(kind, budget) {
  const usage = isObject(budget) && isObject(budget.usage) ? budget.usage : null;
  const cost = isObject(budget) && isObject(budget.cost) ? budget.cost : null;
  const priced = cost !== null && cost.state === 'ESTIMADO';
  const measured = priced && cost.proof_kind === 'medido';
  const usdReason = cost !== null && stringOrNull(cost.reason) ? cost.reason : NOT_MEASURED_USD;
  const tokensOf = usage ? countsOf(kind === 'task' ? usage.by_task : usage.by_iteration) : [];
  const usdOf = priced ? Object.fromEntries(countsOf(kind === 'task' ? cost.by_task : cost.by_iteration)) : {};
  const floorIds = priced ? idSet(kind === 'task' ? cost.floor_tasks : cost.floor_iterations) : new Set();
  const label = kind === 'task' ? 'Tarefa ' : 'Iteração ';
  const keyOf = (id) => kind + ':' + id;
  const stateOf = (usd) => (usd === null ? 'UNVERIFIED' : measured ? 'PASS' : 'ESTIMADO');
  const sorted = [...tokensOf].sort((a, b) => b[1] - a[1]);
  const rows = sorted.slice(0, COST_ROWS_CAP).map(([id, tokens]) => {
    const usd = numberOrNull(usdOf[id]);
    const floor = usd !== null && floorIds.has(id);
    const money = usd !== null ? moneyOf(usd, floor, measured) : NOT_MEASURED_USD + ': ' + (priced ? NOT_LISTED : usdReason);
    return { key: keyOf(id), label: label + id, state: stateOf(usd), floor, detail: formatTokens(tokens) + ' medidos · ' + money };
  });
  const unattributedTokens = usage && isObject(usage.unattributed_tokens) ? numberOrNull(usage.unattributed_tokens[kind]) : null;
  if (unattributedTokens !== null && unattributedTokens > 0) {
    const usd = priced && isObject(cost.unattributed_usd) ? numberOrNull(cost.unattributed_usd[kind]) : null;
    const floor = usd !== null && isObject(cost.floor_unattributed) && cost.floor_unattributed[kind] === true;
    const money = usd !== null ? moneyOf(usd, floor, measured) : NOT_MEASURED_USD + ': ' + usdReason;
    rows.push({
      floor,
      key: 'unattributed-' + kind,
      label: kind === 'task' ? 'Sem tarefa identificada' : 'Sem iteração identificada',
      state: stateOf(usd),
      detail: formatTokens(unattributedTokens) + ' medidos · ' + money,
    });
  }
  const attributed = tokensOf.length;
  // The split has a USD only when a listed task (or iteration) carries one; an unattributed remainder alone is not a split.
  const state = rows.some((row) => row.key.startsWith(kind + ':') && row.state !== 'UNVERIFIED') ? (measured ? 'MEDIDO' : 'ESTIMADO') : 'UNVERIFIED';
  let reason;
  if (state === 'MEDIDO') reason = 'USD reportado pelo provedor; tokens medidos.';
  else if (state === 'ESTIMADO') reason = 'USD estimado com a tabela de preços de ' + (stringOrNull(cost.as_of) || 'data não informada') + '; tokens medidos.';
  else if (attributed === 0) reason = kind === 'task' ? NO_TASK_ID : NO_ITERATION;
  else reason = usdReason;
  const floorReason = state === 'ESTIMADO' && cost.floor === true ? stringOrNull(cost.floor_reason) : null;
  if (floorReason) reason += ' ' + floorReason + '.';
  return { state, reason, rows, more: Math.max(0, attributed - COST_ROWS_CAP) };
}

// The cost widgets of the panel: the origin of the tokens and the USD, the cost per task and the cost per iteration.
export function costWidgetsView(budget) {
  return {
    provenance: provenanceOf(budget),
    taskCosts: costRowsOf('task', budget),
    iterationCosts: costRowsOf('iteration', budget),
  };
}

// Renderer.
function costNote(costs) {
  return costs.more > 0 ? costs.reason + ' Mais ' + costs.more + ' não listadas.' : costs.reason;
}

function block(id, title) {
  return make('section', { class: 'cost-block', 'aria-labelledby': id + '-title' },
    make('h3', { id: id + '-title' }, title), make('p', { id: id + '-note', class: 'note' }),
    make('ul', { id: id, class: 'checks', 'aria-label': title }));
}

function buildInto(host) {
  host.replaceChildren(
    block('token-source', 'Origem dos tokens e do USD'),
    block('task-cost', 'Custo por tarefa'),
    block('iteration-cost', 'Custo por iteração'),
  );
}

// Draws the widgets for one GET /api/runs/<id>/budget body under the agents list, building the host on the first call.
export function renderCostWidgets(budget) {
  let host = document.getElementById('cost-widgets');
  if (!host) {
    host = make('div', { id: 'cost-widgets', class: 'cost-widgets' });
    document.getElementById('agents-cost').after(host);
    buildInto(host);
  }
  const view = costWidgetsView(budget);
  document.getElementById('token-source-note').textContent = view.provenance.reason;
  renderBadges(document.getElementById('token-source'), view.provenance.rows);
  document.getElementById('task-cost-note').textContent = costNote(view.taskCosts);
  renderBadges(document.getElementById('task-cost'), view.taskCosts.rows);
  document.getElementById('iteration-cost-note').textContent = costNote(view.iterationCosts);
  renderBadges(document.getElementById('iteration-cost'), view.iterationCosts.rows);
}
