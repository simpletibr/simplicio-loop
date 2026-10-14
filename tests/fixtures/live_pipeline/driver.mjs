// Node driver for the Simplicio Live pipeline reducer (issue #1402, slice 4b-1).
// stdin: {"steps":[{"action": {...} or null, "now": <ms>}], "runId": "<optional>"}
// stdout: one JSON array with selectView(state, now) for each step, after reduce() of its action.
// A step may carry "drill" (a selectDrill target) or "commands": the view then gains that key for that step only.

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
const steps = Array.isArray(input.steps) ? input.steps : [];
const firstEvent = steps.find((step) => step && step.action && step.action.type === 'event');
const runId = typeof input.runId === 'string'
  ? input.runId
  : (firstEvent ? String(firstEvent.action.event.run_id || '') : '');

const reducerUrl = new URL('../../../simplicio_loop/dashboard/static/live/reducer.js', import.meta.url);
const reducer = await import(reducerUrl.href);
const { initialState, reduce, selectView } = reducer;

// selectDrill and selectCommands are read on demand: a step without drill or commands never reaches them.
function requireExport(name) {
  if (typeof reducer[name] !== 'function') throw new Error(name + ' is not exported by reducer.js');
  return reducer[name];
}

let state = initialState(runId);
const out = [];
for (const step of steps) {
  if (step && step.action) state = reduce(state, step.action);
  const now = Number(step && step.now);
  const view = selectView(state, now);
  if (step && step.drill !== undefined && step.drill !== null) view.drill = requireExport('selectDrill')(state, step.drill, now);
  if (step && step.commands) view.commands = requireExport('selectCommands')(state);
  out.push(view);
}
process.stdout.write(JSON.stringify(out) + '\n');
