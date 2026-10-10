"""HTTP transport to Langfuse, stdlib only.

Status classes decide what the queue does with a request:

- 2xx: accepted, the request is acked.
- retryable (408, 429, 5xx, network or protocol errors): counted as an attempt, kept for the next window.
- blocking (401, 403, 404, 3xx): the configuration is wrong (keys, host, path). The queue keeps every
  request and nothing is dead-lettered until the operator fixes it.
- permanent (other 4xx): this body is rejected; it goes to ``dead/``.

Redirects are refused, so the Basic auth header never follows one to another host.
"""

from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.request
from typing import Any, NamedTuple

from .config import DEFAULT_HOST, check_host

TRACES_PATH = "/api/public/otel/v1/traces"
SCORES_PATH = "/api/public/scores"
BLOCKING_STATUSES = frozenset({401, 403, 404})
RETRYABLE_STATUSES = frozenset({408, 429})


class Result(NamedTuple):
    ok: bool
    retryable: bool
    status: int | None
    error: str
    blocking: bool = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None  # urllib then raises HTTPError for the 3xx; it is classified as blocking


_OPENER = urllib.request.build_opener(_NoRedirect)


def classify(status: int) -> Result:
    """The queue's decision for an HTTP status (no body involved)."""
    if 200 <= status < 300:
        return Result(ok=True, retryable=False, status=status, error="")
    error = f"http {status}"
    if status in BLOCKING_STATUSES or 300 <= status < 400:
        return Result(
            ok=False, retryable=False, status=status, error=error, blocking=True
        )
    retryable = status in RETRYABLE_STATUSES or status >= 500
    return Result(ok=False, retryable=retryable, status=status, error=error)


class HttpTransport:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        *,
        public_key: str,
        secret_key: str,
        timeout: float = 10.0,
    ) -> None:
        self.host = check_host(host).rstrip("/")
        self.timeout = timeout
        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "x-langfuse-ingestion-version": "4",
        }

    def send(self, kind: str, body: Any) -> Result:
        path = TRACES_PATH if kind == "traces" else SCORES_PATH
        request = urllib.request.Request(
            self.host + path,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=self._headers,
        )
        try:
            with _OPENER.open(request, timeout=self.timeout) as response:
                return classify(int(response.status))
        except urllib.error.HTTPError as exc:
            return classify(exc.code)
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
        ) as exc:
            # BadStatusLine, IncompleteRead and friends are not OSError: they are still a failed request.
            return Result(
                ok=False,
                retryable=True,
                status=None,
                error=f"transport {type(exc).__name__}",
            )
