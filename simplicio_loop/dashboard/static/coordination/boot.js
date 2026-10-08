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
      // The container is created here: static/live/ is at its size cap, so it cannot carry the markup.
      const worktreesEl = () => {
        let node = el('coord-worktrees');
        if (!node && el('coord-slots')) {
          node = document.createElement('div');
          node.id = 'coord-worktrees';
          node.className = 'coord-worktrees';
          el('coord-slots').after(node);
        }
        return node;
      };
      coord = { of: model.coordinationOf, view: view.createCoordination({ kanban: el('coord-kanban'), dag: el('coord-dag'), drain: el('coord-drain'), slots: el('coord-slots'), status: el('coord-status'), worktrees: worktreesEl() }) };
    }
    coord.view.render(coord.of(reply, Date.now()));
  };
  load();
  setInterval(load, POLL_MS);
}
