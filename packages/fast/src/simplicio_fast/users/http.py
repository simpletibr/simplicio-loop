import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .service import EmailConflictError, UserNotFoundError, UserService


def handler_for(service: UserService) -> type[BaseHTTPRequestHandler]:
    class UserHandler(BaseHTTPRequestHandler):
        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0"))
            return json.loads(self.rfile.read(length)) if length else {}

        def _send(self, status: HTTPStatus, payload: object | None = None) -> None:
            self.send_response(status)
            if payload is None:
                self.end_headers()
                return
            body = json.dumps(payload).encode()
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _route(self) -> tuple[str, str | None]:
            parts = self.path.split("?", 1)[0].strip("/").split("/")
            if parts[0] != "users" or len(parts) > 2:
                return "", None
            return "users", parts[1] if len(parts) == 2 else None

        def do_GET(self) -> None:
            route, user_id = self._route()
            if route != "users":
                return self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            try:
                payload = (
                    service.get(user_id).to_dict()
                    if user_id
                    else [user.to_dict() for user in service.list()]
                )
                self._send(HTTPStatus.OK, payload)
            except UserNotFoundError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(error)})

        def do_POST(self) -> None:
            route, user_id = self._route()
            if route != "users" or user_id:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            self._mutate(
                lambda data: service.create(data["name"], data["email"]),
                HTTPStatus.CREATED,
            )

        def do_PUT(self) -> None:
            route, user_id = self._route()
            if route != "users" or not user_id:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            self._mutate(lambda data: service.update(user_id, **data), HTTPStatus.OK)

        def do_DELETE(self) -> None:
            route, user_id = self._route()
            if route != "users" or not user_id:
                return self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            try:
                service.delete(user_id)
                self._send(HTTPStatus.NO_CONTENT)
            except UserNotFoundError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(error)})

        def _mutate(self, operation: Any, status: HTTPStatus) -> None:
            try:
                self._send(status, operation(self._body()).to_dict())
            except UserNotFoundError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": str(error)})
            except EmailConflictError as error:
                self._send(HTTPStatus.CONFLICT, {"error": str(error)})
            except (ValueError, KeyError) as error:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return UserHandler


def serve(service: UserService, host: str = "127.0.0.1", port: int = 3000) -> None:
    ThreadingHTTPServer((host, port), handler_for(service)).serve_forever()
