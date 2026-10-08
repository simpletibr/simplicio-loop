'''Alert rules the dashboard server evaluates over one run's event stream (issue #1406, slice 1406b).

AlertWatch applies new events and the clock, then reports the alerts it raised and the ids it cleared since the last
update. One id is raised once while it stays active, so repeated updates never duplicate an alert. The rules mirror the
page reducer: a stall lasts until a different phase starts, a gate is failing while its latest verdict is fail, a silent
phase is one with no event for SILENCE_MS, and the oracle is unverified once the run is done, its receipt is ready and
the oracle gave no verdict. The receipt is read only when the run is done.
'''
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from simplicio_loop.dashboard import budget as budget_mod

SILENCE_MS = 5 * 60 * 1000
SCHEMA = 'simplicio.dashboard-event/v1'
SEVERITY_ORDER = {'critical': 0, 'warning': 1}
NO_REASON = 'sem motivo registrado'
ORACLE_VERDICTS = ('pass', 'fail', 'blocked')


def _to_ms(ts: Any) -> int | None:
    if not isinstance(ts, str):
        return None
    for layout in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            parsed = datetime.strptime(ts, layout)
        except ValueError:
            continue
        return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)
    return None


def _streak(payload: dict[str, Any]) -> int:
    try:
        value = int(payload.get('streak'))
    except (TypeError, ValueError):
        return 1
    return value or 1


def _alert(alert_id: str, rule: str, severity: str, heading: str, why: str, ref: dict[str, Any] | None) -> dict[str, Any]:
    return {'id': alert_id, 'rule': rule, 'severity': severity, 'heading': heading, 'why': why, 'ref': ref}


class AlertWatch:
    '''The alerts active for one event stream. Feed it events in order with update().'''

    def __init__(self, silence_ms: int = SILENCE_MS, budget: dict[str, Any] | None = None) -> None:
        self.silence_ms = silence_ms
        self.budget = budget or {}
        self.used: dict[str, float | None] = {'tokens': None, 'usd': None, 'seconds': None}
        self.first_ms: int | None = None
        self.last_seq = 0
        self.phase: str | None = None
        self.stall: dict[str, Any] | None = None
        self.gates: dict[str, tuple[str, str]] = {}
        self.last_ms: int | None = None
        self.active: dict[str, dict[str, Any]] = {}

    def update(self, events: Iterable[dict[str, Any]], now_ms: int,
               receipt_ready: Callable[[], bool] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
        '''Apply the events and the clock. Returns (alerts raised, ids cleared) since the previous update.'''
        for event in events:
            self._apply(event)
        current = self._evaluate(now_ms, receipt_ready)
        raised = [alert for alert_id, alert in current.items() if alert_id not in self.active]
        cleared = [alert_id for alert_id in self.active if alert_id not in current]
        self.active = current
        return raised, cleared

    def snapshot(self) -> list[dict[str, Any]]:
        '''The alerts active now, critical first.'''
        return list(self.active.values())

    def _apply(self, event: Any) -> None:
        if not isinstance(event, dict) or event.get('schema') != SCHEMA:
            return
        seq = event.get('seq')
        if not isinstance(seq, int) or seq <= self.last_seq:
            return
        self.last_seq = seq
        stamp = _to_ms(event.get('ts'))
        if stamp is not None:
            self.last_ms = stamp
            if self.first_ms is None:
                self.first_ms = stamp
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        kind = event.get('kind')
        phase = event.get('phase') if isinstance(event.get('phase'), str) else None
        if kind in ('token_usage', 'cost_sample'):
            seen = budget_mod.usage([event])
            for key in ('tokens', 'usd'):
                if seen[key] is not None:
                    self.used[key] = (self.used[key] or 0) + seen[key]
        if kind == 'phase_entered' and phase:
            if self.stall is not None and self.stall['phase'] != phase:
                self.stall = None
            self.phase = phase
        elif kind == 'stall_detected':
            self.stall = {'phase': phase, 'streak': _streak(payload)}
        elif kind == 'gate_evaluated' and isinstance(payload.get('gate'), str):
            verdict = payload.get('verdict')
            message = payload.get('message') if isinstance(payload.get('message'), str) else ''
            self.gates[payload['gate']] = (verdict.lower() if isinstance(verdict, str) else '', message)

    def _budget_alerts(self) -> list[dict[str, Any]]:
        found = []
        if self.first_ms is not None and self.last_ms is not None:
            self.used['seconds'] = (self.last_ms - self.first_ms) / 1000
        for key, label in (('tokens', 'tokens'), ('usd', 'USD'), ('seconds', 'segundos')):
            row = budget_mod.project(self.budget.get(key), self.used[key], self.phase)
            ref = {'type': 'logs'}
            if row['state'] == 'EXCEEDED':
                found.append(_alert('budget-exceeded:' + key, 'budget-exceeded', 'critical', 'Orçamento estourado: ' + label,
                                    'Uso de %s passou do limite %s (medido).' % (row['used'], row['limit']), ref))
            elif row['state'] == 'PROJECTED_OVER':
                found.append(_alert('budget-projected:' + key, 'budget-projected', 'warning', 'Projeção passa do orçamento: ' + label,
                                    'Estimado: %s ao fim do run contra o limite %s (extrapolado pela fase).' % (row['projected'], row['limit']), ref))
        return found

    def _evaluate(self, now_ms: int, receipt_ready: Callable[[], bool] | None) -> dict[str, dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if self.stall is not None:
            found.append(_alert('run-stalled', 'run-stalled', 'critical', 'Run sem avanço',
                                'O run está parado: %d sequência(s) de paradas detectadas pelo diário.' % self.stall['streak'],
                                {'type': 'logs'}))
        for gate, (verdict, message) in self.gates.items():
            if verdict == 'fail':
                found.append(_alert('gate-failing:' + gate, 'gate-failing', 'warning', 'Gate falhando: ' + gate,
                                    message or NO_REASON, {'type': 'logs'}))
        if self.last_ms is not None and now_ms - self.last_ms > self.silence_ms:
            minutes = round((now_ms - self.last_ms) / 60000)
            label = self.phase or 'sem fase'
            ref = {'type': 'phase', 'phase': self.phase} if self.phase else {'type': 'logs'}
            found.append(_alert('phase-silent:' + label, 'phase-silent', 'warning',
                                'Sem eventos há %d min' % minutes,
                                'Nenhum evento do loop chegou desde a última atividade da fase ' + label + '.', ref))
        oracle_verdict = self.gates.get('oracle', ('', ''))[0]
        if self.phase == 'done' and oracle_verdict not in ORACLE_VERDICTS and receipt_ready is not None and receipt_ready():
            found.append(_alert('oracle-unverified', 'oracle-unverified', 'warning', 'Oracle sem veredito',
                                'o run terminou sem veredito do oracle', {'type': 'logs'}))
        found.extend(self._budget_alerts())
        found.sort(key=lambda alert: SEVERITY_ORDER[alert['severity']])
        return {alert['id']: alert for alert in found}
