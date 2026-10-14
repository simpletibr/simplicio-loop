'''Opt-in settings of the Simplicio Live dashboard, read from `.simplicio-loop/dashboard.toml` (issue #1406).

The file is optional. When it is absent every default holds. A bad file or a bad value never stops the server: the
default stays and the problem is listed in `problems`. Sections: `[alerts] phase_silence_minutes`,
`[alerts] stall_fingerprint_repeats`, `decision_wait_minutes`, `[alerts.phase_silence]`, `[notifications] browser` and `[webhook] url`. Browser notifications and the webhook are off unless the file turns
them on.
'''
from __future__ import annotations

import tomllib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard.alerts import DECISION_WAIT_MS, SILENCE_MS, STALL_REPEATS

CONFIG_PATH = Path('.simplicio-loop') / 'dashboard.toml'


@dataclass(frozen=True)
class DashboardConfig:
    silence_ms: int = SILENCE_MS
    browser_notifications: bool = False
    webhook_url: str | None = None
    problems: list[str] = field(default_factory=list)
    phase_silence_ms: dict[str, int] = field(default_factory=dict)
    stall_repeats: int = STALL_REPEATS
    decision_wait_ms: int = DECISION_WAIT_MS

    def public(self) -> dict[str, bool]:
        '''What the page may know. The webhook URL stays on the server: it can carry a secret.'''
        return {'browser_notifications': self.browser_notifications, 'webhook': self.webhook_url is not None}


def _section(data: dict[str, Any], name: str, problems: list[str]) -> dict[str, Any]:
    value = data.get(name, {})
    if isinstance(value, dict):
        return value
    problems.append('[%s] must be a table' % name)
    return {}


def load(repo_root: Any) -> DashboardConfig:
    path = Path(repo_root) / CONFIG_PATH
    if not path.is_file():
        return DashboardConfig()
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        return DashboardConfig(problems=['dashboard.toml unreadable: %s' % error])
    problems: list[str] = []
    silence_ms = SILENCE_MS
    minutes = _section(data, 'alerts', problems).get('phase_silence_minutes')
    if minutes is not None:
        if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes > 0:
            silence_ms = int(minutes * 60 * 1000)
        else:
            problems.append('alerts.phase_silence_minutes must be a number above 0')
    alert_section = _section(data, 'alerts', problems)
    stall_repeats = STALL_REPEATS
    repeats = alert_section.get('stall_fingerprint_repeats')
    if repeats is not None:
        if isinstance(repeats, int) and not isinstance(repeats, bool) and repeats >= 2:
            stall_repeats = repeats
        else:
            problems.append('alerts.stall_fingerprint_repeats must be an integer of 2 or more')
    decision_wait_ms = DECISION_WAIT_MS
    wait = alert_section.get('decision_wait_minutes')
    if wait is not None:
        if isinstance(wait, (int, float)) and not isinstance(wait, bool) and wait > 0:
            decision_wait_ms = int(wait * 60 * 1000)
        else:
            problems.append('alerts.decision_wait_minutes must be a number above 0')
    phase_silence_ms: dict[str, int] = {}
    table = alert_section.get('phase_silence', {})
    if isinstance(table, dict):
        for phase, value in table.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                phase_silence_ms[phase] = int(value * 60 * 1000)
            else:
                problems.append('alerts.phase_silence.%s must be a number above 0' % phase)
    else:
        problems.append('[alerts.phase_silence] must be a table')
    browser = False
    flag = _section(data, 'notifications', problems).get('browser')
    if flag is not None:
        if isinstance(flag, bool):
            browser = flag
        else:
            problems.append('notifications.browser must be true or false')
    webhook_url = None
    url = _section(data, 'webhook', problems).get('url')
    if url is not None:
        parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
        if parsed is not None and parsed.scheme in ('http', 'https') and parsed.netloc:
            webhook_url = url
        else:
            problems.append('webhook.url must be an http or https URL')
    return DashboardConfig(silence_ms, browser, webhook_url, problems, phase_silence_ms, stall_repeats, decision_wait_ms)
