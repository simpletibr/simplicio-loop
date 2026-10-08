// Simplicio Live global economy view (issue #1404, slice 1404a). Pure: no DOM, no network, no clock.
// Reads only the token fields the proxy panel publishes; log lines, runtimes and process data never enter the view.
const MODELS_CAP = 8;
const NO_PANEL = 'painel de tokens indisponivel';
const NO_DATA = 'nenhum dado de tokens recebido';
const NO_TRAFFIC = 'proxy de captura sem trafego medido';
const NOT_MEASURED = 'tokens nao medidos';
const AGENT_ROWS = [
  ['agentMap', 'Mapa de agentes', 'sem produtor de mapa de agentes no fluxo atual'],
  ['tokensByPhase', 'Tokens por fase', 'sem produtor de tokens por fase no fluxo atual'],
  ['cost', 'Custo', 'sem produtor de custo por agente no fluxo atual'],
  ['budget', 'Orcamento', 'sem produtor de orcamento no fluxo atual'],
  ['comparison', 'Comparacao com os ultimos 10 runs', 'sem produtor de comparacao entre runs no fluxo atual'],
];

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

// The global economy of the token proxy, from the GET /api/tokens body. Unmeasured readings are UNVERIFIED with a reason.
export function economyView(response) {
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

// The five agent-level cost rows. No producer exists yet for any of them, so none is ever PASS.
export function agentsCostView() {
  return AGENT_ROWS.map(([key, label, reason]) => ({ key, label, state: 'UNVERIFIED', reason }));
}
