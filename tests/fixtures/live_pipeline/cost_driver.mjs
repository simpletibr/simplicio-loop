// Node driver for the pure view of the Live cost widgets (issue #1404), which load on demand from static/extras.
// stdin: {"budget": <GET /api/runs/<id>/budget body>}; stdout: costWidgetsView(budget) as JSON.

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
const widgetsUrl = new URL('../../../simplicio_loop/dashboard/static/extras/cost-widgets.js', import.meta.url);
const { costWidgetsView } = await import(widgetsUrl.href);
process.stdout.write(JSON.stringify(costWidgetsView(input.budget)));
