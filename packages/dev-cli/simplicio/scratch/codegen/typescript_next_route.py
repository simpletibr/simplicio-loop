"""Deterministic Next.js route handler generation for scratch tasks.

Pure Python: the handler bodies are small, fixed shapes (a JSON list/echo
per HTTP method) generated from string templates and merged into the target
file by text, not by parsing/mutating a TypeScript AST. There is no Node.js
or npm dependency anywhere in this module or its runtime path — this
package is Python-only end to end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor

_SUPPORTED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_NO_BODY_METHODS = frozenset({"GET", "DELETE"})


@dataclass(frozen=True)
class _NextRouteSpec:
    resource: str
    variable_name: str
    methods: tuple[str, ...]


class TypeScriptAddNextRouteExecutor(TaskExecutor):
    """Create small JSON route handlers for Next.js app-router API routes."""

    name = "typescript-add-next-route"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_next_stack(stack):
            return False
        if _route_parts(task.target) is None:
            return False
        text = _task_text(task).lower()
        return any(token in text for token in ("api", "crud", "endpoint", "json", "route", "handler"))

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        spec = _parse_route_spec(task)
        if spec is None:
            return _fallback("unsupported Next.js route task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")

        original = target.read_text(encoding="utf-8") if target.exists() else ""
        missing = [method for method in spec.methods if not _has_exported_method(original, method)]
        if target.exists() and not missing:
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{task.target} already has {', '.join(spec.methods)} handlers",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        methods = list(missing or list(spec.methods))
        target.write_text(_render_route_file(original, spec, methods), encoding="utf-8")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"generated Next.js route handlers {', '.join(methods)} for {spec.resource}",
        )


def _is_next_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language} {stack.framework}".lower()
    return "next" in text or stack.slug == "ts-nextjs"


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_route_spec(task: Task) -> _NextRouteSpec | None:
    parts = _route_parts(task.target)
    if parts is None:
        return None

    resource = _resource_from_parts(parts)
    if not resource:
        return None

    methods = _parse_methods(_task_text(task))
    return _NextRouteSpec(
        resource=resource,
        variable_name=_identifier(resource),
        methods=methods,
    )


def _route_parts(target: str) -> list[str] | None:
    normalized = target.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 5:
        return None
    if parts[:3] != ["src", "app", "api"] or parts[-1] != "route.ts":
        return None
    return parts[3:-1]


def _resource_from_parts(parts: list[str]) -> str:
    for part in reversed(parts):
        if part.startswith("[") and part.endswith("]"):
            continue
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "", part)
        if cleaned:
            return cleaned
    return ""


def _parse_methods(text: str) -> tuple[str, ...]:
    upper = text.upper()
    methods = [method for method in _SUPPORTED_METHODS if re.search(rf"\b{method}\b", upper)]
    if "CRUD" in upper:
        for method in ("GET", "POST"):
            if method not in methods:
                methods.append(method)
    if not methods:
        methods = ["GET", "POST"]
    return tuple(methods)


def _identifier(value: str) -> str:
    identifier = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not identifier:
        return "items"
    if identifier[0].isdigit():
        return f"items_{identifier}"
    return identifier


def _has_exported_method(text: str, method: str) -> bool:
    return (
        re.search(
            rf"\bexport\s+(?:async\s+)?function\s+{re.escape(method)}\b",
            text,
        )
        is not None
    )


def _success_status(method: str) -> int:
    return 201 if method == "POST" else 200


def _render_function(method: str, variable_name: str) -> str:
    """One exported async route handler, matching the fixed shapes the
    former ts-morph script produced: GET returns an empty list, DELETE
    acknowledges deletion, and every other verb echoes the parsed JSON
    request body with a method-appropriate status code."""
    if method == "GET":
        params = ""
        body = (
            f"  const {variable_name}: Array<Record<string, unknown>> = [];\n"
            f"  return Response.json({variable_name});\n"
        )
    elif method == "DELETE":
        params = ""
        body = "  return Response.json({ deleted: true });\n"
    else:
        params = "request: Request"
        body = (
            "  const body = (await request.json()) as Record<string, unknown>;\n"
            f"  return Response.json(body, {{ status: {_success_status(method)} }});\n"
        )
    return f"export async function {method}({params}): Promise<Response> {{\n{body}}}\n"


def _render_route_file(original: str, spec: _NextRouteSpec, methods: list[str]) -> str:
    blocks = "\n".join(_render_function(method, spec.variable_name) for method in methods)
    if not original:
        return blocks
    prefix = original if original.endswith("\n") else original + "\n"
    return f"{prefix}\n{blocks}"


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
