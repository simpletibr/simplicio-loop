'''Opt-in settings of the Simplicio Live dashboard, read from `.simplicio-loop/dashboard.toml` (issue #1406).

The file is optional. When it is absent every default holds. A bad file or a bad value never stops the server: the
default stays and the problem is listed in `problems`. Sections: `[alerts] phase_silence_minutes`,
`[notifications] browser` and `[webhook] url`. Browser notifications and the webhook are off unless the file turns
them on.
'''
from __future__ import annotations

import tomllib
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard.alerts import SILENCE_MS

CONFIG_PATH = Path('.simplicio-loop') / 'dashboard.toml'


@dataclass(frozen=True)
class DashboardConfig:
    silence_ms: int = SILENCE_MS
    browser_notifications: bool = False
    webhook_url: str | None = None
    problems: list[str] = field(default_factory=list)

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
    return DashboardConfig(silence_ms, browser, webhook_url, problems)
