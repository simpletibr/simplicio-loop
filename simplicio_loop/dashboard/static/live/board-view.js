// The board view of the Simplicio Live page: nine columns (eight phases and the off-track siding) rendered from the
// model of boardOf(). Columns and cards stay between polls and change in place, so a focused card keeps its focus.
// Card text goes in through textContent and attributes only.
import { runHref } from './board.js';

const STATE_LABEL = {
  RUNNING: 'Em execução',
  PASS: 'Aprovado',
  FAIL: 'Falhou',
  UNVERIFIED: 'Não verificado',
  STALLED: 'Travado',
  BLOCKED: 'Bloqueado',
  PENDING: 'Pendente',
};
const EMPTY = 'Nenhum run encontrado neste repositório.';

function setAttr(el, name, value) {
  if (value === null || value === undefined || value === false) {
    if (el.hasAttribute(name)) el.removeAttribute(name);
    return;
  }
  const text = value === true ? '' : String(value);
  if (el.getAttribute(name) !== text) el.setAttribute(name, text);
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

function element(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.setAttribute('class', cls);
  return el;
}

// "há 3 min" from an age in milliseconds: minutes, then hours, then days.
function ageText(ms) {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return 'há menos de 1 min';
  if (minutes < 60) return 'há ' + minutes + ' min';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return 'há ' + hours + ' h';
  return 'há ' + Math.floor(hours / 24) + ' d';
}

// A part without a value is emptied and hidden, so it takes no room and says nothing.
function show(el, text) {
  const shown = text !== null && text !== undefined && text !== '';
  setText(el, shown ? text : '');
  setAttr(el, 'hidden', shown ? null : true);
}

function newCard() {
  return {
    item: element('li'),
    body: null,
    parts: {
      state: element('span', 'card-state'),
      run: element('strong', 'card-run'),
      action: element('span', 'card-action'),
      percent: element('span', 'card-percent'),
      age: element('span', 'card-age'),
    },
  };
}

// The body is a link when runHref names a target and a plain span when it does not. A change of kind moves the parts over.
function placeBody(card, href) {
  const tag = href === null ? 'span' : 'a';
  if (card.body === null || card.body.localName !== tag) {
    const body = element(tag, 'card-body');
    body.append(...Object.values(card.parts));
    if (card.body === null) card.item.append(body);
    else card.body.replaceWith(body);
    card.body = body;
  }
  setAttr(card.body, 'href', href);
}

function fillCard(card, row, opts) {
  setAttr(card.item, 'data-state', row.state);
  setAttr(card.item, 'aria-current', row.runId === opts.runId ? 'true' : null);
  placeBody(card, runHref(row.runId, opts.token, opts.pathname));
  const { parts } = card;
  setText(parts.state, STATE_LABEL[row.state] ?? row.state);
  setText(parts.run, row.runId);
  show(parts.action, row.currentAction);
  show(parts.percent, Number.isFinite(row.percent) ? row.percent + '%' : null);
  show(parts.age, Number.isFinite(row.ageMs) ? ageText(row.ageMs) : null);
}

function columnView(key) {
  const section = element('section');
  section.setAttribute('data-column', key);
  const heading = element('h3');
  const list = element('ol');
  section.append(heading, list);
  return { section, heading, list };
}

// Puts the cards in model order. A node already in place is not touched, and nodes left over are removed.
function placeCards(list, items) {
  items.forEach((item, index) => {
    if (list.children[index] !== item) list.insertBefore(item, list.children[index] ?? null);
  });
  while (list.children.length > items.length) list.children[items.length].remove();
}

export function createBoard(root, statusEl) {
  const columns = new Map();
  const cards = new Map();
  let lastKey = null;
  return {
    render(model, opts) {
      const key = JSON.stringify([model, opts]);
      if (key === lastKey) return;
      lastKey = key;
      const present = new Set(model.columns.flatMap((column) => column.cards.map((row) => row.runId)));
      for (const [runId, card] of cards) {
        if (!present.has(runId)) {
          card.item.remove();
          cards.delete(runId);
        }
      }
      for (const column of model.columns) {
        let view = columns.get(column.key);
        if (view === undefined) {
          view = columnView(column.key);
          columns.set(column.key, view);
          root.append(view.section);
        }
        setText(view.heading, column.label + ' (' + column.count + ')');
        const items = column.cards.map((row) => {
          let card = cards.get(row.runId);
          if (card === undefined) {
            card = newCard();
            cards.set(row.runId, card);
          }
          fillCard(card, row, opts);
          return card.item;
        });
        placeCards(view.list, items);
      }
      setText(statusEl, model.total === 0 ? EMPTY : '');
    },
  };
}
