// Node driver for the Simplicio Live pipeline reducer (issue #1402, slice 4b-1).
// stdin: {"steps":[{"action": {...} or null, "now": <ms>}], "runId": "<optional>"}
// stdout: one JSON array with selectView(state, now) for each step, after reduce() of its action.

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
const steps = Array.isArray(input.steps) ? input.steps : [];
const firstEvent = steps.find((step) => step && step.action && step.action.type === 'event');
const runId = typeof input.runId === 'string'
  ? input.runId
  : (firstEvent ? String(firstEvent.action.event.run_id || '') : '');

const reducerUrl = new URL('../../../simplicio_loop/dashboard/static/live/reducer.js', import.meta.url);
const { initialState, reduce, selectView } = await import(reducerUrl.href);

let state = initialState(runId);
const out = [];
for (const step of steps) {
  if (step && step.action) state = reduce(state, step.action);
  out.push(selectView(state, Number(step && step.now)));
}
process.stdout.write(JSON.stringify(out) + '\n');
