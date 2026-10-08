// DOM rendering for the Simplicio Live pipeline page. Writes only what changed; payload text goes through textContent.
import { PHASE_META, STATES } from '/static/components/index.js';
import { GATES } from '/static/live/reducer.js';

const CONNECTION = { live: 'live', stale: 'stale', connecting: 'connecting', reconnecting: 'connecting' };

const pad = (value) => String(value).padStart(2, '0');

export function formatClock(ms) {
  if (ms === null || ms === undefined) return '—';
  const date = new Date(ms);
  return pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
}

export function formatDuration(ms) {
  const total = Math.floor(Math.max(0, ms) / 1000);
  const hours = Math.floor(total / 3600);
  const clock = pad(Math.floor((total % 3600) / 60)) + ':' + pad(total % 60);
  return hours > 0 ? pad(hours) + ':' + clock : clock;
}

function labelOf(phase) {
  return (PHASE_META[phase] || {}).label || phase;
}

function stateLabel(state) {
  return STATES[state] || state;
}

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

function artifactHref(runId, ref, token) {
  if (!ref || !runId || !token) return null;
  return '/api/runs/' + encodeURIComponent(runId) + '/artifacts/' + encodeURIComponent(ref)
    + '?t=' + encodeURIComponent(token);
}

function connectionStatus(value) {
  return Object.hasOwn(CONNECTION, value) ? CONNECTION[value] : 'offline';
}

function ensurePhaseItems(list, phases) {
  if (list.children.length === phases.length) return;
  list.replaceChildren(...phases.map((item) => {
    const li = document.createElement('li');
    li.dataset.phase = item.phase;
    return li;
  }));
}

function ensureGateItems(list) {
  if (list.children.length === GATES.length) return;
  list.replaceChildren(...GATES.map((gate) => {
    const li = document.createElement('li');
    li.dataset.gate = gate;
    const badge = document.createElement('sl-gate-badge');
    badge.setAttribute('gate', gate);
    li.append(badge, document.createElement('time'));
    return li;
  }));
}

export function createView() {
  const byId = (id) => document.getElementById(id);
  const agora = byId('agora');
  const field = (name) => agora.querySelector('[data-field=' + name + ']');
  const els = {
    rail: byId('rail'),
    ring: byId('ring'),
    phaseStats: byId('phase-stats'),
    gates: byId('gates'),
    conn: byId('conn'),
    kpiEpm: byId('kpi-epm'),
    kpiHeartbeat: byId('kpi-heartbeat'),
    kpiStall: byId('kpi-stall'),
    empty: byId('empty'),
    runId: byId('run-id'),
    current: field('current'),
    next: field('next'),
    command: field('command'),
    timer: field('timer'),
  };
  let ringPercent = null;
  function renderRail(model) {
    const rail = model.rail;
    setAttr(els.rail, 'phase', rail.phase || 'intake');
    setAttr(els.rail, 'status', rail.status);
    setAttr(els.rail, 'at', rail.at === null ? null : formatClock(rail.at));
    setAttr(els.rail, 'reason', rail.reason);
    setAttr(els.rail, 'receipt-ready', rail.receiptReady);
    if (ringPercent !== model.percent) {
      ringPercent = model.percent;
      els.ring.segments = [
        { label: 'Concluído', value: model.percent, state: model.percent === 100 ? 'PASS' : 'RUNNING' },
        { label: 'Restante', value: 100 - model.percent, state: 'PENDING' },
      ];
    }
    setAttr(els.ring, 'center', model.percent + '%');
    setAttr(els.ring, 'data-percent', model.percent);
  }

  function renderPhases(model) {
    ensurePhaseItems(els.phaseStats, model.phases);
    model.phases.forEach((item, index) => {
      const li = els.phaseStats.children[index];
      const entries = item.entries === 1 ? '1 entrada' : item.entries + ' entradas';
      setAttr(li, 'data-phase', item.phase);
      setAttr(li, 'data-entries', item.entries);
      setAttr(li, 'data-state', item.state);
      setText(li, labelOf(item.phase) + ': ' + entries + ' · ' + formatDuration(item.elapsedMs));
    });
  }

  function renderAgora(model) {
    const agoraModel = model.agora;
    const next = agoraModel.next.text;
    setText(els.current, agoraModel.current.text);
    setText(els.next, next ? labelOf(next) + ' · ' + stateLabel(agoraModel.next.state) : 'fim do pipeline');
    setText(els.command, stateLabel(agoraModel.command.state) + ' · ' + agoraModel.command.reason);
    setText(els.timer, formatDuration(agoraModel.timerMs));
  }

  function renderGates(model, options) {
    ensureGateItems(els.gates);
    model.gates.forEach((gate, index) => {
      const li = els.gates.children[index];
      const badge = li.querySelector('sl-gate-badge');
      setAttr(badge, 'state', gate.state);
      setAttr(badge, 'reason', gate.reason);
      setAttr(badge, 'href', artifactHref(options.runId, gate.ref, options.token));
      setText(li.querySelector('time'), formatClock(gate.at));
    });
  }

  function renderHealth(model) {
    const health = model.health;
    const stall = health.stall;
    setAttr(els.conn, 'status', connectionStatus(model.connection));
    setAttr(els.kpiEpm, 'value', health.eventsPerMinute);
    setAttr(els.kpiHeartbeat, 'value', health.heartbeatAgeMs === null ? '–' : Math.round(health.heartbeatAgeMs / 1000));
    setAttr(els.kpiStall, 'value', stall.detected ? 'Sim' : 'Não');
    setAttr(els.kpiStall, 'state', stall.detected ? 'STALLED' : 'PASS');
    setAttr(els.kpiStall, 'detail', stall.detected ? 'sequência ' + stall.streak : 'nenhum stall detectado');
    const hidden = model.lastSeq > 0;
    if (els.empty.hidden !== hidden) els.empty.hidden = hidden;
  }

  return {
    showMessage(text) {
      setText(els.empty, text);
    },
    render(model, options) {
      setText(els.runId, options.runId ? 'Run ' + options.runId : 'Nenhum run selecionado');
      renderRail(model);
      renderPhases(model);
      renderAgora(model);
      renderGates(model, options);
      renderHealth(model);
    },
  };
}

