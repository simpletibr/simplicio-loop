// Alert rules for the Simplicio Live page (issue #1406, slice 1406a). Pure: no DOM, no clock, no network.
// alertsOf turns one selectView model into the alerts it implies. Each id names one rule instance, so an alert that
// stays true is the same alert on the next tick. diffAlerts names what was raised and cleared between two ticks.
// activeAlerts hides the alerts the reader silenced until their time passes.
const DEFAULT_SILENCE_MS = 5 * 60 * 1000;
const STREAM_LOST = ['stale', 'offline', 'closed'];
const SEVERITY_ORDER = { critical: 0, warning: 1 };
const NO_REASON = 'sem motivo registrado';

function gateAlerts(gates) {
  return gates
    .filter((gate) => gate.state === 'FAIL')
    .map((gate) => ({
      id: 'gate-failing:' + gate.gate,
      rule: 'gate-failing',
      severity: 'warning',
      heading: 'Gate falhando: ' + gate.gate,
      why: gate.reason || NO_REASON,
      ref: { type: 'logs' },
    }));
}

function stallAlerts(stall) {
  if (!stall.detected) return [];
  return [{
    id: 'run-stalled',
    rule: 'run-stalled',
    severity: 'critical',
    heading: 'Run sem avanço',
    why: 'O run está parado: ' + stall.streak + ' sequência(s) de paradas detectadas pelo diário.',
    ref: { type: 'logs' },
  }];
}

function silenceAlerts(health, phase, thresholdMs) {
  const silence = health.stall.silenceMs;
  if (silence === null || silence <= thresholdMs) return [];
  const label = phase || 'sem fase';
  return [{
    id: 'phase-silent:' + label,
    rule: 'phase-silent',
    severity: 'warning',
    heading: 'Sem eventos há ' + Math.round(silence / 60000) + ' min',
    why: 'Nenhum evento do loop chegou desde a última atividade da fase ' + label + '.',
    ref: phase ? { type: 'phase', phase } : { type: 'logs' },
  }];
}

function streamAlerts(connection) {
  if (!STREAM_LOST.includes(connection)) return [];
  return [{
    id: 'stream-lost',
    rule: 'stream-lost',
    severity: 'warning',
    heading: 'Stream desconectado',
    why: 'O painel não recebe eventos; a visão pode estar atrasada.',
    ref: null,
  }];
}

function oracleAlerts(model) {
  const oracle = model.gates.find((gate) => gate.gate === 'oracle');
  if (model.rail.phase !== 'done' || !model.rail.receiptReady || !oracle || oracle.state !== 'UNVERIFIED') return [];
  return [{
    id: 'oracle-unverified',
    rule: 'oracle-unverified',
    severity: 'warning',
    heading: 'Oracle sem veredito',
    why: oracle.reason || 'o run terminou sem recibo de conclusão',
    ref: { type: 'logs' },
  }];
}

// The alerts the model implies now: critical first, then warnings, each id once.
export function alertsOf(model, options) {
  const thresholdMs = options && Number.isFinite(options.silenceMs) ? options.silenceMs : DEFAULT_SILENCE_MS;
  const raw = [
    ...stallAlerts(model.health.stall),
    ...gateAlerts(model.gates),
    ...silenceAlerts(model.health, model.phase, thresholdMs),
    ...streamAlerts(model.connection),
    ...oracleAlerts(model),
  ];
  const seen = new Set();
  return raw
    .filter((alert) => {
      if (seen.has(alert.id)) return false;
      seen.add(alert.id);
      return true;
    })
    .map((alert, position) => ({ alert, position }))
    .sort((left, right) => SEVERITY_ORDER[left.alert.severity] - SEVERITY_ORDER[right.alert.severity]
      || left.position - right.position)
    .map((entry) => entry.alert);
}

// The ids raised since the previous tick and the ids cleared since it.
export function diffAlerts(previous, current) {
  const before = new Set(previous);
  const now = new Set(current);
  return {
    raised: current.filter((id) => !before.has(id)),
    cleared: previous.filter((id) => !now.has(id)),
  };
}

// Hides an alert while its silence (a timestamp) is later than now.
export function activeAlerts(alerts, silenced, now) {
  return alerts.filter((alert) => !(Object.hasOwn(silenced, alert.id) && silenced[alert.id] > now));
}
