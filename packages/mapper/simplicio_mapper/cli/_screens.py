from __future__ import annotations

import json
import os
import re

from ._shared import SCREEN_INVENTORY_SCHEMA


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
                objects.append(array_text[object_start : index + 1])
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
                    return obj_text[value_start : end + 1]
            return obj_text[value_start:]
        if opener == "[":
            span = _balanced_span(obj_text, value_start, "[", "]")
            return obj_text[span[0] : span[1]] if span else obj_text[value_start:]
        if opener == "{":
            span = _balanced_span(obj_text, value_start, "{", "}")
            return obj_text[span[0] : span[1]] if span else obj_text[value_start:]
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


def _extract_route_screens_from_array(
    array_text: str, file: str, root: str, parent_path: str = ""
) -> list[dict]:
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
    return _extract_route_screens_from_array(text[span[0] + 1 : span[1] - 1], file, root)


def _screen_inventory_for(root: str) -> dict:
    root = os.path.abspath(root)
    entries: list[dict] = []
    for file in _screen_files(root):
        try:
            with open(file, encoding="utf-8", errors="replace") as handle:
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
