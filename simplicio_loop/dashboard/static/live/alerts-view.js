// The alert list of the Simplicio Live page (issue #1406, slice 1406a). Text goes in through textContent and attributes only.
// Each alert shows its severity as text, its heading and its reason, with a "Ver" action when it names a drill target
// and a "Silenciar 1 h" action. Rows are rebuilt only when the visible alerts change, so a focused button keeps focus.
import { setAttr, setText } from '/static/live/lanes.js';

const SEVERITY_LABEL = { critical: 'Crítico', warning: 'Aviso' };
const NONE = 'Nenhum alerta ativo.';

function row(alert, handlers) {
  const item = document.createElement('li');
  setAttr(item, 'data-rule', alert.rule);
  const severity = document.createElement('span');
  setAttr(severity, 'data-severity', alert.severity);
  setText(severity, SEVERITY_LABEL[alert.severity] || alert.severity);
  const heading = document.createElement('strong');
  setText(heading, alert.heading);
  const why = document.createElement('p');
  setText(why, alert.why);
  const actions = document.createElement('div');
  if (alert.ref !== null) {
    const view = document.createElement('button');
    view.type = 'button';
    setText(view, 'Ver');
    setAttr(view, 'aria-label', 'Ver: ' + alert.heading);
    view.addEventListener('click', () => handlers.view(alert));
    actions.append(view);
  }
  const silence = document.createElement('button');
  silence.type = 'button';
  setText(silence, 'Silenciar 1 h');
  setAttr(silence, 'aria-label', 'Silenciar 1 hora: ' + alert.heading);
  silence.addEventListener('click', () => handlers.silence(alert));
  actions.append(silence);
  item.append(severity, heading, why, actions);
  return item;
}

function placeholder() {
  const item = document.createElement('li');
  setText(item, NONE);
  return item;
}

export function createAlertList(els, handlers) {
  let signature = '';
  return {
    render(visible, change) {
      setText(els.toggle, 'Alertas (' + visible.length + ')');
      const key = JSON.stringify(visible);
      if (key !== signature) {
        signature = key;
        const items = visible.map((alert) => row(alert, handlers));
        if (items.length === 0) items.push(placeholder());
        els.list.replaceChildren(...items);
      }
      if (change.raised.length > 0) setText(els.status, change.raised.length + ' alerta(s) novo(s).');
      else if (change.cleared.length > 0) setText(els.status, change.cleared.length + ' alerta(s) resolvido(s).');
    },
  };
}
