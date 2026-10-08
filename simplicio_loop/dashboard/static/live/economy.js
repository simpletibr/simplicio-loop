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
