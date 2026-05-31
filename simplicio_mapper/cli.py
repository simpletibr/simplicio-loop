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
from .mapper import write_mapping_artifacts

INDEX_RESULT_SCHEMA = "simplicio.mapper-index/v1"
INDEX_STATE_SCHEMA = "simplicio.mapper-index-state/v1"
ENDPOINT_INVENTORY_SCHEMA = "simplicio.endpoint-inventory/v1"

HELP_TEXT = """simplicio-mapper map

Generate or update machine-readable mapper artifacts.

USAGE
  simplicio-mapper index <path> [--json] [--verbose]
  simplicio-mapper endpoints <path> [--against <server-root>] [--json]
  simplicio-mapper map [--root <dir>] [--incremental] [--watch]
  simplicio-mapper update [--root <dir>] [--watch]

OPTIONS
  index <path>          Idempotently create or refresh .simplicio artifacts.
  endpoints <path>      Extract client/server HTTP endpoint inventory.
  --against <dir>       Compare endpoint client calls against server routes.
  --json                Emit structured index output.
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
        "command": "map",
        "against": "",
    }
    command = argv[0] if argv and argv[0] in ("index", "map", "update", "endpoints") else "map"
    opts["command"] = command
    if command == "index":
        opts["silent"] = True
    if command == "update":
        opts["incremental"] = True
    i = 1 if argv and argv[0] in ("index", "map", "update", "endpoints") else 0
    while i < len(argv):
        arg = argv[i]
        if command in ("index", "endpoints") and not arg.startswith("-"):
            opts["root"] = arg
        elif arg == "--against":
            i += 1
            opts["against"] = argv[i]
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
        elif arg == "--watch":
            opts["watch"] = True
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
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules") and os.path.abspath(os.path.join(current, d)) != abs_out]
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


def _artifact_paths(root: str, out: str) -> dict[str, str]:
    abs_out = os.path.abspath(os.path.join(root, out))
    return {
        "project_map": os.path.join(abs_out, "project-map.json"),
        "precedent_index": os.path.join(abs_out, "precedent-index.json"),
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
    return {
        "kind": "git",
        "head": head.stdout.strip(),
        "status_hash": _hash_text(status.stdout),
    }


def _tree_signature(root: str, out: str) -> dict:
    digest = hashlib.sha256()
    abs_out = os.path.abspath(os.path.join(root, out))
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in (".git", "node_modules")
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
    changed_files = list(project_map.get("changed_files") or [])
    counts = counts or {
        "files": len(project_map.get("files", []) or []),
        "precedents": len(precedent_index.get("items", []) or []),
        "changed_files": len(changed_files),
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


def _normalize_endpoint_path(path: str) -> str:
    path = path.strip().split("?", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    path = path.replace("//", "/")
    path = re.sub(r"\$\{[^}]+\}", "{id}", path)
    path = re.sub(r"\{[^}]+\}", "{id}", path)
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
    for owner in ("self", "self._client"):
        for method in ("get", "post", "put", "patch", "delete"):
            pattern = rf"{re.escape(owner)}\.{method}\(\s*f?['\"]([^'\"]+)['\"]"
            for match in re.finditer(pattern, text):
                path = match.group(1)
                if path.startswith("/"):
                    client.append(_route_entry(method, f"/api/v1{path}", file, root, "client"))
    return server, client


def _extract_text_client_calls(text: str, file: str, root: str) -> list[dict]:
    calls: list[dict] = []
    for method in ("get", "post", "put", "patch", "delete"):
        pattern = rf"\.{method}(?:<[^>]+>)?\(\s*(?:`([^`]+)`|['\"]([^'\"]+)['\"])"
        for match in re.finditer(pattern, text, re.I):
            path = match.group(1) or match.group(2) or ""
            if "/api/v1" in path:
                path = path[path.index("/api/v1"):]
                calls.append(_route_entry(method, path, file, root, "client"))
    return calls


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
        if ext == ".cs":
            server.extend(_extract_csharp_server_routes(text, file, root))
        elif ext == ".py":
            py_server, py_client = _extract_python_routes(text, file, root)
            server.extend(py_server)
            client.extend(py_client)
        if ext in (".ts", ".tsx", ".js", ".jsx"):
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
    missing = [
        {"method": method, "path": path}
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


def _run_index(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    paths = _artifact_paths(root, out)
    state = _read_index_state(root, out)
    current_signature = _freshness_signature(root, out)

    if (
        state.get("schema") == INDEX_STATE_SCHEMA
        and state.get("signature") == current_signature
        and _artifacts_exist(paths)
    ):
        _emit_index_json(opts, _index_result(
            root,
            out,
            status="skipped",
            skipped_reason="already_fresh",
            counts=state.get("counts") if isinstance(state.get("counts"), dict) else None,
        ))
        return 0

    run_result = _run_once({
        **opts,
        "root": root,
        "incremental": bool(state),
        "silent": not opts["verbose"],
    })
    refreshed_signature = _freshness_signature(root, out)
    payload = _index_result(root, out, status="updated", run_result=run_result)
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
    if opts["command"] == "endpoints":
        return _run_endpoints(opts)
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
    if opts["watch"]:
        _watch(opts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
