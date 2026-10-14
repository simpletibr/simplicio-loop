// Deep links into the Simplicio Live drill-down (issue #1405, slice 1405b). Pure: no DOM, no location, no clock.
// Routes: #/run/<run>/logs, #/run/<run>/phase/<phase>, #/run/<run>/lane/<lane>, #/run/<run>/lane/<lane>/block/<index>,
// #/run/<run>/iteration/<n>, #/run/<run>/phase/<phase>/iteration/<n>.
// The run and lane ids must start with a letter or digit, so '..' and path tricks never parse.
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const PHASE = /^[a-z_]+$/;
const INDEX = /^[0-9]+$/;

function safeId(value) {
  return typeof value === 'string' && SAFE_ID.test(value);
}

// An iteration number is a safe integer >= 0. Its text form must be digits only.
function isIterationText(value) {
  return typeof value === 'string' && INDEX.test(value) && Number.isSafeInteger(Number(value));
}

function isIterationNumber(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

// The drill target a fragment names for this run, or null when the fragment is for another run or is not a route.
export function parseDeepLink(hash, runId) {
  if (typeof hash !== 'string' || !safeId(runId)) return null;
  const parts = hash.replace(/^#/, '').split('/').filter(Boolean);
  if (parts[0] !== 'run' || parts[1] !== runId) return null;
  const rest = parts.slice(2);
  if (rest.length === 1 && rest[0] === 'logs') return { type: 'logs' };
  if (rest.length === 2 && rest[0] === 'phase' && PHASE.test(rest[1])) return { type: 'phase', phase: rest[1] };
  if (rest.length === 2 && rest[0] === 'lane' && safeId(rest[1])) return { type: 'lane', lane: rest[1] };
  if (rest.length === 4 && rest[0] === 'lane' && rest[2] === 'block' && safeId(rest[1]) && INDEX.test(rest[3])) {
    return { type: 'block', lane: rest[1], index: Number(rest[3]) };
  }
  if (rest.length === 2 && rest[0] === 'iteration' && isIterationText(rest[1])) {
    return { type: 'iteration', iteration: Number(rest[1]) };
  }
  if (rest.length === 4 && rest[0] === 'phase' && PHASE.test(rest[1]) && rest[2] === 'iteration' && isIterationText(rest[3])) {
    return { type: 'iteration', iteration: Number(rest[3]), phase: rest[1] };
  }
  return null;
}

// The fragment that names a drill target, or null when the target or the run id cannot be written safely.
export function deepLinkOf(runId, target) {
  if (!safeId(runId) || target === null || typeof target !== 'object') return null;
  const base = '#/run/' + runId;
  if (target.type === 'logs') return base + '/logs';
  if (target.type === 'phase' && PHASE.test(target.phase)) return base + '/phase/' + target.phase;
  if (target.type === 'lane' && safeId(target.lane)) return base + '/lane/' + target.lane;
  if (target.type === 'block' && safeId(target.lane) && Number.isInteger(target.index) && target.index >= 0) {
    return base + '/lane/' + target.lane + '/block/' + target.index;
  }
  if (target.type === 'iteration' && isIterationNumber(target.iteration)) {
    if (target.phase === undefined) return base + '/iteration/' + target.iteration;
    if (typeof target.phase === 'string' && PHASE.test(target.phase)) {
      return base + '/phase/' + target.phase + '/iteration/' + target.iteration;
    }
  }
  return null;
}
