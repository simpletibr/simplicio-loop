// Run navigation for the Simplicio Live page (issue #1402, slice 4b-3). Pure: no DOM, no location, no clock.
// Palette "go to run" commands, the next run for the TV rotation and the URL of a run.
export const TV_ROTATE_MS = 20000;
const MAX_ROTATE_SECONDS = 3600;
const RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function idsOf(runs) {
  const rows = Array.isArray(runs) ? runs : [];
  return rows.map((row) => row && row.run_id).filter((id) => typeof id === 'string' && RUN_ID.test(id));
}

// One palette command per run other than the open one.
export function runCommands(runs, currentId) {
  return idsOf(runs)
    .filter((id) => id !== currentId)
    .map((id) => ({ id: 'run:' + id, label: 'Run ' + id, group: 'Runs', hint: 'Ir para o run' }));
}

// The run after the open one, wrapping around; null when there is nothing to rotate to.
export function nextRunId(runs, currentId) {
  const ids = idsOf(runs);
  if (ids.length < 2) return null;
  const index = ids.indexOf(currentId);
  return ids[(index + 1) % ids.length];
}

// The URL of a run: every other query parameter (token, theme, tv, rotate) is kept.
export function runUrl(pathname, search, runId) {
  const params = new URLSearchParams(search);
  params.set('run', runId);
  return pathname + '?' + params.toString();
}

// The rotation interval in ms: only in TV mode, never under reduced motion, 20 s unless ?rotate=<seconds> says otherwise.
export function rotationMs(search, reducedMotion) {
  const params = new URLSearchParams(search);
  if (params.get('tv') !== '1' || reducedMotion) return null;
  const seconds = Number(params.get('rotate'));
  return Number.isFinite(seconds) && seconds > 0 && seconds <= MAX_ROTATE_SECONDS ? seconds * 1000 : TV_ROTATE_MS;
}
