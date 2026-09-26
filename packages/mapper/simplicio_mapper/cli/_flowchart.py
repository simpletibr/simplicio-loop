from __future__ import annotations

import json
import os
import re

from ._endpoints import (
    _endpoint_files,
    _endpoint_inventory_for,
    _extract_text_client_calls,
    _is_test_path,
    _normalize_endpoint_path,
)
from ._screens import _balanced_span, _screen_inventory_for
from ._shared import SERVICE_FLOWCHART_SCHEMA

_CLICK_ATTR_RE = re.compile(r"\(click\)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")

_VALIDATOR_RE = re.compile(r"Validators\.(\w+)")

_DB_MARKER_RE = re.compile(
    r"DbContext|SaveChanges(?:Async)?|ExecuteSqlRaw|FromSqlRaw|SqlConnection|"
    r"TableClient|CosmosClient|BlobClient|QueueClient|\.commit\(\)|"
    r"session\.(?:add|commit|execute|query|delete)|db\.(?:add|commit|execute|query|session)|"
    r"\.execute\(|prisma\.|sequelize\.|Repository|repository\.|_repo\.",
    re.IGNORECASE,
)

_PY_REQUEST_FRAMEWORK = {"request", "backgroundtasks", "response", "depends"}

_CS_CALL_OWNER_SKIP = {"req", "request", "log", "logger", "_logger", "console", "httpcontext"}

_PY_CALL_OWNER_SKIP = {"self", "request", "logger", "log"}


def _posix_dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _flow_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return slug or "x"


def _mermaid_escape(text: str) -> str:
    return (text or "").replace('"', "'").replace("\n", " ").strip()


def _scan_ts_classes(root: str) -> dict[str, dict]:
    """Map each TypeScript class name to its file path and source text."""
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
    info: dict[str, dict] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.endswith((".ts", ".tsx")):
                continue
            path = os.path.join(current, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            for match in re.finditer(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_]\w*)", text):
                cls = match.group(1)
                if cls not in info:
                    info[cls] = {"rel": rel, "abs": os.path.abspath(path), "text": text}
    return info


def _component_template(info: dict | None) -> str:
    """Return the Angular component template (inline ``template`` or ``templateUrl``)."""
    if not info:
        return ""
    text = info["text"]
    inline = re.search(r"template\s*:\s*`", text)
    if inline:
        start = inline.end()
        index = start
        while index < len(text):
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "`":
                return text[start:index]
            index += 1
        return text[start:]
    url = re.search(r"templateUrl\s*:\s*['\"]([^'\"]+)['\"]", text)
    if url:
        html_path = os.path.normpath(os.path.join(os.path.dirname(info["abs"]), url.group(1)))
        try:
            with open(html_path, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return ""
    return ""


def _button_label(template: str, click_pos: int) -> str:
    tag_open = template.rfind("<", 0, click_pos)
    tag_close = template.find(">", click_pos)
    if tag_open == -1 or tag_close == -1:
        return ""
    tag = template[tag_open : tag_close + 1]
    text_end = template.find("<", tag_close + 1)
    text = template[tag_close + 1 : text_end] if text_end != -1 else ""
    text = re.sub(r"\{\{.*?\}\}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        return text
    for attr in ("aria-label", "title"):
        found = re.search(rf'{attr}\s*=\s*"([^"]*)"', tag)
        if found:
            return found.group(1).strip()
    return ""


def _handler_body(text: str, handler: str) -> str:
    match = re.search(rf"\b{re.escape(handler)}\s*\([^)]*\)\s*(?::\s*[^={{]+)?\{{", text)
    if not match:
        return ""
    brace = text.find("{", match.end() - 1)
    if brace == -1:
        return ""
    span = _balanced_span(text, brace, "{", "}")
    return text[span[0] : span[1]] if span else ""


def _calls_in_text(text: str) -> list[dict]:
    calls = _extract_text_client_calls(text, "handler", ".")
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for call in calls:
        key = (call["method"], call["path"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"method": call["method"], "path": call["path"]})
    return out


def _extract_buttons(template: str, comp_file: str, comp_text: str) -> list[dict]:
    buttons: list[dict] = []
    if not template:
        return buttons
    seen: set[tuple[str, str]] = set()
    for match in _CLICK_ATTR_RE.finditer(template):
        expr = (match.group(1) or match.group(2) or "").strip()
        handler_match = re.match(r"([A-Za-z_]\w*)", expr)
        handler = handler_match.group(1) if handler_match else expr
        label = _button_label(template, match.start()) or handler or "(action)"
        key = (handler, label)
        if key in seen:
            continue
        seen.add(key)
        services = _calls_in_text(_handler_body(comp_text, handler)) if handler else []
        buttons.append(
            {
                "label": label,
                "handler": handler,
                "file": comp_file,
                "line": template.count("\n", 0, match.start()) + 1,
                "services": services,
            }
        )
    return buttons


def _within_scope(file: str, scope: str) -> bool:
    if not scope:
        return False
    return file == scope or file.startswith(scope + "/")


def _build_frontend_face(root: str, class_info: dict[str, dict]) -> dict:
    screen_inv = _screen_inventory_for(root)
    endpoint_inv = _endpoint_inventory_for(root)
    screens: list[dict] = []
    scopes: list[str] = []
    for item in screen_inv["screens"]:
        component = item.get("component")
        info = class_info.get(component) if component else None
        comp_file = info["rel"] if info else item["file"]
        scope = _posix_dirname(comp_file)
        rules: list[dict] = []
        if item.get("guarded"):
            rules.append({"kind": "guard", "detail": "route requires a canActivate guard"})
        persona = item.get("persona") or "public"
        if persona != "public":
            rules.append({"kind": "persona", "detail": f"restricted to persona '{persona}'"})
        if item.get("dynamic"):
            rules.append({"kind": "dynamic-route", "detail": "route carries a dynamic path parameter"})
        if info:
            for validator in sorted(set(_VALIDATOR_RE.findall(info["text"]))):
                rules.append({"kind": "validator", "detail": f"form validator Validators.{validator}"})
        buttons = _extract_buttons(_component_template(info), comp_file, info["text"]) if info else []
        screens.append(
            {
                "path": item["path"],
                "component": component,
                "persona": persona,
                "guarded": bool(item.get("guarded")),
                "dynamic": bool(item.get("dynamic")),
                "file": comp_file,
                "scope": scope,
                "services": [],
                "buttons": buttons,
                "rules": rules,
            }
        )
        scopes.append(scope)

    unlinked: list[dict] = []
    seen_unlinked: set[tuple[str, str]] = set()
    seen_screen: list[set[tuple[str, str]]] = [set() for _ in screens]
    for call in endpoint_inv["client_calls"]:
        best = -1
        best_len = -1
        for index, scope in enumerate(scopes):
            if _within_scope(call["file"], scope) and len(scope) > best_len:
                best = index
                best_len = len(scope)
        entry = {"method": call["method"], "path": call["path"], "file": call["file"]}
        key = (entry["method"], entry["path"])
        if best == -1:
            if key not in seen_unlinked:
                seen_unlinked.add(key)
                unlinked.append(entry)
        elif key not in seen_screen[best]:
            seen_screen[best].add(key)
            screens[best]["services"].append(entry)

    for screen in screens:
        screen["services"].sort(key=lambda e: (e["path"], e["method"]))
    unlinked.sort(key=lambda e: (e["path"], e["method"]))
    return {"screens": screens, "unlinked_services": unlinked}


def _external_calls(body: str, language: str) -> list[str]:
    skip = _CS_CALL_OWNER_SKIP if language == "csharp" else _PY_CALL_OWNER_SKIP
    calls: set[str] = set()
    for match in re.finditer(r"(?:await\s+)?([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(", body):
        owner, method = match.group(1), match.group(2)
        if owner.lower() in skip:
            continue
        calls.add(f"{owner}.{method}")
    return sorted(calls)


def _db_markers(body: str) -> list[str]:
    return sorted({match.group(0) for match in _DB_MARKER_RE.finditer(body)})[:6]


def _flow_steps(
    method: str, path: str, auth: str, request: list[str], external: list[str], db: bool, response: list[str]
) -> list[str]:
    steps = [f"Receive {method} {path}"]
    if auth:
        steps.append(f"Authorize ({auth})")
    if request:
        steps.append("Validate payload: " + ", ".join(request))
    for call in external[:6]:
        steps.append(f"Call {call}")
    if db:
        steps.append("Read/write database and treat data")
    steps.append("Return " + (", ".join(response) if response else "result"))
    return steps


def _guess_layer(rel: str) -> str:
    low = rel.lower()
    if "controller" in low:
        return "controller"
    if "function" in low:
        return "function"
    if "service" in low:
        return "service"
    if "repository" in low or "/repo" in low or low.endswith("repo.py"):
        return "repository"
    if "router" in low or "route" in low or "/api" in low:
        return "route"
    return "handler"


_CS_REQUEST_FRAMEWORK = {
    "HttpRequest",
    "HttpRequestData",
    "HttpRequestMessage",
    "HttpResponseData",
    "FunctionContext",
    "CancellationToken",
    "ILogger",
}


def _csharp_request_payload(params_text: str) -> list[str]:
    types = set(re.findall(r"\[FromBody\]\s*([A-Za-z_][\w<>\[\]]*)", params_text))
    types.update(re.findall(r"\b([A-Z][A-Za-z0-9_]*(?:Dto|Request|Model|Command|Input))\b", params_text))
    return sorted(t for t in types if t not in _CS_REQUEST_FRAMEWORK)


def _csharp_response_payload(body: str) -> list[str]:
    types = set(re.findall(r"new\s+([A-Z]\w*(?:Dto|Response|Result|Model|ViewModel))\s*[\({]", body))
    types.update(re.findall(r"Ok\w*\(\s*new\s+([A-Z]\w*)", body))
    return sorted(types)


def _csharp_endpoint_flows(text: str) -> list[dict]:
    flows: list[dict] = []
    for match in re.finditer(r"([A-Za-z_]\w*)\s*\(\s*\[HttpTrigger\((.*?)\)\]", text, re.S):
        args = match.group(2)
        route = re.search(r'Route\s*=\s*"([^"]+)"', args)
        if not route:
            continue
        methods = [m.lower() for m in re.findall(r'"(get|post|put|patch|delete)"', args, re.I)] or ["get"]
        auth = ""
        auth_match = re.search(r"AuthorizationLevel\.(\w+)", args)
        if auth_match:
            auth = auth_match.group(1)
        paren = text.index("(", match.start())
        pspan = _balanced_span(text, paren, "(", ")")
        if not pspan:
            continue
        params_text = text[pspan[0] + 1 : pspan[1] - 1]
        brace = text.find("{", pspan[1])
        bspan = _balanced_span(text, brace, "{", "}") if brace != -1 else None
        body = text[bspan[0] : bspan[1]] if bspan else ""
        request = _csharp_request_payload(params_text)
        response = _csharp_response_payload(body)
        external = _external_calls(body, "csharp")
        db = bool(_DB_MARKER_RE.search(body))
        path = _normalize_endpoint_path(route.group(1))
        for method in dict.fromkeys(methods):
            mu = method.upper()
            flows.append(
                {
                    "method": mu,
                    "path": path,
                    "auth": auth,
                    "request": request,
                    "response": response,
                    "external_calls": external,
                    "external_count": len(external),
                    "db_access": db,
                    "db_markers": _db_markers(body),
                    "steps": _flow_steps(mu, path, auth, request, external, db, response),
                }
            )
    return flows


def _python_def_body(text: str, start: int) -> str:
    lines = text[start:].splitlines()
    body: list[str] = []
    indent: int | None = None
    for line in lines:
        if not line.strip():
            body.append(line)
            continue
        current = len(line) - len(line.lstrip())
        if indent is None:
            if current == 0:
                break
            indent = current
        elif current < indent:
            break
        body.append(line)
    return "\n".join(body)


def _python_request_payload(params: str) -> list[str]:
    types: list[str] = []
    for param in params.split(","):
        param = param.strip()
        if not param or param == "self" or param.startswith("*"):
            continue
        if ":" in param:
            type_name = param.split(":", 1)[1].split("=")[0].strip()
            if type_name and type_name.lower() not in _PY_REQUEST_FRAMEWORK:
                types.append(type_name)
    seen: set[str] = set()
    out: list[str] = []
    for type_name in types:
        if type_name not in seen:
            seen.add(type_name)
            out.append(type_name)
    return out


def _python_endpoint_flows(text: str) -> list[dict]:
    flows: list[dict] = []
    prefix = ""
    prefix_match = re.search(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]", text, re.S)
    if prefix_match:
        prefix = prefix_match.group(1)
    pattern = (
        r"@\w+\.(get|post|put|patch|delete)\(\s*['\"]([^'\"]+)['\"][^)]*\)\s*\n"
        r"\s*(?:async\s+)?def\s+\w+\s*\(([^)]*)\)\s*(?:->\s*([^\:]+?))?\s*:"
    )
    for match in re.finditer(pattern, text, re.S):
        method, raw_path, params, ret = match.groups()
        body = _python_def_body(text, match.end())
        request = _python_request_payload(params)
        response = [ret.strip()] if ret and ret.strip() else []
        external = _external_calls(body, "python")
        db = bool(_DB_MARKER_RE.search(body))
        auth = "Depends" if "Depends(" in params else ""
        path = _normalize_endpoint_path(f"/api/v1{prefix}{raw_path}")
        mu = method.upper()
        flows.append(
            {
                "method": mu,
                "path": path,
                "auth": auth,
                "request": request,
                "response": response,
                "external_calls": external,
                "external_count": len(external),
                "db_access": db,
                "db_markers": _db_markers(body),
                "steps": _flow_steps(mu, path, auth, request, external, db, response),
            }
        )
    return flows


def _build_backend_face(root: str) -> list[dict]:
    flows: list[dict] = []
    for file in _endpoint_files(root):
        try:
            with open(file, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        if _is_test_path(file, root):
            continue
        ext = os.path.splitext(file)[1].lower()
        rel = os.path.relpath(file, root).replace(os.sep, "/")
        if ext == ".cs":
            raw = _csharp_endpoint_flows(text)
        elif ext == ".py":
            raw = _python_endpoint_flows(text)
        else:
            continue
        for flow in raw:
            flow["file"] = rel
            flow["layer"] = _guess_layer(rel)
            flows.append(flow)
    flows.sort(key=lambda f: (f["path"], f["method"]))
    return flows


def build_service_flowchart(root: str) -> dict:
    """Build the deterministic frontend/backend service flowchart model."""
    root = os.path.abspath(root)
    class_info = _scan_ts_classes(root)
    frontend = _build_frontend_face(root, class_info)
    backend = _build_backend_face(root)
    screens = frontend["screens"]
    return {
        "schema": SERVICE_FLOWCHART_SCHEMA,
        "root": root.replace(os.sep, "/"),
        "counts": {
            "screens": len(screens),
            "linked_services": sum(len(s["services"]) for s in screens),
            "unlinked_services": len(frontend["unlinked_services"]),
            "buttons": sum(len(s["buttons"]) for s in screens),
            "rules": sum(len(s["rules"]) for s in screens),
            "backend_flows": len(backend),
            "db_flows": sum(1 for f in backend if f["db_access"]),
        },
        "screens": screens,
        "unlinked_services": frontend["unlinked_services"],
        "backend": backend,
    }


_FLOW_DIAGRAM_LIMIT = 40


def render_service_flowchart_markdown(model: dict) -> str:
    screens = model["screens"]
    backend = model["backend"]
    counts = model["counts"]
    lines = [
        "# Service Flowchart",
        "",
        "Auto-generated from the `.simplicio-loop` extractors. Maps frontend screens to the",
        "services/endpoints they reach, the buttons that trigger them, and the backend",
        "process behind each endpoint (layer, payloads, external calls, database access).",
        "",
        "> Rules listed here are **observable** (route guards, persona gating, dynamic",
        "> parameters, form validators, auth levels). Semantic business rules are not",
        "> inferred. Payload, external-call and database signals are heuristic — verify",
        "> against the referenced source before treating them as a contract.",
        "",
        "## Coverage",
        "",
        f"- Screens: {counts['screens']}",
        f"- Linked services: {counts['linked_services']}",
        f"- Unlinked services: {counts['unlinked_services']}",
        f"- Buttons: {counts['buttons']}",
        f"- Observable rules: {counts['rules']}",
        f"- Backend flows: {counts['backend_flows']}",
        f"- Flows touching the database: {counts['db_flows']}",
        "",
    ]

    if screens or model["unlinked_services"]:
        lines += ["## Frontend Diagram", "", "```mermaid", "flowchart TD"]
        endpoint_ids: dict[tuple[str, str], str] = {}
        endpoint_defs: list[str] = []

        def endpoint_node(method: str, path: str) -> str:
            key = (method, path)
            if key not in endpoint_ids:
                node_id = f"EP{len(endpoint_ids)}"
                endpoint_ids[key] = node_id
                endpoint_defs.append(f'  {node_id}["{_mermaid_escape(method + " " + path)}"]')
            return endpoint_ids[key]

        by_persona: dict[str, list[tuple[int, dict]]] = {}
        for index, screen in enumerate(screens):
            by_persona.setdefault(screen["persona"], []).append((index, screen))
        for persona, items in by_persona.items():
            lines.append(f'  subgraph P_{_flow_slug(persona)}["Persona: {persona}"]')
            for index, screen in items:
                guard = " [guard]" if screen["guarded"] else ""
                label = _mermaid_escape(f"{screen['path']}<br/>{screen['component'] or '?'}{guard}")
                lines.append(f'    SCR{index}["{label}"]')
            lines.append("  end")

        edges: list[str] = []
        for index, screen in enumerate(screens):
            for service in screen["services"]:
                node = endpoint_node(service["method"], service["path"])
                edges.append(f"  SCR{index} -->|{service['method']}| {node}")
            for order, button in enumerate(screen["buttons"]):
                button_id = f"BTN{index}_{order}"
                edges.append(f'  {button_id}(["{_mermaid_escape(button["label"])}"])')
                edges.append(f"  SCR{index} -.->|click| {button_id}")
                for service in button["services"]:
                    node = endpoint_node(service["method"], service["path"])
                    edges.append(f"  {button_id} ==>|{service['method']}| {node}")
        lines.extend(endpoint_defs)
        lines.extend(edges)
        lines.append("```")
        lines.append("")

        lines += ["## Screens", ""]
        for screen in screens:
            heading = f"{screen['path']} — {screen['component'] or '?'}"
            lines += [
                f"### {heading}",
                "",
                f"- Persona: {screen['persona']}",
                f"- Guarded: {'yes' if screen['guarded'] else 'no'}",
                f"- Dynamic: {'yes' if screen['dynamic'] else 'no'}",
                f"- File: `{screen['file']}`",
                "",
            ]
            if screen["services"]:
                lines += ["**Services**", "", "| Method | Path | Source |", "| --- | --- | --- |"]
                for service in screen["services"]:
                    lines.append(f"| {service['method']} | `{service['path']}` | `{service['file']}` |")
                lines.append("")
            if screen["buttons"]:
                lines += ["**Buttons**", "", "| Label | Handler | Triggers |", "| --- | --- | --- |"]
                for button in screen["buttons"]:
                    triggers = ", ".join(f"{s['method']} {s['path']}" for s in button["services"]) or "—"
                    lines.append(f"| {button['label']} | `{button['handler']}` | {triggers} |")
                lines.append("")
            if screen["rules"]:
                lines += ["**Observable rules**", ""]
                for rule in screen["rules"]:
                    lines.append(f"- `{rule['kind']}`: {rule['detail']}")
                lines.append("")

        if model["unlinked_services"]:
            lines += [
                "## Unlinked services",
                "",
                "Client calls that could not be attributed to a screen scope.",
                "",
                "| Method | Path | Source |",
                "| --- | --- | --- |",
            ]
            for service in model["unlinked_services"]:
                lines.append(f"| {service['method']} | `{service['path']}` | `{service['file']}` |")
            lines.append("")

    if backend:
        lines += ["## Backend Flows", ""]
        shown = backend[:_FLOW_DIAGRAM_LIMIT]
        if len(backend) > _FLOW_DIAGRAM_LIMIT:
            lines.append(
                f"> Showing {_FLOW_DIAGRAM_LIMIT} of {len(backend)} backend flows in diagrams; "
                "all flows are listed in the table below."
            )
            lines.append("")
        for index, flow in enumerate(shown):
            lines += [f"### {flow['method']} {flow['path']}", "", "```mermaid", "flowchart LR"]
            previous = None
            for step_order, step in enumerate(flow["steps"]):
                node_id = f"F{index}_{step_order}"
                if step.startswith("Read/write database"):
                    lines.append(f'  {node_id}[("{_mermaid_escape(step)}")]')
                else:
                    lines.append(f'  {node_id}["{_mermaid_escape(step)}"]')
                if previous is not None:
                    lines.append(f"  {previous} --> {node_id}")
                previous = node_id
            lines.append("```")
            lines += [
                "",
                f"- Layer: `{flow['layer']}`",
                f"- File: `{flow['file']}`",
                f"- Auth: {flow['auth'] or 'none detected'}",
                f"- Request payload: {', '.join(flow['request']) or 'none detected'}",
                f"- Response payload: {', '.join(flow['response']) or 'none detected'}",
                f"- External functions hit: {flow['external_count']}"
                + (f" ({', '.join(flow['external_calls'][:6])})" if flow["external_calls"] else ""),
                f"- Database access: {'yes' if flow['db_access'] else 'no'}"
                + (f" ({', '.join(flow['db_markers'])})" if flow["db_markers"] else ""),
                "",
            ]
        lines += [
            "## Backend Flow Summary",
            "",
            "| Method | Path | Layer | Ext. calls | DB | Request | Response |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for flow in backend:
            lines.append(
                f"| {flow['method']} | `{flow['path']}` | {flow['layer']} | "
                f"{flow['external_count']} | {'yes' if flow['db_access'] else 'no'} | "
                f"{', '.join(flow['request']) or '—'} | {', '.join(flow['response']) or '—'} |"
            )
        lines.append("")

    if not screens and not model["unlinked_services"] and not backend:
        lines += ["No frontend screens, client calls or backend routes were detected.", ""]

    return "\n".join(lines)


def _run_flowchart(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    model = build_service_flowchart(root)
    markdown = render_service_flowchart_markdown(model)
    abs_out = os.path.abspath(os.path.join(root, opts["out"]))
    doc_path = os.path.join(abs_out, "docs", "flowchart.md")
    os.makedirs(os.path.dirname(doc_path), exist_ok=True)
    tmp = f"{doc_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(markdown.rstrip() + "\n")
    os.replace(tmp, doc_path)
    payload = {
        "schema": SERVICE_FLOWCHART_SCHEMA,
        "root": model["root"],
        "doc": doc_path.replace(os.sep, "/"),
        "counts": model["counts"],
        "screens": model["screens"],
        "unlinked_services": model["unlinked_services"],
        "backend": model["backend"],
    }
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        counts = model["counts"]
        print(
            f"screens={counts['screens']} linked_services={counts['linked_services']} "
            f"buttons={counts['buttons']} rules={counts['rules']} "
            f"backend_flows={counts['backend_flows']} db_flows={counts['db_flows']} "
            f"doc={doc_path}"
        )
    return 0
