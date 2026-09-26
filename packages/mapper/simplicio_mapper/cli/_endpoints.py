from __future__ import annotations

import json
import os
import re

from ._shared import ENDPOINT_INVENTORY_SCHEMA

_NUMERIC_ID_SEGMENT = re.compile(r"/[0-9]+(?=/|$)")

_UUID_SEGMENT = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)


def _normalize_endpoint_path(path: str) -> str:
    """Normalize a raw endpoint path into a comparable canonical form.

    Generic rules only — no project-specific collection names are baked in.
    Custom resource collapsing belongs in caller-side configuration, not in
    this helper.
    """
    path = path.strip().split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    path = path.replace("//", "/")
    # Path/query parameter placeholders such as `${foo}` or `{foo}`.
    path = re.sub(r"\$\{[^}]+\}", "{id}", path)
    path = re.sub(r"\{[^}]+\}", "{id}", path)
    # UUIDs anywhere in the path.
    path = _UUID_SEGMENT.sub("/{id}", path)
    # Generic numeric IDs (e.g. /users/42, /orders/1001/items).
    path = _NUMERIC_ID_SEGMENT.sub("/{id}", path)
    return path.rstrip("/") or "/"


def _endpoint_files(root: str):
    skip = {
        ".git",
        "node_modules",
        ".simplicio-loop",
        "dist",
        "build",
        "obj",
        "bin",
        ".venv",
        "venv",
        "__pycache__",
    }
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in (".cs", ".py", ".ts", ".tsx", ".js", ".jsx"):
                yield os.path.join(current, name)


def _route_entry(method: str, path: str, file: str, root: str, kind: str) -> dict:
    return {
        "method": method.upper(),
        "path": _normalize_endpoint_path(path),
        "file": os.path.relpath(file, root).replace(os.sep, "/"),
        "kind": kind,
    }


def _extract_csharp_server_routes(text: str, file: str, root: str) -> list[dict]:
    routes: list[dict] = []
    for match in re.finditer(r"HttpTrigger\((.*?)\)", text, re.S):
        args = match.group(1)
        route_match = re.search(r'Route\s*=\s*"([^"]+)"', args)
        if not route_match:
            continue
        for method in re.findall(r'"(get|post|put|patch|delete)"', args, re.I):
            routes.append(_route_entry(method, route_match.group(1), file, root, "server"))

    class_route = ""
    controller_kind = "contract" if "OpenApiContractControllerBase" in text else "server"
    class_route_match = re.search(r'\[Route\("([^"]+)"\)\]', text)
    if class_route_match:
        class_route = class_route_match.group(1)
    for match in re.finditer(r'\[Http(Get|Post|Put|Patch|Delete)(?:\("([^"]*)"\))?\]', text):
        method = match.group(1)
        suffix = match.group(2) or ""
        if class_route or suffix:
            routes.append(_route_entry(method, f"/{class_route}/{suffix}", file, root, controller_kind))
    return routes


def _extract_python_routes(text: str, file: str, root: str) -> tuple[list[dict], list[dict]]:
    server: list[dict] = []
    client: list[dict] = []
    prefix = ""
    prefix_match = re.search(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]", text, re.S)
    if prefix_match:
        prefix = prefix_match.group(1)
    for match in re.finditer(r"@router\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"]", text, re.I):
        server.append(_route_entry(match.group(1), f"/api/v1{prefix}{match.group(2)}", file, root, "server"))
    for method in ("get", "post", "put", "patch", "delete"):
        pattern = rf"(?:^|[^\w])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.{method}\(\s*f?['\"]([^'\"]+)['\"]"
        for match in re.finditer(pattern, text):
            owner = match.group(1)
            if owner in ("app", "router"):
                continue
            path = match.group(2)
            if path.startswith("/"):
                prefix = "" if path.startswith("/api/v1") else "/api/v1"
                client.append(_route_entry(method, f"{prefix}{path}", file, root, "client"))
    return server, client


def _extract_text_client_calls(text: str, file: str, root: str) -> list[dict]:
    calls: list[dict] = []
    constants = _extract_text_constants(text)
    for method in ("get", "post", "put", "patch", "delete"):
        pattern = rf"\.{method}(?:<[^>]+>)?\(\s*(`[^`]+`|'[^']+'|\"[^\"]+\"|this\.[A-Za-z_]\w*|[A-Za-z_]\w*)"
        for match in re.finditer(pattern, text, re.I):
            path = _resolve_text_endpoint_expression(match.group(1), constants)
            if "/api/v1" in path:
                path = path[path.index("/api/v1") :]
                calls.append(_route_entry(method, path, file, root, "client"))
    return calls


def _is_test_path(file: str, root: str) -> bool:
    rel = os.path.relpath(file, root).replace(os.sep, "/")
    name = os.path.basename(rel)
    return (
        rel.startswith("tests/")
        or "/tests/" in rel
        or name.endswith((".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx", "_test.py"))
        or name.startswith("test_")
    )


def _extract_text_constants(text: str) -> dict[str, str]:
    constants: dict[str, str] = {
        "environment.apiUrl": "/api/v1",
        "apiUrl": "/api/v1",
    }
    pattern = (
        r"(?:private\s+readonly|readonly|const|let|var)?\s*([A-Za-z_]\w*)\s*=\s*(`[^`]+`|'[^']+'|\"[^\"]+\")"
    )
    for match in re.finditer(pattern, text):
        key = match.group(1)
        value = _strip_ts_quote(match.group(2))
        resolved = _resolve_text_endpoint_template(value, constants)
        if "/api/v1" in resolved:
            constants[key] = resolved
            constants[f"this.{key}"] = resolved
    return constants


def _strip_ts_quote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in ("'", '"', "`") and value[-1] == value[0]:
        return value[1:-1]
    return value


def _resolve_text_endpoint_expression(expr: str, constants: dict[str, str]) -> str:
    expr = expr.strip()
    if expr in constants:
        return constants[expr]
    return _resolve_text_endpoint_template(_strip_ts_quote(expr), constants)


def _resolve_text_endpoint_template(value: str, constants: dict[str, str]) -> str:
    for key in sorted(constants, key=len, reverse=True):
        value = value.replace(f"${{{key}}}", constants[key])
    value = value.replace("environment.apiUrl", "/api/v1")
    return re.sub(r"\$\{[^}]+\}", "{id}", value)


def _endpoint_inventory_for(root: str) -> dict:
    root = os.path.abspath(root)
    server: list[dict] = []
    client: list[dict] = []
    seen_server: set[tuple[str, str, str]] = set()
    seen_client: set[tuple[str, str, str]] = set()
    for file in _endpoint_files(root):
        try:
            with open(file, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        ext = os.path.splitext(file)[1].lower()
        collect_client_calls = not _is_test_path(file, root)
        if ext == ".cs":
            server.extend(_extract_csharp_server_routes(text, file, root))
        elif ext == ".py":
            py_server, py_client = _extract_python_routes(text, file, root)
            server.extend(py_server)
            if collect_client_calls:
                client.extend(py_client)
        if collect_client_calls and ext in (".ts", ".tsx", ".js", ".jsx"):
            client.extend(_extract_text_client_calls(text, file, root))

    def unique(entries: list[dict], seen: set[tuple[str, str, str]]) -> list[dict]:
        out: list[dict] = []
        for item in entries:
            key = (item["method"], item["path"], item["file"])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return sorted(out, key=lambda item: (item["method"], item["path"], item["file"]))

    server = unique(server, seen_server)
    client = unique(client, seen_client)
    return {
        "root": root.replace(os.sep, "/"),
        "server_routes": server,
        "client_calls": client,
        "counts": {
            "server_routes": len({(item["method"], item["path"]) for item in server}),
            "runtime_server_routes": len(
                {(item["method"], item["path"]) for item in server if item["kind"] == "server"}
            ),
            "contract_server_routes": len(
                {(item["method"], item["path"]) for item in server if item["kind"] == "contract"}
            ),
            "client_calls": len({(item["method"], item["path"]) for item in client}),
        },
    }


def _run_endpoints(opts: dict) -> int:
    client_inventory = _endpoint_inventory_for(opts["root"])
    server_inventory = _endpoint_inventory_for(opts["against"]) if opts["against"] else client_inventory
    server_pairs = {
        (item["method"], item["path"])
        for item in server_inventory["server_routes"]
        if item["kind"] == "server"
    }
    client_pairs = {(item["method"], item["path"]) for item in client_inventory["client_calls"]}
    client_sources: dict[tuple[str, str], list[str]] = {}
    for item in client_inventory["client_calls"]:
        key = (item["method"], item["path"])
        client_sources.setdefault(key, [])
        if item["file"] not in client_sources[key]:
            client_sources[key].append(item["file"])
    missing = [
        {"method": method, "path": path, "sources": sorted(client_sources.get((method, path), []))}
        for method, path in sorted(client_pairs - server_pairs)
    ]
    payload = {
        "schema": ENDPOINT_INVENTORY_SCHEMA,
        "client_root": client_inventory["root"],
        "server_root": server_inventory["root"],
        "counts": {
            "client_calls": len(client_pairs),
            "server_routes": len(server_pairs),
            "contract_routes": server_inventory["counts"]["contract_server_routes"],
            "missing_from_server": len(missing),
        },
        "client_calls": client_inventory["client_calls"],
        "server_routes": server_inventory["server_routes"],
        "missing_from_server": missing,
    }
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"client_calls={payload['counts']['client_calls']} "
            f"server_routes={payload['counts']['server_routes']} "
            f"missing_from_server={payload['counts']['missing_from_server']}"
        )
        for item in missing:
            print(f"{item['method']} {item['path']}")
    return 0
