// Alert logic for the Simplicio Live page (issue #1406). Pure: no DOM, no clock, no network.
// Run alerts come from the server as alert_snapshot, alert_raised and alert_cleared frames, applied with applyAlertFrame.
// The page adds the one alert only it can know: the stream is lost (connectionAlertsOf). mergeAlerts lists both,
// critical first. diffAlerts names what was raised and cleared between two ticks; activeAlerts hides silenced alerts.
const STREAM_LOST = ['stale', 'offline', 'closed'];
const SEVERITY_ORDER = { critical: 0, warning: 1 };

function isAlert(value) {
  return value !== null && typeof value === 'object' && typeof value.id === 'string' && value.id !== '';
}

// The server map after one frame. A malformed frame leaves the map as it was.
export function applyAlertFrame(current, name, payload) {
  if (name === 'alert_snapshot') {
    if (payload === null || typeof payload !== 'object' || !Array.isArray(payload.alerts)) return current;
    const next = {};
    for (const alert of payload.alerts) {
      if (isAlert(alert)) next[alert.id] = alert;
    }
    return next;
  }
  if (name === 'alert_raised') {
    return isAlert(payload) ? { ...current, [payload.id]: payload } : current;
  }
  if (name === 'alert_cleared') {
    if (payload === null || typeof payload !== 'object' || typeof payload.id !== 'string') return current;
    const next = { ...current };
    delete next[payload.id];
    return next;
  }
  return current;
}

// The page's own alert: the connection to the stream is lost, so the view may be behind.
export function connectionAlertsOf(connection) {
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

// The server alerts and the page's connection alert, critical first, each listed once.
export function mergeAlerts(server, connection) {
  const serverList = Object.values(server || {}).filter(isAlert);
  return [...serverList, ...connectionAlertsOf(connection)]
    .map((alert, position) => ({ alert, position }))
    .sort((left, right) => (SEVERITY_ORDER[left.alert.severity] ?? 1) - (SEVERITY_ORDER[right.alert.severity] ?? 1)
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

// The browser notification for a newly raised alert, or null. Opt-in twice: dashboard.toml turns it on and the
// user grants the permission. A silenced alert never notifies. The tag makes a repeat replace the earlier one.
export function browserNotice(alert, settings, permission, silenced, now) {
  if (!settings || settings.browser_notifications !== true || permission !== 'granted') return null;
  if (Object.hasOwn(silenced, alert.id) && silenced[alert.id] > now) return null;
  return { title: alert.heading, body: alert.why, tag: alert.id };
}
