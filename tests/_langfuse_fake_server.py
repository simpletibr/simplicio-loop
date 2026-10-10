"""Servidor HTTP falso da API do Langfuse para os testes do exportador (issue #1595).

Aceita POST em ``/api/public/otel/v1/traces`` e ``/api/public/scores``, valida o Basic auth
(``public_key:secret_key``) e grava cada requisição recebida. ``mode`` escolhe a resposta:

- ``"ok"``: 200 com corpo vazio (aceite);
- ``"error"``: 500 (falha transitória, reenvia depois);
- ``"drop"``: fecha a conexão sem responder (queda de rede, o cliente vê erro de transporte).
- ``"garbage"``: responde com uma linha que não é HTTP (o cliente vê BadStatusLine);
- um inteiro (400, 401, 429, 503...): responde com esse status, sem olhar o auth.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

TRACES_PATH = "/api/public/otel/v1/traces"
SCORES_PATH = "/api/public/scores"


class FakeLangfuse:
    def __init__(
        self, public_key: str = "pk-lf-test-1595", secret_key: str = "sk-lf-test-1595"
    ) -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.mode = "ok"
        self.requests: list[
            dict[str, Any]
        ] = []  # every request that got an answer or was dropped
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def expected_auth(self) -> str:
        raw = f"{self.public_key}:{self.secret_key}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    @property
    def host(self) -> str:
        assert self._server is not None, "server not started"
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def accepted(self, path: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                r for r in self.requests if r["path"] == path and r["status"] == 200
            ]

    def start(self) -> FakeLangfuse:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # keep test output quiet
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if outer.mode == "drop":
                    with outer._lock:
                        outer.requests.append(
                            {"path": self.path, "status": None, "body": None}
                        )
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                if outer.mode == "garbage":
                    with outer._lock:
                        outer.requests.append(
                            {"path": self.path, "status": None, "body": None}
                        )
                    self.wfile.write(b"NOT-HTTP\r\n")
                    self.wfile.flush()
                    self.close_connection = True
                    return
                auth_ok = self.headers.get("Authorization") == outer.expected_auth
                if isinstance(outer.mode, int):
                    status = outer.mode
                elif not auth_ok:
                    status = 401
                else:
                    status = 200 if outer.mode == "ok" else 500
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", errors="replace")
                with outer._lock:
                    outer.requests.append(
                        {
                            "path": self.path,
                            "status": status,
                            "auth_ok": auth_ok,
                            "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": body,
                        }
                    )
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()
