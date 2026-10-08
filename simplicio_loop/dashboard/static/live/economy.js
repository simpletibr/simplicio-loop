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
const BUDGET = 'orçamento do run fica no journal do Mapper; a leitura entra em fatia própria';
const COMPARISON = 'o histórico de runs entra com a issue #1408';

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

// The agent-level rows: the map lists the contract roles, and no instance is measured, so no row is ever PASS.
export function agentsCostView(economy, agents) {
  const contract = isObject(agents) ? agents : null;
  return [
    {
      key: 'agentMap', label: 'Mapa de agentes', state: 'UNVERIFIED', roles: rolesOf(contract),
      reason: contract && stringOrNull(contract.reason) ? contract.reason : NO_CONTRACT,
    },
    { key: 'tokensByPhase', label: 'Tokens por fase', state: 'UNVERIFIED', reason: TOKENS_BY_PHASE },
    costRowOf(economy.cost),
    { key: 'budget', label: 'Orcamento', state: 'UNVERIFIED', reason: BUDGET },
    { key: 'comparison', label: 'Comparacao com os ultimos 10 runs', state: 'UNVERIFIED', reason: COMPARISON },
  ];
}
