// Tabs, receipt list and command list of the Simplicio Live drill-down drawer (issue #1405, slice 1405a).
// Text goes in through textContent and attributes only; markup is built with createElement.
import { artifactHref, setAttr, setText } from '/static/live/lanes.js';

const NO_RECEIPTS = 'Nenhum recibo indexado neste run.';
const NO_COMMANDS = 'Sem comandos: o run ainda não informou o caminho do repo.';
const COPIED = 'Comando copiado.';
const COPY_FAILED = 'Não foi possível copiar. Selecione o texto e copie manualmente.';

// Roving tabindex (WAI-ARIA tabs): only the selected tab is in the tab order. Arrows, Home and End move the selection.
export function bindTabs(tablist, tabs, panels, onSelect) {
  let selected = Math.max(0, tabs.findIndex((tab) => tab.getAttribute('aria-selected') === 'true'));
  const select = (index, focus) => {
    selected = index;
    tabs.forEach((tab, position) => {
      const on = position === index;
      setAttr(tab, 'aria-selected', on ? 'true' : 'false');
      setAttr(tab, 'tabindex', on ? '0' : '-1');
      panels[position].hidden = !on;
    });
    if (focus) tabs[index].focus();
    if (onSelect) onSelect(index);
  };
  tabs.forEach((tab, index) => tab.addEventListener('click', () => select(index, false)));
  tablist.addEventListener('keydown', (event) => {
    const current = tabs.indexOf(event.target);
    if (current < 0) return;
    let next = null;
    if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    select(next, true);
  });
  return {
    select(index) {
      if (index !== selected) select(index, false);
    },
  };
}

// Writes the status line for the copy button. Without a clipboard API the reader is told to copy by hand.
export async function copyCommand(text, status) {
  try {
    await navigator.clipboard.writeText(text);
    setText(status, COPIED);
  } catch (error) {
    setText(status, COPY_FAILED);
  }
}

function receiptItem(row, runId, token) {
  const item = document.createElement('li');
  const link = document.createElement('a');
  setAttr(link, 'href', artifactHref(runId, row.name, token) || '#');
  setText(link, row.name);
  const size = document.createElement('span');
  setText(size, row.size + ' bytes');
  const validation = document.createElement('span');
  setAttr(validation, 'data-state', row.validation.state);
  setText(validation, 'Não validado: ' + row.validation.reason);
  item.append(link, size, validation);
  return item;
}

function commandItem(row, status) {
  const item = document.createElement('li');
  const label = document.createElement('span');
  setText(label, row.label);
  const code = document.createElement('code');
  setText(code, row.command);
  const copy = document.createElement('button');
  copy.type = 'button';
  setText(copy, 'Copiar');
  setAttr(copy, 'aria-label', 'Copiar: ' + row.label);
  copy.addEventListener('click', () => copyCommand(row.command, status));
  item.append(label, code, copy);
  return item;
}

// Keyed by content: the lists are rebuilt only when their rows or the run change, so a focused copy button keeps focus.
export function createDrillLists(els) {
  let receiptSignature = '';
  let commandSignature = '';
  return {
    render(model, link) {
      const receiptKey = JSON.stringify([link.runId, link.token, model.receipts]);
      if (receiptKey !== receiptSignature) {
        receiptSignature = receiptKey;
        const items = model.receipts.map((row) => receiptItem(row, link.runId, link.token));
        if (items.length === 0) items.push(placeholder(NO_RECEIPTS));
        els.receipts.replaceChildren(...items);
      }
      const commandKey = JSON.stringify(model.runCommands);
      if (commandKey !== commandSignature) {
        commandSignature = commandKey;
        const items = model.runCommands.map((row) => commandItem(row, els.copyStatus));
        if (items.length === 0) items.push(placeholder(NO_COMMANDS));
        els.commands.replaceChildren(...items);
      }
    },
  };
}

function placeholder(text) {
  const item = document.createElement('li');
  setText(item, text);
  return item;
}
