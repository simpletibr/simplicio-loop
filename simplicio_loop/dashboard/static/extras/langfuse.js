// Langfuse widget of the Live extras panel (issue #1610): displays the integration state, trace link, and comparison gates.
// Pure view first (no DOM, no network, no clock), then a renderer that polls every 10000 ms and builds the DOM.
const SCHEMA = 'simplicio.dashboard-langfuse/v1';
const POLL_MS = 10000;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function stringOrNull(value) {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function isValidState(state) {
  return ['off', 'ok', 'sending', 'late', 'error'].includes(state);
}

// Converts the Langfuse API reply to a view object suitable for rendering.
// Returns null if the reply is invalid or the schema/chip is missing.
export function viewOf(reply) {
  if (!isObject(reply) || reply.schema !== SCHEMA) return null;
  const chip = reply.chip;
  if (!isObject(chip) || !isValidState(chip.state)) return null;

  const state = chip.state;
  const label = 'Langfuse: ' + (stringOrNull(chip.label) || 'desconhecido');
  const reason = stringOrNull(chip.reason);

  // When off, return only the chip
  if (state === 'off') {
    return {
      state,
      label,
      reason,
      queue: null,
      link: null,
      notice: null,
      warn: null,
      gates: [],
      tokens: null,
      cost: null,
    };
  }

  // For other states, populate all fields
  let queue = null;
  if (Number.isFinite(reply.queue) && reply.queue >= 0) {
    queue = 'Fila em disco: ' + reply.queue;
  }

  let link = null;
  if (isObject(reply.trace) && stringOrNull(reply.trace.url)) {
    try {
      const url = new URL(reply.trace.url);
      if ((url.protocol === 'https:' || url.protocol === 'http:') && state !== 'error') {
        link = { href: reply.trace.url, text: 'Abrir trace no Langfuse' };
      }
    } catch {
      // Invalid URL; link stays null
    }
  }

  let notice = null;
  if (isObject(reply.trace) && reply.trace.exported === false) {
    notice = 'Trace ainda não enviado ao Langfuse';
  }

  let warn = null;
  if (isObject(reply.compare) && reply.compare.state === 'DIVERGE') {
    warn = 'Atenção: o Langfuse tem valores diferentes dos do loop';
  }

  let gates = [];
  if (isObject(reply.compare) && Array.isArray(reply.compare.gates)) {
    gates = reply.compare.gates
      .filter((gate) => {
        if (!isObject(gate)) return false;
        if (typeof gate.name !== 'string' || gate.name.trim() === '') return false;
        if (typeof gate.passed !== 'boolean') return false;
        return true;
      })
      .slice(0, 20)
      .map((gate) => {
        const passed = gate.passed ? 'passou' : 'falhou';
        const langfuse = stringOrNull(gate.langfuse) || 'desconhecido';
        const text = gate.name + ': ' + passed + ' — Langfuse: ' + langfuse;
        const gateState = gate.langfuse === 'diverge' ? 'DIVERGE' : 'PASS';
        return { text, state: gateState };
      });
  }

  let tokens = null;
  if (isObject(reply.compare) && isObject(reply.compare.tokens)) {
    const tok = reply.compare.tokens;
    const loopData = isObject(tok.loop);
    const langfuseData = isObject(tok.langfuse);
    if (loopData || langfuseData) {
      const loopInput = loopData && Number.isFinite(tok.loop.input) && tok.loop.input >= 0 ? tok.loop.input : null;
      const loopOutput = loopData && Number.isFinite(tok.loop.output) && tok.loop.output >= 0 ? tok.loop.output : null;
      const langfuseInput = langfuseData && Number.isFinite(tok.langfuse.input) && tok.langfuse.input >= 0 ? tok.langfuse.input : null;
      const langfuseOutput = langfuseData && Number.isFinite(tok.langfuse.output) && tok.langfuse.output >= 0 ? tok.langfuse.output : null;
      const loopStr = loopInput !== null ? 'entrada ' + loopInput + ', saída ' + loopOutput : 'não medido';
      const langfuseStr = langfuseInput !== null ? 'entrada ' + langfuseInput + ', saída ' + langfuseOutput : 'não medido';
      const text = 'Tokens medidos — loop: ' + loopStr + '; Langfuse: ' + langfuseStr;
      const tokState = tok.diverge === true ? 'DIVERGE' : 'PASS';
      tokens = { text, state: tokState };
    }
  }

  let cost = null;
  if (isObject(reply.compare) && isObject(reply.compare.cost)) {
    const costReason = stringOrNull(reply.compare.cost.reason);
    if (costReason) {
      cost = { text: 'Custo: ' + costReason, state: 'UNVERIFIED' };
    }
  }

  return {
    state,
    label,
    reason,
    queue,
    link,
    notice,
    warn,
    gates,
    tokens,
    cost,
  };
}

function textNode(tag, className, text, state) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  if (state) node.dataset.state = state;
  return node;
}

// Off has no rows in its view (see viewOf), so the chip is the whole panel; the other states add the rows below it.
function nodesOf(view) {
  const chip = document.createElement('span');
  chip.className = 'lf-chip';
  chip.dataset.state = view.state;
  chip.setAttribute('role', 'status');
  chip.textContent = view.label;
  const head = document.createElement('p');
  head.append(chip);
  const nodes = [head];
  if (view.queue) nodes.push(textNode('p', 'lf-queue', view.queue));
  if (view.link) {
    const link = textNode('a', 'lf-link', view.link.text);
    link.href = view.link.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    nodes.push(link);
  }
  if (view.notice) nodes.push(textNode('p', 'lf-notice', view.notice));
  if (view.reason) nodes.push(textNode('p', 'lf-reason', view.reason));
  if (view.warn) {
    const warn = textNode('p', 'lf-warn', view.warn);
    warn.setAttribute('role', 'alert');
    nodes.push(warn);
  }
  if (view.gates.length) {
    const list = document.createElement('ul');
    list.className = 'lf-gates';
    list.append(...view.gates.map((gate) => {
      const item = document.createElement('li');
      item.dataset.state = gate.state;
      item.textContent = gate.text;
      return item;
    }));
    nodes.push(list);
  }
  if (view.tokens) nodes.push(textNode('p', 'lf-tokens', view.tokens.text, view.tokens.state));
  if (view.cost) nodes.push(textNode('p', 'lf-cost', view.cost.text, view.cost.state));
  return nodes;
}

// Reads /api/runs/<id>/langfuse now and every 10000 ms. The section is created after the first valid reply, right after
// the anchor (#live-extras). A failed or foreign reply keeps what is on screen, so a dead server or Langfuse changes nothing.
export function startLangfuse(readApi, runId, anchor) {
  if (!runId) return;
  const path = '/api/runs/' + encodeURIComponent(runId) + '/langfuse';
  let section = null;
  const load = async () => {
    const view = viewOf(await readApi(path));
    if (view === null) return;
    if (section === null) {
      section = document.createElement('section');
      section.id = 'live-langfuse';
      section.className = 'panel lf-panel';
      section.setAttribute('aria-label', 'Langfuse');
      anchor.after(section);
    }
    section.replaceChildren(...nodesOf(view));
  };
  load();
  setInterval(load, POLL_MS);
}
