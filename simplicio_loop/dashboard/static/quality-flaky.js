// Flaky tests (issue #1403). Kept outside static/live to respect that directory's size cap.
const NO_IDS = 'sem ids por teste: o produtor emite contagens, não identidade de teste';

// A flip (fail to pass or back) is flaky when its later iteration has no code change: no diff, or added and deleted 0.
export function selectFlaky(state) {
  const entries = state.order
    .filter((iteration) => state.byIteration[iteration].tests?.failedIds)
    .map((iteration) => ({ iteration, record: state.byIteration[iteration].tests }));
  if (entries.length < 2) return { state: 'UNVERIFIED', reason: NO_IDS };
  const flips = new Map();
  entries.slice(1).forEach((entry, i) => {
    const diff = state.byIteration[entry.iteration].diff;
    if (diff && (diff.added || diff.deleted)) return;
    const before = entries[i].record.failedIds;
    const after = entry.record.failedIds;
    for (const id of new Set([...before, ...after])) {
      if (before.includes(id) !== after.includes(id)) flips.set(id, (flips.get(id) || 0) + 1);
    }
  });
  if (flips.size === 0) return { state: 'PASS', reason: `nenhum teste instável (ids observados em ${entries.length} iterações)`, ids: [] };
  const ids = [...flips].sort((a, b) => b[1] - a[1]).slice(0, 20).map(([id, flipCount]) => ({ id, flips: flipCount }));
  const names = ids.map((item) => `${item.id} (${item.flips} ${item.flips === 1 ? 'virada' : 'viradas'})`);
  return {
    state: 'FAIL',
    reason: `${flips.size === 1 ? '1 teste instável' : flips.size + ' testes instáveis'}: ${names.join(', ')}`,
    ids,
  };
}
