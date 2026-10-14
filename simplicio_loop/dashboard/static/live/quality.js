// Simplicio Live quality reducer: tests, lint, coverage and diff per iteration. Pure: no DOM, no network, no clock.
// Every number that reaches the view is validated here; an event with a bad required number is ignored whole.
export const QUALITY_CAP = 200;
export const COVERAGE_TARGET = 85;
const FILES_CAP = 200;
const MINUS = '−';
const NO_PRODUCER = 'sem produtor no fluxo atual';

export function initialQuality() {
  return { byIteration: {}, order: [] };
}

function isCount(value) {
  return Number.isInteger(value) && value >= 0;
}

function countOrNull(value) {
  return isCount(value) ? value : null;
}

function durationOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function percentOrNull(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
}

function countOf(table, key) {
  return Object.hasOwn(table, key) ? table[key] : 0;
}

function pluralize(count, one, many) {
  return count === 1 ? one : many;
}

function decimal(value, digits) {
  return value.toFixed(digits).replace('.', ',');
}

function unverified() {
  return { state: 'UNVERIFIED', reason: NO_PRODUCER };
}

function testRecord(payload) {
  const passed = countOrNull(payload.passed);
  const failed = countOrNull(payload.failed);
  const errors = countOrNull(payload.errors);
  if (passed === null || failed === null || errors === null) return null;
  return {
    passed,
    failed,
    errors,
    skipped: countOrNull(payload.skipped),
    total: countOrNull(payload.total),
    durationS: durationOrNull(payload.duration_s),
    failedIds: Array.isArray(payload.failed_ids) && payload.failed_ids.every((id) => typeof id === 'string')
      ? payload.failed_ids.slice(0, 100) : null,
  };
}

// Keeps the rule counts that are valid; a value that is not an object yields null (no rule data).
function byRuleOrNull(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
  const rules = [];
  for (const rule of Object.keys(value)) {
    if (isCount(value[rule])) rules.push([rule, value[rule]]);
  }
  return Object.fromEntries(rules);
}

function lintRecord(payload) {
  const errors = countOrNull(payload.errors);
  const warnings = countOrNull(payload.warnings);
  if (errors === null || warnings === null) return null;
  return { errors, warnings, byRule: byRuleOrNull(payload.by_rule) };
}

function coverageRecord(payload) {
  const percent = percentOrNull(payload.percent);
  return percent === null ? null : { percent };
}

function diffRecord(payload) {
  if (!Array.isArray(payload.files)) return null;
  const filesTotal = countOrNull(payload.files_total);
  const added = countOrNull(payload.added);
  const deleted = countOrNull(payload.deleted);
  if (filesTotal === null || added === null || deleted === null) return null;
  const names = payload.files.filter((name) => typeof name === 'string');
  return { files: unionFiles([], names), reportedTotal: filesTotal, added, deleted };
}

// Union in first-seen order, capped at FILES_CAP names.
function unionFiles(first, second) {
  const seen = new Set(first);
  const files = first.slice();
  for (const name of second) {
    if (files.length >= FILES_CAP) break;
    if (!seen.has(name)) {
      seen.add(name);
      files.push(name);
    }
  }
  return files;
}

// Maps an event to its selection key and a record. The record is null when a required number is missing or invalid.
function recordFor(event) {
  const payload = event.payload;
  if (payload === null || typeof payload !== 'object') return null;
  if (event.kind === 'test_result') return ['tests', testRecord(payload)];
  if (event.kind === 'lint_result') return ['lint', lintRecord(payload)];
  if (event.kind === 'coverage_result') return ['coverage', coverageRecord(payload)];
  if (event.kind === 'apply_result' && payload.step === 'diff') return ['diff', diffRecord(payload)];
  return null;
}

// Tests, lint and coverage keep the last record of an iteration. Diff accumulates within the iteration.
function mergeRecord(key, previous, record) {
  if (key !== 'diff' || previous === undefined) return record;
  return {
    files: unionFiles(previous.files, record.files),
    reportedTotal: Math.max(previous.reportedTotal, record.reportedTotal),
    added: previous.added + record.added,
    deleted: previous.deleted + record.deleted,
  };
}

function iterationOf(event, currentIteration) {
  if (Number.isInteger(event.iteration)) return event.iteration;
  if (Number.isInteger(currentIteration)) return currentIteration;
  return null;
}

// Stores the bucket and keeps only the newest QUALITY_CAP iterations, ascending. A bucket older than those is dropped.
function withBucket(state, number, bucket) {
  const known = Object.hasOwn(state.byIteration, number);
  const order = known ? state.order.slice() : state.order.concat([number]);
  order.sort((a, b) => a - b);
  const kept = order.slice(-QUALITY_CAP);
  if (!kept.includes(number)) return state;
  const byIteration = {};
  for (const iteration of kept) byIteration[iteration] = iteration === number ? bucket : state.byIteration[iteration];
  return { byIteration, order: kept };
}

export function reduceQuality(state, event, currentIteration) {
  if (event === null || typeof event !== 'object') return state;
  const entry = recordFor(event);
  if (entry === null || entry[1] === null) return state;
  const number = iterationOf(event, currentIteration);
  if (number === null) return state;
  const [key, record] = entry;
  const bucket = Object.hasOwn(state.byIteration, number) ? state.byIteration[number] : {};
  const merged = mergeRecord(key, Object.hasOwn(bucket, key) ? bucket[key] : undefined, record);
  return withBucket(state, number, { ...bucket, [key]: merged });
}

// Entries for one key, ascending by iteration.
function entriesWith(state, key) {
  const entries = [];
  for (const iteration of state.order) {
    const bucket = state.byIteration[iteration];
    if (Object.hasOwn(bucket, key)) entries.push({ iteration, record: bucket[key] });
  }
  return entries;
}

function selectTests(state) {
  const entries = entriesWith(state, 'tests');
  if (entries.length === 0) return unverified();
  const { record, iteration } = entries[entries.length - 1];
  const failing = record.failed + record.errors;
  const previous = entries.length > 1 ? entries[entries.length - 2].record : null;
  const deltaFailed = previous === null ? null : failing - (previous.failed + previous.errors);
  const parts = [
    `${record.passed} ${pluralize(record.passed, 'passou', 'passaram')}`,
    `${record.failed} ${pluralize(record.failed, 'falhou', 'falharam')}`,
  ];
  if (record.errors > 0) parts.push(`${record.errors} ${pluralize(record.errors, 'erro', 'erros')}`);
  if (record.skipped !== null) parts.push(`${record.skipped} ${pluralize(record.skipped, 'ignorado', 'ignorados')}`);
  let reason = parts.join(', ');
  if (record.durationS !== null) reason += ` em ${decimal(record.durationS, 1)} s`;
  reason += ` (iteração ${iteration})`;
  return {
    state: failing > 0 ? 'FAIL' : 'PASS',
    reason,
    counts: {
      passed: record.passed,
      failed: record.failed,
      skipped: record.skipped,
      errors: record.errors,
      total: record.total,
    },
    durationS: record.durationS,
    iteration,
    deltaFailed,
    series: entries.map((entry) => ({ iteration: entry.iteration, failed: entry.record.failed })),
  };
}

function selectLint(state) {
  const entries = entriesWith(state, 'lint');
  if (entries.length === 0) return unverified();
  const { record, iteration } = entries[entries.length - 1];
  const comparable = entries.slice(0, -1).filter((entry) => entry.record.byRule !== null);
  const previous = comparable.length > 0 ? comparable[comparable.length - 1].record : null;
  let newCount = null;
  let resolvedCount = null;
  if (record.byRule !== null && previous !== null) {
    newCount = 0;
    resolvedCount = 0;
    const rules = new Set([...Object.keys(record.byRule), ...Object.keys(previous.byRule)]);
    for (const rule of rules) {
      const change = countOf(record.byRule, rule) - countOf(previous.byRule, rule);
      if (change > 0) newCount += change;
      else resolvedCount -= change;
    }
  }
  let reason = `${record.errors} ${pluralize(record.errors, 'erro', 'erros')}, `
    + `${record.warnings} ${pluralize(record.warnings, 'aviso', 'avisos')} (iteração ${iteration})`;
  if (newCount !== null) reason += `; novos ${newCount}, resolvidos ${resolvedCount}`;
  return {
    state: record.errors > 0 ? 'FAIL' : 'PASS',
    reason,
    errors: record.errors,
    warnings: record.warnings,
    byRule: record.byRule === null ? null : { ...record.byRule },
    newCount,
    resolvedCount,
    series: entries.map((entry) => ({
      iteration: entry.iteration,
      errors: entry.record.errors,
      warnings: entry.record.warnings,
    })),
    iteration,
  };
}

function selectCoverage(state) {
  const entries = entriesWith(state, 'coverage');
  if (entries.length === 0) return unverified();
  const { record, iteration } = entries[entries.length - 1];
  const percent = record.percent;
  let reason = `cobertura ${decimal(percent, 1)}% de ${decimal(COVERAGE_TARGET, 0)}% (iteração ${iteration})`;
  if (entries.length > 1) {
    const change = Math.round((percent - entries[entries.length - 2].record.percent) * 10) / 10;
    reason += `, ${change < 0 ? MINUS : '+'}${decimal(Math.abs(change), 1)} pp`;
  }
  return {
    state: percent >= COVERAGE_TARGET ? 'PASS' : 'FAIL',
    reason,
    percent,
    target: COVERAGE_TARGET,
    series: entries.map((entry) => ({ iteration: entry.iteration, percent: entry.record.percent })),
    iteration,
  };
}

// A diff is a fact, so its state is PASS whenever the iteration has one. The file count is the listed names,
// or the largest files_total reported when that is higher (the listed names are capped).
function selectDiff(state) {
  const entries = entriesWith(state, 'diff');
  if (entries.length === 0) return unverified();
  const filesOf = (record) => Math.max(record.files.length, record.reportedTotal);
  const { record, iteration } = entries[entries.length - 1];
  const filesTotal = filesOf(record);
  const previous = entries.length > 1 ? entries[entries.length - 2].record : null;
  const cumulative = { added: 0, deleted: 0, files: 0 };
  for (const entry of entries) {
    cumulative.added += entry.record.added;
    cumulative.deleted += entry.record.deleted;
    cumulative.files += filesOf(entry.record);
  }
  return {
    state: 'PASS',
    reason: `${filesTotal} ${pluralize(filesTotal, 'arquivo', 'arquivos')}, `
      + `+${record.added} ${MINUS}${record.deleted} (iteração ${iteration})`,
    files: record.files.slice(),
    filesTotal,
    added: record.added,
    deleted: record.deleted,
    cumulative,
    vsPrevious: previous === null ? null : {
      added: record.added - previous.added,
      deleted: record.deleted - previous.deleted,
    },
    iteration,
  };
}

export function selectQuality(state) {
  return {
    tests: selectTests(state),
    lint: selectLint(state),
    coverageTrend: selectCoverage(state),
    diff: selectDiff(state),
  };
}
