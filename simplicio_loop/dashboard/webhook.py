'''Optional alert webhook of the Simplicio Live dashboard (issue #1406). Off unless dashboard.toml sets a URL.

Each raised alert is posted once as JSON while it stays active; clear() re-arms it. A failed post is counted and
never reaches the event stream.
'''
from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

TIMEOUT_S = 5


class Sender:
    def __init__(self, url: str | None, background: bool = True) -> None:
        self.url = url
        self.background = background
        self.failures = 0
        self._sent: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def send(self, run_id: str, alert: dict[str, Any]) -> bool:
        '''Post the alert unless it was already sent and not cleared. True when a post was attempted.'''
        if self.url is None:
            return False
        key = (run_id, alert['id'])
        with self._lock:
            if key in self._sent:
                return False
            self._sent.add(key)
        body = json.dumps({'schema': 'simplicio.dashboard-alert/v1', 'run_id': run_id, 'alert': alert}).encode('utf-8')
        if self.background:
            threading.Thread(target=self._post, args=(body,), daemon=True).start()
        else:
            self._post(body)
        return True

    def clear(self, run_id: str, alert_id: str) -> None:
        with self._lock:
            self._sent.discard((run_id, alert_id))

    def _post(self, body: bytes) -> None:
        request = urllib.request.Request(self.url, data=body, method='POST',
                                         headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(request, timeout=TIMEOUT_S).close()
        except (OSError, ValueError):
            with self._lock:
                self.failures += 1
