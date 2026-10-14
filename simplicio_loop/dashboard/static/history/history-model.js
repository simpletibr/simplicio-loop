// History model for the Simplicio Live dashboard. Turns the simplicio.dashboard-history/v1 records, the trend buckets,
// the heatmap grid and a run comparison into what the history view draws: a query string, row texts, heat levels,
// trend series, delta texts and phase bars. Pure: no DOM, no network and no clock. Null means unmeasured.

const HISTORY_FILTERS = [
  ['verdict', 'verdict'],
  ['repo', 'repo'],
  ['since', 'since'],
  ['until', 'until'],
  ['minDuration', 'min_duration_s'],
  ['maxDuration', 'max_duration_s'],
  ['minIterations', 'min_iterations'],
  ['maxIterations', 'max_iterations'],
  ['minCost', 'min_cost_usd'],
  ['maxCost', 'max_cost_usd'],
  ['limit', 'limit'],
];

const TONE = new Map([
  ['COMPLETE', 'pass'],
  ['BLOCKED', 'fail'],
  ['INFRASTRUCTURE_FAILURE', 'fail'],
  ['INVALID_RECEIPT', 'fail'],
  ['PARTIAL', 'warn'],
  ['CANCELLED', 'warn'],
  ['RUNNING', 'run'],
]);

const TREND_KEYS = ['complete_rate', 'iterations_per_task', 'cost_per_task_usd'];
const DELTA_KINDS = ['seconds', 'count', 'usd'];
const UNMEASURED = '—';
const MINUS = '−';

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value);
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const numberOrNull = (value) => (isNumber(value) && value >= 0 ? value : null);

function durationText(seconds) {
  if (!isNumber(seconds) || seconds < 0) return UNMEASURED;
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return hours + 'h ' + minutes + 'm';
  if (minutes > 0) return minutes + 'm ' + secs + 's';
  return secs + 's';
}

function costText(usd) {
  if (!isNumber(usd) || usd < 0) return UNMEASURED;
  return 'US$ ' + usd.toFixed(2);
}

function rowOf(record) {
  return {
    runId: record.run_id ?? null,
    repo: record.repo ?? null,
    verdict: record.verdict ?? null,
    durationText: durationText(record.duration_s),
    iterations: isNumber(record.iterations) ? record.iterations : UNMEASURED,
    costText: costText(record.cost_usd),
    startedAt: record.started_at ?? null,
    tone: TONE.get(record.verdict) ?? 'idle',
  };
}

// The filter query string for the history list. Empty values are skipped, zero is kept, the key order is fixed.
export function historyQuery(filters) {
  const source = isRecord(filters) ? filters : {};
  const pairs = [];
  for (const [key, apiName] of HISTORY_FILTERS) {
    const value = source[key];
    if (value === null || value === undefined) continue;
    if (typeof value === 'number' && !Number.isFinite(value)) continue;
    if (String(value).trim() === '') continue;
    pairs.push(apiName + '=' + encodeURIComponent(String(value)));
  }
  return pairs.length ? '?' + pairs.join('&') : '';
}

// One row per history record, in input order. A value that is not a record is skipped.
export function rowsOf(records) {
  if (!Array.isArray(records)) return [];
  return records.filter(isRecord).map(rowOf);
}

// A 7 x 24 grid (weekday by hour) of heat levels 0..4. A zero count is level 0; any other count is ceil(4 * count / max).
export function heatLevels(grid) {
  const countAt = (day, hour) => {
    const row = Array.isArray(grid) ? grid[day] : undefined;
    const count = Array.isArray(row) ? row[hour] : undefined;
    return isNumber(count) && count > 0 ? count : 0;
  };
  let max = 0;
  for (let day = 0; day < 7; day += 1) {
    for (let hour = 0; hour < 24; hour += 1) max = Math.max(max, countAt(day, hour));
  }
  return Array.from({ length: 7 }, (_, day) => Array.from({ length: 24 }, (_, hour) => {
    const count = countAt(day, hour);
    return count === 0 || max === 0 ? 0 : Math.ceil((4 * count) / max);
  }));
}

// The labels (buckets, oldest first as given) and the values of one trend key. A missing value is null.
export function trendSeries(trends, key) {
  if (!TREND_KEYS.includes(key)) throw new RangeError('unknown trend key: ' + key);
  const rows = Array.isArray(trends) ? trends.filter(isRecord) : [];
  return {
    labels: rows.map((row) => row.bucket ?? null),
    values: rows.map((row) => (isNumber(row[key]) ? row[key] : null)),
  };
}

function signOf(delta, shown) {
  if (shown === 0) return '';
  return delta < 0 ? MINUS : '+';
}

// The text of a comparison delta (b minus a). kind is 'seconds', 'count' or 'usd'; a null delta is a dash.
export function deltaText(metric, kind) {
  if (!DELTA_KINDS.includes(kind)) throw new RangeError('unknown delta kind: ' + kind);
  const delta = isRecord(metric) ? metric.delta : null;
  if (!isNumber(delta)) return UNMEASURED;
  if (kind === 'usd') {
    const shown = Math.abs(delta).toFixed(2);
    return signOf(delta, Number(shown)) + 'US$ ' + shown;
  }
  const magnitude = Math.round(Math.abs(delta));
  const unit = kind === 'seconds' ? ' s' : '';
  return signOf(delta, magnitude) + magnitude + unit;
}

// One bar per phase of a run comparison. Each side is a percent of the largest measured value over both runs.
export function phaseBars(compare) {
  const phases = isRecord(compare) && isRecord(compare.phases) ? compare.phases : {};
  const entries = Object.entries(phases).map(([phase, value]) => {
    const row = isRecord(value) ? value : {};
    return { phase, aS: numberOrNull(row.a_s), bS: numberOrNull(row.b_s) };
  });
  const max = entries.reduce((top, entry) => Math.max(top, entry.aS ?? 0, entry.bS ?? 0), 0);
  const percent = (seconds) => {
    if (seconds === null) return null;
    return max === 0 ? 0 : (seconds / max) * 100;
  };
  return entries.map((entry) => ({
    phase: entry.phase,
    aPct: percent(entry.aS),
    bPct: percent(entry.bS),
    aS: entry.aS,
    bS: entry.bS,
  }));
}
