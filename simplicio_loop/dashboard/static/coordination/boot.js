// Starts the coordination panel: polls GET /api/coordination and renders it. The model and the view load on the first
// successful read; a failed read keeps the last render.
const POLL_MS = 3000;

export function startCoordination(readApi) {
  let coord = null;
  const load = async () => {
    const reply = await readApi('/api/coordination');
    if (reply === null) return;
    if (!coord) {
      const [model, view] = await Promise.all([import('/static/coordination/model.js'), import('/static/coordination/view.js')]);
      const el = (id) => document.getElementById(id);
      coord = { of: model.coordinationOf, view: view.createCoordination({ kanban: el('coord-kanban'), dag: el('coord-dag'), drain: el('coord-drain'), slots: el('coord-slots'), status: el('coord-status') }) };
    }
    coord.view.render(coord.of(reply, Date.now()));
  };
  load();
  setInterval(load, POLL_MS);
}
