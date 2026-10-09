// Simplicio Live global economy view (issue #1404, slice 1404a). Pure: no DOM, no network, no clock.
// Reads only the token fields the proxy panel publishes; log lines, runtimes and process data never enter the view.
const MODELS_CAP = 8;
const NO_PANEL = 'painel de tokens indisponivel';
const NO_DATA = 'nenhum dado de tokens recebido';
const NO_TRAFFIC = 'proxy de captura sem trafego medido';
const NOT_MEASURED = 'tokens nao medidos';
const NO_COST_MODEL = 'modelo ativo não identificado';
const NO_PRICE_TABLE = 'tabela de preços indisponível';
const NOT_PRICED = 'modelo ativo sem preço na tabela';
const NO_CONTRACT = 'contrato de agentes não recebido';
const TOKENS_BY_PHASE = 'sem produtor de tokens por fase no fluxo atual';
const BUDGET = 'orçamento do run indisponível: o contrato da tarefa não declara limite ou a leitura falhou';
const COMPARISON = 'histórico de runs indisponível para este run';

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function numberOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function stringOrNull(value) {
  return typeof value === 'string' ? value : null;
}

// Every measured field is null or empty unless the reading is MEASURED with traffic.
function economyOf(status, reason, requests) {
  return {
    status,
    reason,
    scope: 'global',
    proof: { tokens: 'estimado', usd: 'estimado' },
    requests,
    tokensBefore: null,
    tokensAfter: null,
    tokensSaved: null,
    savingsPct: null,
    usdSaved: null,
    providers: { total: null, interceptable: null, notInterceptable: null },
    proxyRunning: null,
    ledgerEvents: null,
    activeModel: null,
    modelsSeen: [],
    series: [],
    seriesKind: 'acumulado',
  };
}

function providersOf(data) {
  const total = numberOrNull(data.provider_total);
  const interceptable = numberOrNull(data.provider_interceptable);
  const notInterceptable = total === null || interceptable === null ? null : Math.max(0, total - interceptable);
  return { total, interceptable, notInterceptable };
}

// The active model is the last intercepted request; an empty object means there is no history.
function activeModelOf(value) {
  if (!isObject(value) || Object.keys(value).length === 0) return null;
  return {
    provider: stringOrNull(value.provider),
    model: stringOrNull(value.model),
    timestamp: stringOrNull(value.timestamp),
    saved: numberOrNull(value.saved),
  };
}

function modelsOf(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(isObject).slice(0, MODELS_CAP)
    .map((item) => ({ provider: stringOrNull(item.provider), model: stringOrNull(item.model) }));
}

// One point per history entry: the tokens saved by that request.
function seriesOf(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(isObject).map((entry) => numberOrNull(entry.saved)).filter((saved) => saved !== null);
}

// The global economy of the token proxy, from the GET /api/tokens body, with its cost estimate.
export function economyView(response) {
  const economy = economyBase(response);
  return { ...economy, cost: costOf(response, economy) };
}

function economyBase(response) {
  if (!isObject(response)) return economyOf('UNVERIFIED', NO_PANEL, null);
  if (response.status !== 'MEASURED') return economyOf('UNVERIFIED', stringOrNull(response.reason) || NOT_MEASURED, null);
  const data = response.data;
  if (!isObject(data)) return economyOf('UNVERIFIED', NO_DATA, null);
  const requests = numberOrNull(data.requests);
  if (requests === null) return economyOf('UNVERIFIED', NO_DATA, null);
  if (requests === 0) return economyOf('UNVERIFIED', NO_TRAFFIC, 0);
  return {
    ...economyOf('MEASURED', null, requests),
    tokensBefore: numberOrNull(data.tokens_before),
    tokensAfter: numberOrNull(data.tokens_after),
    tokensSaved: numberOrNull(data.tokens_saved),
    savingsPct: numberOrNull(data.savings_pct),
    usdSaved: numberOrNull(data.usd_saved),
    providers: providersOf(data),
    proxyRunning: typeof data.proxy_running === 'boolean' ? data.proxy_running : null,
    ledgerEvents: numberOrNull(data.ledger_events),
    activeModel: activeModelOf(data.active_model),
    modelsSeen: modelsOf(data.models_seen),
    series: seriesOf(data.series),
  };
}

function unpricedOf(reason) {
  return {
    state: 'UNVERIFIED', reason, model: null, inputPerMtok: null, inputUsd: null, savedUsd: null,
    asOf: null, sourceUrl: null, note: null, proof: 'estimado',
  };
}

// The longest table key that prefixes the model id, so a dated id takes its family's price.
function priceFor(models, model) {
  let best = null;
  for (const key of Object.keys(models)) {
    if (model.startsWith(key) && (best === null || key.length > best.length)) best = key;
  }
  return best === null ? null : models[best];
}

// Measured tokens times the active model's input price from the table. Each missing piece stays UNVERIFIED with its reason.
function costOf(response, economy) {
  if (economy.status !== 'MEASURED') return unpricedOf(economy.reason);
  const table = isObject(response.pricing) ? response.pricing : null;
  if (table === null || !isObject(table.models)) return unpricedOf(NO_PRICE_TABLE);
  const active = economy.activeModel;
  if (active === null || !active.model) return unpricedOf(NO_COST_MODEL);
  const price = priceFor(table.models, active.model);
  if (!isObject(price)) return unpricedOf(NOT_PRICED);
  const rate = numberOrNull(price.input_per_mtok);
  if (rate === null || economy.tokensAfter === null || economy.tokensSaved === null) return unpricedOf(NOT_MEASURED);
  return {
    state: 'ESTIMADO',
    reason: null,
    model: active.model,
    inputPerMtok: rate,
    inputUsd: economy.tokensAfter * rate / 1000000,
    savedUsd: economy.tokensSaved * rate / 1000000,
    asOf: stringOrNull(table.as_of),
    sourceUrl: stringOrNull(table.source_url),
    note: stringOrNull(price.note),
    proof: 'estimado',
  };
}

function costRowOf(cost) {
  if (cost.state !== 'ESTIMADO') return { key: 'cost', label: 'Custo', state: 'UNVERIFIED', reason: cost.reason };
  const text = 'USD ' + cost.inputUsd.toFixed(4) + ' de entrada estimados com ' + cost.model
    + ' (US$ ' + cost.inputPerMtok + ' por milhão de tokens, tabela de ' + cost.asOf + ').';
  return { key: 'cost', label: 'Custo', state: 'ESTIMADO', reason: text };
}

function rolesOf(contract) {
  if (!contract || !Array.isArray(contract.roles)) return [];
  return contract.roles.filter(isObject).map((role) => ({
    role_id: stringOrNull(role.role_id),
    title: stringOrNull(role.title),
    stages: Array.isArray(role.stages) ? role.stages.map(String) : [],
  }));
}

const BUDGET_LABELS = { tokens: 'tokens', usd: 'USD', seconds: 'segundos' };

function num(value) {
  return numberOrNull(value) === null ? '–' : String(Math.round(value * 10000) / 10000);
}

// Budget row from GET /api/runs/<id>/budget. A projection is an estimate; only a use already past the limit is measured.
function budgetRowOf(budget) {
  const base = { key: 'budget', label: 'Orcamento' };
  const rows = isObject(budget) && isObject(budget.rows) ? budget.rows : null;
  if (rows === null) return { ...base, state: 'UNVERIFIED', reason: BUDGET };
  const parts = [];
  let state = 'UNVERIFIED';
  for (const key of Object.keys(BUDGET_LABELS)) {
    const row = rows[key];
    if (!isObject(row) || row.state === 'UNVERIFIED') continue;
    const unit = BUDGET_LABELS[key];
    if (row.state === 'EXCEEDED') {
      state = 'FAIL';
      parts.push(unit + ': uso medido ' + num(row.used) + ' passou do limite ' + num(row.limit));
    } else {
      if (state !== 'FAIL') state = 'ESTIMADO';
      const over = row.state === 'PROJECTED_OVER' ? ' e passa do limite' : '';
      parts.push(unit + ': estimado ' + num(row.projected) + ' ao fim do run' + over + ' (limite ' + num(row.limit) + ', uso ' + num(row.used) + ')');
    }
  }
  if (parts.length === 0) {
    const why = Object.values(rows).map((row) => (isObject(row) ? stringOrNull(row.reason) : null)).find(Boolean);
    return { ...base, state: 'UNVERIFIED', reason: why || BUDGET };
  }
  return { ...base, state, reason: parts.join('; ') };
}

function groupText(group) {
  return Object.entries(group).map(([name, tokens]) => name + ' ' + tokens).join(', ');
}

// Tokens per phase and model come from the measured token_usage events; with no producer the row stays UNVERIFIED.
function tokensByPhaseRowOf(budget) {
  const usage = isObject(budget) && isObject(budget.usage) ? budget.usage : null;
  const byPhase = usage && isObject(usage.by_phase) ? usage.by_phase : {};
  if (Object.keys(byPhase).length === 0) return { key: 'tokensByPhase', label: 'Tokens por fase', state: 'UNVERIFIED', reason: TOKENS_BY_PHASE };
  const byModel = isObject(usage.by_model) ? usage.by_model : {};
  const reason = 'medido por fase: ' + groupText(byPhase) + (Object.keys(byModel).length ? '. Por modelo: ' + groupText(byModel) + '.' : '.');
  return { key: 'tokensByPhase', label: 'Tokens por fase', state: 'PASS', reason };
}

const COMPARE_LABELS = { duration_s: 'duração', tokens: 'tokens', cost_usd: 'custo', iterations: 'iterações' };
const NO_BASELINE = 'nenhum run anterior com valor medido para comparar';

// This run against the average of the last ten finished runs. The averages are derived figures, so they show ESTIMADO.
function comparisonRowOf(budget) {
  const base = { key: 'comparison', label: 'Comparacao com os ultimos 10 runs' };
  const comparison = isObject(budget) && isObject(budget.comparison) ? budget.comparison : null;
  if (comparison === null || !isObject(comparison.fields)) return { ...base, state: 'UNVERIFIED', reason: COMPARISON };
  const parts = [];
  for (const key of Object.keys(COMPARE_LABELS)) {
    const field = comparison.fields[key];
    if (!isObject(field) || field.state !== 'ESTIMADO' || numberOrNull(field.delta_pct) === null) continue;
    const signed = (field.delta_pct > 0 ? '+' : '') + field.delta_pct + '%';
    parts.push(COMPARE_LABELS[key] + ' ' + signed + ' (média ' + num(field.average) + ' em ' + field.samples + ' runs)');
  }
  if (parts.length === 0) return { ...base, state: 'UNVERIFIED', reason: NO_BASELINE };
  return { ...base, state: 'ESTIMADO', reason: 'estimado sobre ' + comparison.runs + ' runs: ' + parts.join('; ') };
}

// The agent-level rows: the map lists the contract roles, and no instance is measured, so no row is ever PASS.
export function agentsCostView(economy, agents, budget) {
  const contract = isObject(agents) ? agents : null;
  return [
    {
      key: 'agentMap', label: 'Mapa de agentes', state: 'UNVERIFIED', roles: rolesOf(contract),
      reason: contract && stringOrNull(contract.reason) ? contract.reason : NO_CONTRACT,
    },
    tokensByPhaseRowOf(budget),
    costRowOf(economy.cost),
    budgetRowOf(budget),
    comparisonRowOf(budget),
  ];
}

// Cost widgets (issue #1404): token bars and cost per task and per iteration, from GET /api/runs/<id>/budget.
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
