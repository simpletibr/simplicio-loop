"""Deterministic Next.js route handler generation for scratch tasks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor

_SUPPORTED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


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
        ok, log = _write_with_ts_morph(project_dir, target, spec, methods)
        if not ok:
            return _fallback(log)
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=(
                "generated Next.js route handlers with ts-morph "
                f"{', '.join(missing or list(spec.methods))} for {spec.resource}"
            ),
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


def _write_with_ts_morph(
    project_dir: Path,
    target: Path,
    spec: _NextRouteSpec,
    methods: list[str],
) -> tuple[bool, str]:
    payload = {
        "routePath": str(target),
        "methods": methods,
        "resource": spec.resource,
        "variableName": spec.variable_name,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".cjs", delete=False) as handle:
        handle.write(_TS_MORPH_SCRIPT)
        script = Path(handle.name)
    node = shutil.which("node") or shutil.which("node.exe")
    if node is None:
        try:
            script.unlink()
        except OSError:
            pass
        return False, "ts-morph execution failed: node was not found"
    ok, env_or_log = _ts_morph_env(project_dir)
    if not ok:
        try:
            script.unlink()
        except OSError:
            pass
        return False, env_or_log
    try:
        proc = subprocess.run(
            [
                node,
                str(script),
                json.dumps(payload),
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            env=env_or_log,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"ts-morph execution failed: {exc}"
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        log = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return False, f"ts-morph execution failed: {log[-1000:]}"
    return True, (proc.stdout or "").strip()


def _ts_morph_env(project_dir: Path) -> tuple[bool, dict[str, str] | str]:
    env = os.environ.copy()
    node_modules = _find_node_modules_with_ts_morph(project_dir)
    if node_modules is None:
        ok, node_modules_or_log = _ensure_ts_morph_cache()
        if not ok:
            return False, node_modules_or_log
        node_modules = node_modules_or_log
    existing = env.get("NODE_PATH")
    env["NODE_PATH"] = str(node_modules) if not existing else os.pathsep.join([str(node_modules), existing])
    return True, env


def _find_node_modules_with_ts_morph(project_dir: Path) -> Path | None:
    candidates = [
        project_dir / "node_modules",
        Path.cwd() / "node_modules",
    ]
    for node_modules in candidates:
        if (node_modules / "ts-morph" / "package.json").is_file():
            return node_modules
    return None


def _ensure_ts_morph_cache() -> tuple[bool, Path | str]:
    cache = Path(
        os.environ.get(
            "SIMPLICIO_TS_MORPH_CACHE",
            str(Path(tempfile.gettempdir()) / "simplicio-ts-morph-node"),
        )
    )
    node_modules = cache / "node_modules"
    if (node_modules / "ts-morph" / "package.json").is_file():
        return True, node_modules
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        return False, "ts-morph execution failed: npm was not found"
    cache.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            npm,
            "install",
            "--prefix",
            str(cache),
            "--no-save",
            "--silent",
            "ts-morph@^28.0.0",
            "typescript@^5",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        log = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return False, f"ts-morph dependency install failed: {log[-1000:]}"
    return True, node_modules


_TS_MORPH_SCRIPT = r"""
const { Project, QuoteKind } = require("ts-morph");

const input = JSON.parse(process.argv[2]);
const project = new Project({
  manipulationSettings: {
    quoteKind: QuoteKind.Double,
    indentationText: "  ",
  },
});
const sourceFile = project.addSourceFileAtPathIfExists(input.routePath)
  ?? project.createSourceFile(input.routePath, "", { overwrite: true });

function successStatus(method) {
  return method === "POST" ? 201 : 200;
}

function statementsFor(method) {
  if (method === "GET") {
    return [
      `const ${input.variableName}: Array<Record<string, unknown>> = [];`,
      `return Response.json(${input.variableName});`,
    ];
  }
  if (method === "DELETE") {
    return ["return Response.json({ deleted: true });"];
  }
  return [
    "const body = (await request.json()) as Record<string, unknown>;",
    `return Response.json(body, { status: ${successStatus(method)} });`,
  ];
}

for (const method of input.methods) {
  if (sourceFile.getFunction(method)) continue;
  sourceFile.addFunction({
    isExported: true,
    isAsync: true,
    name: method,
    returnType: "Promise<Response>",
    parameters: method === "GET" || method === "DELETE"
      ? []
      : [{ name: "request", type: "Request" }],
    statements: statementsFor(method),
  });
}

sourceFile.formatText();
sourceFile.saveSync();
"""


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
