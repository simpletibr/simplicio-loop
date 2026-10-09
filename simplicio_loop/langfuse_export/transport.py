"""HTTP transport to Langfuse, stdlib only. Errors are classified; secrets never enter an error text."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, NamedTuple

from .config import DEFAULT_HOST

TRACES_PATH = "/api/public/otel/v1/traces"
SCORES_PATH = "/api/public/scores"


class Result(NamedTuple):
    ok: bool
    retryable: bool
    status: int | None
    error: str


class HttpTransport:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        *,
        public_key: str,
        secret_key: str,
        timeout: float = 10.0,
    ) -> None:
        self.host = host.rstrip("/")
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
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = int(response.status)
            return Result(
                ok=200 <= status < 300, retryable=False, status=status, error=""
            )
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            return Result(
                ok=False, retryable=retryable, status=exc.code, error=f"http {exc.code}"
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return Result(
                ok=False,
                retryable=True,
                status=None,
                error=f"transport {type(exc).__name__}",
            )
