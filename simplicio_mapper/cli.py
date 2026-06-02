"""Command-line entry point for simplicio-mapper.

Mirrors ``bin/map.js``: generates or refreshes the machine-readable mapper
artifacts under ``.simplicio/``. Exposed as the ``simplicio-mapper`` and
``llm-project-mapper`` console scripts (see ``pyproject.toml``).
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import time
from typing import Sequence

from . import __version__
from .mapper import export_architecture_docs, write_architecture_docs, write_mapping_artifacts

INDEX_RESULT_SCHEMA = "simplicio.mapper-index/v1"
INDEX_STATE_SCHEMA = "simplicio.mapper-index-state/v1"
ENDPOINT_INVENTORY_SCHEMA = "simplicio.endpoint-inventory/v1"
SCREEN_INVENTORY_SCHEMA = "simplicio.screen-inventory/v1"
FRESHNESS_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".docusaurus",
    "build",
    "dist",
    "coverage",
    "playwright-report",
    "test-results",
    "__pycache__",
    ".pytest_cache",
}

HELP_TEXT = """simplicio-mapper map

Generate or update machine-readable mapper artifacts.

USAGE
  simplicio-mapper index <path> [--json] [--verbose] [--update]
  simplicio-mapper endpoints <path> [--against <server-root>] [--json]
  simplicio-mapper screens <path> [--json]
  simplicio-mapper docs <path> [--json]
  simplicio-mapper export-docs <path> --target <dir> [--json]
  simplicio-mapper map [--root <dir>] [--incremental] [--watch]
  simplicio-mapper update [--root <dir>] [--watch]

OPTIONS
  index <path>          Idempotently create or refresh .simplicio artifacts.
  endpoints <path>      Extract client/server HTTP endpoint inventory.
  screens <path>        Extract frontend route/screen inventory.
  docs <path>           Render architecture inventory markdown under .simplicio/docs.
  export-docs <path>    Copy rendered markdown docs to a local target directory.
  --against <dir>       Compare endpoint client calls against server routes.
  --target <dir>        Local target directory for export-docs.
  --docs                Render markdown docs after map/index.
  --no-docs             Keep map/index JSON-only.
  --docs-only           Render markdown docs without refreshing JSON first.
  --json-only           Compatibility alias for --no-docs.
  --changed-only        Compatibility alias for incremental refresh workflows.
  --background          Start an index refresh in a detached background process.
  --json                Emit structured index output.
  --update              Compatibility alias for index refresh workflows.
  --verbose             Show progress during index refreshes.
  --root <dir>          Project root to map. Defaults to cwd.
  --stack <name>        Stack hint when .starter-meta.json is absent.
  --product-name <name> Product name hint when .starter-meta.json is absent.
  --out <dir>           Artifact directory. Defaults to .simplicio.
  --incremental         Record changed files and update existing artifacts.
  --watch               Re-run mapping when local files change.
  --silent              Minimal output.
  -V, --version         Show version and exit.
  -h, --help            Show this help
"""


def _read_json_safe(file: str) -> dict:
    try:
        with open(file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _parse_args(argv: Sequence[str]) -> dict:
    opts = {
        "root": os.getcwd(),
        "out": ".simplicio",
        "stack": "",
        "product_name": "",
        "incremental": False,
        "watch": False,
        "silent": False,
        "json": False,
        "verbose": False,
        "docs": False,
        "docs_only": False,
        "background": False,
        "command": "map",
        "against": "",
        "target": "",
    }
    commands = ("index", "map", "update", "endpoints", "screens", "docs", "export-docs")
    command = argv[0] if argv and argv[0] in commands else "map"
    opts["command"] = command
    if command == "index":
        opts["silent"] = True
    if command == "update":
        opts["incremental"] = True
    i = 1 if argv and argv[0] in commands else 0
    while i < len(argv):
        arg = argv[i]
        if command in ("index", "endpoints", "screens", "docs", "export-docs") and not arg.startswith("-"):
            opts["root"] = arg
        elif arg == "--against":
            i += 1
            opts["against"] = argv[i]
        elif arg == "--target":
            i += 1
            opts["target"] = argv[i]
        elif arg == "--root":
            i += 1
            opts["root"] = argv[i]
        elif arg == "--out":
            i += 1
            opts["out"] = argv[i]
        elif arg == "--stack":
            i += 1
            opts["stack"] = argv[i]
        elif arg == "--product-name":
            i += 1
            opts["product_name"] = argv[i]
        elif arg == "--incremental":
            opts["incremental"] = True
        elif arg == "--update":
            opts["incremental"] = True
        elif arg == "--watch":
            opts["watch"] = True
        elif arg == "--docs":
            opts["docs"] = True
        elif arg == "--no-docs":
            opts["docs"] = False
        elif arg == "--json-only":
            opts["docs"] = False
        elif arg == "--docs-only":
            opts["docs"] = True
            opts["docs_only"] = True
        elif arg == "--changed-only":
            opts["incremental"] = True
        elif arg == "--background":
            opts["background"] = True
        elif arg == "--silent":
            opts["silent"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--verbose":
            opts["verbose"] = True
            opts["silent"] = False
        elif arg in ("-h", "--help"):
            print(HELP_TEXT)
            sys.exit(0)
        elif arg in ("-V", "--version"):
            print(__version__)
            sys.exit(0)
        else:
            print(f"Unknown {command} option: {arg}", file=sys.stderr)
            print("Run `simplicio-mapper --help` for usage.", file=sys.stderr)
            sys.exit(2)
        i += 1
    return opts


def _run_once(opts: dict) -> dict:
    root = os.path.abspath(opts["root"])
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts["stack"]:
        meta["stack"] = opts["stack"]
    if opts["product_name"]:
        meta["product_name"] = opts["product_name"]
    log = (lambda _line: None) if opts["silent"] else print
    return write_mapping_artifacts(
        cwd=root,
        meta=meta,
        incremental=opts["incremental"],
        output_dir=opts["out"],
        log=log,
    )


def _signature(root: str, out: str) -> tuple:
    abs_out = os.path.abspath(os.path.join(root, out))
    entries = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
        ]
        for name in files:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((path, stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(entries))


def _state_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index-state.json")


def _lock_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "index.lock")


def _acquire_index_lock(root: str, out: str) -> str | None:
    path = _lock_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    return path


def _release_index_lock(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _artifact_paths(root: str, out: str) -> dict[str, str]:
    abs_out = os.path.abspath(os.path.join(root, out))
    return {
        "project_map": os.path.join(abs_out, "project-map.json"),
        "precedent_index": os.path.join(abs_out, "precedent-index.json"),
        "architecture_inventory": os.path.join(abs_out, "architecture-inventory.json"),
        "symbol_index": os.path.join(abs_out, "symbol-index.json"),
        "call_graph": os.path.join(abs_out, "call-graph.json"),
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_signature(root: str, out: str) -> dict | None:
    ignored_out = os.path.relpath(os.path.abspath(os.path.join(root, out)), root)
    ignored_out = ignored_out.replace(os.sep, "/").rstrip("/") or ".simplicio"
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".",
                f":!{ignored_out}",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode != 0 or status.returncode != 0:
        return None
    tree = _tree_signature(root, out)
    return {
        "kind": "git",
        "head": head.stdout.strip(),
        "status_hash": _hash_text(status.stdout),
        "tree_hash": tree.get("hash"),
    }


def _tree_signature(root: str, out: str) -> dict:
    digest = hashlib.sha256()
    abs_out = os.path.abspath(os.path.join(root, out))
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in FRESHNESS_SKIP_DIRS
            and os.path.abspath(os.path.join(current, d)) != abs_out
        ]
        for name in sorted(files):
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return {"kind": "tree", "hash": digest.hexdigest()}


def _freshness_signature(root: str, out: str) -> dict:
    return _git_signature(root, out) or _tree_signature(root, out)


def _read_index_state(root: str, out: str) -> dict:
    return _read_json_safe(_state_path(root, out))


def _write_index_state(root: str, out: str, signature: dict, counts: dict | None = None) -> None:
    path = _state_path(root, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "schema": INDEX_STATE_SCHEMA,
        "signature": signature,
        "counts": counts or {},
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _artifacts_exist(paths: dict[str, str]) -> bool:
    return all(os.path.exists(path) for path in paths.values())


def _index_result(
    root: str,
    out: str,
    *,
    status: str,
    skipped_reason: str | None = None,
    run_result: dict | None = None,
    counts: dict | None = None,
    error: str | None = None,
) -> dict:
    paths = _artifact_paths(root, out)
    project_map = run_result.get("project_map", {}) if run_result else {}
    precedent_index = run_result.get("precedent_index", {}) if run_result else {}
    architecture_inventory = run_result.get("architecture_inventory", {}) if run_result else {}
    symbol_index = run_result.get("symbol_index", {}) if run_result else {}
    call_graph = run_result.get("call_graph", {}) if run_result else {}
    changed_files = list(project_map.get("changed_files") or [])
    counts = counts or {
        "files": len(project_map.get("files", []) or []),
        "precedents": len(precedent_index.get("items", []) or []),
        "changed_files": len(changed_files),
        "modules": len(architecture_inventory.get("modules", []) or []),
        "layers": len(architecture_inventory.get("layers", []) or []),
        "symbols": len(symbol_index.get("symbols", []) or []),
        "relationships": len(call_graph.get("edges", []) or []),
    }
    return {
        "schema": INDEX_RESULT_SCHEMA,
        "status": status,
        "skipped_reason": skipped_reason,
        "paths": {
            key: path.replace(os.sep, "/")
            for key, path in paths.items()
        },
        "counts": counts,
        "changed_files": changed_files,
        "error": error,
    }


def _emit_index_json(opts: dict, payload: dict) -> None:
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))


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
    skip = {".git", "node_modules", ".simplicio", "dist", "build", "obj", "bin", ".venv", "venv", "__pycache__"}
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
                path = path[path.index("/api/v1"):]
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
    pattern = r"(?:private\s+readonly|readonly|const|let|var)?\s*([A-Za-z_]\w*)\s*=\s*(`[^`]+`|'[^']+'|\"[^\"]+\")"
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
            with open(file, "r", encoding="utf-8", errors="replace") as handle:
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
            "runtime_server_routes": len({(item["method"], item["path"]) for item in server if item["kind"] == "server"}),
            "contract_server_routes": len({(item["method"], item["path"]) for item in server if item["kind"] == "contract"}),
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


def _screen_files(root: str):
    skip = {
        ".git",
        "node_modules",
        ".simplicio",
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
            rel = os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/")
            if name.endswith(".routes.ts") or rel.endswith("app.routes.ts"):
                yield os.path.join(current, name)


def _scan_code(text: str):
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            yield index, char, True
            continue
        if char in ("'", '"', "`"):
            quote = char
            yield index, char, True
            continue
        yield index, char, False


def _balanced_span(text: str, start: int, opener: str, closer: str) -> tuple[int, int] | None:
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ("'", '"', "`"):
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return start, index + 1
    return None


def _top_level_route_objects(array_text: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    object_start: int | None = None
    for index, char, in_string in _scan_code(array_text):
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                object_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and object_start is not None:
                objects.append(array_text[object_start:index + 1])
                object_start = None
    return objects


def _top_level_value(obj_text: str, prop: str) -> str:
    depth_brace = depth_bracket = depth_paren = 0
    for index, char, in_string in _scan_code(obj_text):
        if in_string:
            continue
        if char == "{":
            depth_brace += 1
        elif char == "}":
            depth_brace -= 1
        elif char == "[":
            depth_bracket += 1
        elif char == "]":
            depth_bracket -= 1
        elif char == "(":
            depth_paren += 1
        elif char == ")":
            depth_paren -= 1
        if depth_brace != 1 or depth_bracket or depth_paren:
            continue
        match = re.match(rf"\s*{re.escape(prop)}\s*:\s*", obj_text[index:])
        if not match:
            continue
        value_start = index + match.end()
        while value_start < len(obj_text) and obj_text[value_start].isspace():
            value_start += 1
        if value_start >= len(obj_text):
            return ""
        opener = obj_text[value_start]
        if opener in ("'", '"', "`"):
            escaped = False
            for end in range(value_start + 1, len(obj_text)):
                c = obj_text[end]
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == opener:
                    return obj_text[value_start:end + 1]
            return obj_text[value_start:]
        if opener == "[":
            span = _balanced_span(obj_text, value_start, "[", "]")
            return obj_text[span[0]:span[1]] if span else obj_text[value_start:]
        if opener == "{":
            span = _balanced_span(obj_text, value_start, "{", "}")
            return obj_text[span[0]:span[1]] if span else obj_text[value_start:]
        end = value_start
        while end < len(obj_text) and re.match(r"[A-Za-z0-9_.$]", obj_text[end]):
            end += 1
        return obj_text[value_start:end]
    return ""


def _literal_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in ("'", '"', "`") and value[-1] == value[0]:
        return value[1:-1]
    return value


def _join_screen_path(parent: str, child: str) -> str:
    parent = parent.strip("/")
    child = child.strip("/")
    if not parent and not child:
        return "/"
    if not parent:
        return f"/{child}"
    if not child:
        return f"/{parent}"
    return f"/{parent}/{child}"


def _persona_for_path(path: str) -> str:
    first = path.strip("/").split("/", 1)[0]
    if first in {"admin", "client", "clients", "consultant"}:
        return "client" if first == "clients" else first
    return "public"


def _extract_route_screens_from_array(array_text: str, file: str, root: str, parent_path: str = "") -> list[dict]:
    entries: list[dict] = []
    rel = os.path.relpath(file, root).replace(os.sep, "/")
    for obj_text in _top_level_route_objects(array_text):
        route_path = _join_screen_path(parent_path, _literal_value(_top_level_value(obj_text, "path")))
        component = _literal_value(_top_level_value(obj_text, "component"))
        redirect_to = _literal_value(_top_level_value(obj_text, "redirectTo"))
        data = _top_level_value(obj_text, "data")
        default_user_match = re.search(r"defaultUserType\s*:\s*['\"]([^'\"]+)['\"]", data)
        default_user_type = default_user_match.group(1) if default_user_match else None
        if component or redirect_to:
            entry = {
                "path": route_path,
                "file": rel,
                "kind": "redirect" if redirect_to and not component else "screen",
                "component": component or None,
                "redirect_to": redirect_to or None,
                "persona": default_user_type or _persona_for_path(route_path),
                "guarded": bool(_top_level_value(obj_text, "canActivate")),
                "dynamic": ":" in route_path,
            }
            entries.append(entry)
        children = _top_level_value(obj_text, "children")
        if children.startswith("[") and children.endswith("]"):
            entries.extend(_extract_route_screens_from_array(children[1:-1], file, root, route_path))
    return entries


def _extract_angular_screen_entries(text: str, file: str, root: str) -> list[dict]:
    match = re.search(r"routes\s*:\s*Routes\s*=\s*\[", text)
    if not match:
        match = re.search(r"\bRoutes\s*=\s*\[", text)
    if not match:
        return []
    start = match.end() - 1
    span = _balanced_span(text, start, "[", "]")
    if not span:
        return []
    return _extract_route_screens_from_array(text[span[0] + 1:span[1] - 1], file, root)


def _screen_inventory_for(root: str) -> dict:
    root = os.path.abspath(root)
    entries: list[dict] = []
    for file in _screen_files(root):
        try:
            with open(file, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        entries.extend(_extract_angular_screen_entries(text, file, root))

    entries = sorted(entries, key=lambda item: (item["path"], item["component"] or "", item["kind"]))
    screens = [item for item in entries if item["kind"] == "screen"]
    redirects = [item for item in entries if item["kind"] == "redirect"]
    return {
        "schema": SCREEN_INVENTORY_SCHEMA,
        "root": root.replace(os.sep, "/"),
        "counts": {
            "route_entries": len(entries),
            "screens": len(screens),
            "redirects": len(redirects),
            "guarded": len([item for item in entries if item["guarded"]]),
            "dynamic": len([item for item in entries if item["dynamic"]]),
        },
        "screens": screens,
        "redirects": redirects,
        "route_entries": entries,
    }


def _run_screens(opts: dict) -> int:
    payload = _screen_inventory_for(opts["root"])
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"screens={payload['counts']['screens']} "
            f"redirects={payload['counts']['redirects']} "
            f"guarded={payload['counts']['guarded']} "
            f"dynamic={payload['counts']['dynamic']}"
        )
        for item in payload["route_entries"]:
            if item["kind"] == "redirect":
                print(f"{item['path']} -> {item['redirect_to']}")
            else:
                print(f"{item['path']} {item['component']}")
    return 0


def _run_docs(opts: dict) -> int:
    payload = write_architecture_docs(opts["root"], output_dir=opts["out"])
    if opts["json"]:
        print(json.dumps({
            "schema": "simplicio.architecture-docs/v1",
            "docs_root": payload["docs_root"].replace(os.sep, "/"),
            "paths": [path.replace(os.sep, "/") for path in payload["paths"]],
            "counts": payload["counts"],
        }, sort_keys=True))
    else:
        print(f"docs={payload['counts']['files']} root={payload['docs_root']}")
    return 0


def _run_export_docs(opts: dict) -> int:
    payload = export_architecture_docs(opts["root"], opts["target"], output_dir=opts["out"])
    if opts["json"]:
        print(json.dumps({
            "schema": "simplicio.docs-export/v1",
            "target": payload["target"].replace(os.sep, "/"),
            "paths": [path.replace(os.sep, "/") for path in payload["paths"]],
            "counts": payload["counts"],
        }, sort_keys=True))
    else:
        print(f"exported={payload['counts']['files']} target={payload['target']}")
    return 0


def _run_background(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    abs_out = os.path.abspath(os.path.join(root, out))
    os.makedirs(abs_out, exist_ok=True)
    log_path = os.path.join(abs_out, "background-index.log")
    args = [sys.executable, "-m", "simplicio_mapper.cli", "index", root, "--out", out]
    if opts["stack"]:
        args.extend(["--stack", opts["stack"]])
    if opts["product_name"]:
        args.extend(["--product-name", opts["product_name"]])
    if opts["docs"]:
        args.append("--docs")
    if opts["incremental"]:
        args.append("--update")
    if opts["verbose"]:
        args.append("--verbose")
    env = os.environ.copy()
    source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([source_root, python_path]) if python_path else source_root
    with open(log_path, "ab") as log:
        child = subprocess.Popen(  # noqa: S603 - self-invocation with fixed argv
            args,
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    payload = {
        "schema": "simplicio.background-index/v1",
        "status": "started",
        "pid": child.pid,
        "log": log_path.replace(os.sep, "/"),
    }
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"background index started pid={child.pid} log={log_path}")
    return 0


def _run_index(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    lock = _acquire_index_lock(root, out)
    if lock is None:
        _emit_index_json(opts, _index_result(
            root,
            out,
            status="skipped",
            skipped_reason="locked",
            counts={
                "files": 0,
                "precedents": 0,
                "changed_files": 0,
                "modules": 0,
                "layers": 0,
                "symbols": 0,
                "relationships": 0,
            },
        ))
        if not opts["json"]:
            print(f"index skipped: lock already exists at {_lock_path(root, out)}")
        return 0
    try:
        return _run_index_locked(opts, root, out)
    finally:
        _release_index_lock(lock)


def _run_index_locked(opts: dict, root: str, out: str) -> int:
    paths = _artifact_paths(root, out)
    state = _read_index_state(root, out)
    current_signature = _freshness_signature(root, out)

    if (
        state.get("schema") == INDEX_STATE_SCHEMA
        and state.get("signature") == current_signature
        and _artifacts_exist(paths)
    ):
        payload = _index_result(
            root,
            out,
            status="skipped",
            skipped_reason="already_fresh",
            counts=state.get("counts") if isinstance(state.get("counts"), dict) else None,
        )
        if opts["docs"]:
            docs_payload = write_architecture_docs(root, output_dir=out)
            payload["paths"]["docs_root"] = docs_payload["docs_root"].replace(os.sep, "/")
            payload["counts"]["docs"] = docs_payload["counts"]["files"]
        _emit_index_json(opts, payload)
        return 0

    run_result = _run_once({
        **opts,
        "root": root,
        "incremental": bool(state),
        "silent": not opts["verbose"],
    })
    refreshed_signature = _freshness_signature(root, out)
    payload = _index_result(root, out, status="updated", run_result=run_result)
    if opts["docs"]:
        docs_payload = write_architecture_docs(root, output_dir=out)
        payload["paths"]["docs_root"] = docs_payload["docs_root"].replace(os.sep, "/")
        payload["counts"]["docs"] = docs_payload["counts"]["files"]
    _write_index_state(root, out, refreshed_signature, payload["counts"])
    _emit_index_json(opts, payload)
    return 0


def _watch(opts: dict) -> None:
    root = os.path.abspath(opts["root"])
    print(f"watching {root} for mapper updates...")
    last = _signature(root, opts["out"])
    try:
        while True:
            time.sleep(0.5)
            current = _signature(root, opts["out"])
            if current != last:
                last = current
                try:
                    _run_once({**opts, "incremental": True})
                except Exception as error:  # noqa: BLE001 - watch loop must not crash
                    print(f"map update failed: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        pass


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = _parse_args(argv)
    if opts["background"] and opts["command"] in ("index", "map", "update"):
        return _run_background(opts)
    if opts["docs_only"] and opts["command"] in ("index", "map", "update"):
        return _run_docs(opts)
    if opts["command"] == "endpoints":
        return _run_endpoints(opts)
    if opts["command"] == "screens":
        return _run_screens(opts)
    if opts["command"] == "docs":
        return _run_docs(opts)
    if opts["command"] == "export-docs":
        return _run_export_docs(opts)
    if opts["command"] == "index":
        try:
            return _run_index(opts)
        except Exception as error:  # noqa: BLE001 - CLI boundary must report a stable failure
            payload = _index_result(
                os.path.abspath(opts["root"]),
                opts["out"],
                status="failed",
                error=str(error),
            )
            if opts["json"]:
                _emit_index_json(opts, payload)
            else:
                print(f"index failed: {error}", file=sys.stderr)
            return 1
    _run_once(opts)
    if opts["docs"]:
        write_architecture_docs(opts["root"], output_dir=opts["out"])
    if opts["watch"]:
        _watch(opts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
