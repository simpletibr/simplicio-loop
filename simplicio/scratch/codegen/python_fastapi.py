"""Deterministic FastAPI route edits for scratch tasks."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .python_cst import (
    LibCSTUnavailable,
    append_module_statements,
    ensure_from_import,
    insert_module_statement_after_imports,
)
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _RouteSpec:
    method: str
    path: str
    function_name: str
    parameters: list[str]


@dataclass(frozen=True)
class _CrudRouteSpec:
    model_name: str
    resource_name: str
    prefix: str


class PythonAddFastApiRouteExecutor(TaskExecutor):
    """Add one small FastAPI route handler to an existing API module."""

    name = "python-add-fastapi-route"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_fastapi_stack(stack):
            return False
        target = task.target.replace("\\", "/").lower()
        if not target.endswith(".py") or "/src/api/" not in f"/{target}":
            return False
        text = _task_text(task).lower()
        return "endpoint" in text or "route" in text or "router" in text

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        crud_spec = _parse_crud_route_spec(task)
        if crud_spec is not None:
            return _write_crud_router(task, project_dir, crud_spec)

        spec = _parse_route_spec(task)
        if spec is None:
            return _fallback("unsupported FastAPI route task shape")

        target = project_dir / task.target
        if not target.is_file():
            return _fallback(f"target file not found: {task.target}")

        original = target.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original or "\n")
        except SyntaxError as exc:
            return _fallback(f"target is not valid Python: {exc.msg}")

        if _route_exists(tree, spec):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{spec.method.upper()} {spec.path} already exists; no changes needed",
            )

        newline = _detect_newline(original)
        try:
            updated = ensure_from_import(original, "fastapi", "APIRouter")
            if not _has_router_assignment(ast.parse(updated or "\n")):
                updated = insert_module_statement_after_imports(
                    updated,
                    f"router = APIRouter(){newline}",
                )
            updated = append_module_statements(updated, _render_route(spec, newline))
        except LibCSTUnavailable as exc:
            return _fallback(str(exc))

        target.write_text(updated, encoding="utf-8")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"added FastAPI {spec.method.upper()} {spec.path} route with libcst",
        )


def _is_fastapi_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language} {stack.framework}".lower()
    return "fastapi" in text or stack.slug.startswith("py-")


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_route_spec(task: Task) -> _RouteSpec | None:
    text = _task_text(task)
    method = _parse_method(text)
    path = _parse_path(text)
    if path is None:
        return None
    return _RouteSpec(
        method=method,
        path=path,
        function_name=_function_name(method, path, task.target),
        parameters=_path_parameters(path),
    )


def _parse_crud_route_spec(task: Task) -> _CrudRouteSpec | None:
    text = _task_text(task)
    lowered = text.lower()
    if "crud" not in lowered or "route" not in lowered:
        return None
    model_name = _parse_model_name(text) or _pascal_case(Path(task.target).stem)
    if not model_name:
        return None
    prefix = _parse_route_prefix(text) or f"/{Path(task.target).stem}"
    return _CrudRouteSpec(
        model_name=model_name,
        resource_name=_snake_case(model_name),
        prefix=prefix,
    )


def _parse_model_name(text: str) -> str | None:
    patterns = [
        r"\bCRUD\s+routes?\s+for\s+(?:the\s+)?([A-Z][A-Za-z0-9_]*)\b",
        r"\b([A-Z][A-Za-z0-9_]*)\s+CRUD\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _parse_route_prefix(text: str) -> str | None:
    match = re.search(r"\broute\s+prefix\s+is\s+`?(/[-A-Za-z0-9_/{}]+)`?", text)
    return match.group(1).rstrip("/") if match else None


def _pascal_case(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    if cleaned.endswith("ies") and len(cleaned) > 3:
        cleaned = f"{cleaned[:-3]}y"
    elif cleaned.endswith("s") and len(cleaned) > 1:
        cleaned = cleaned[:-1]
    parts = [part for part in cleaned.split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or None


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _parse_method(text: str) -> str:
    match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", text, re.IGNORECASE)
    return match.group(1).lower() if match else "get"


def _parse_path(text: str) -> str | None:
    for pattern in [
        r"`(/[^`]+)`",
        r"['\"](/[^'\"]+)['\"]",
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`'\"]+)",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(match.lastindex or 1)
            if value.startswith("/"):
                return value.rstrip(".,")
    return None


def _path_parameters(path: str) -> list[str]:
    return re.findall(r"{([A-Za-z_][A-Za-z0-9_]*)}", path)


def _function_name(method: str, path: str, target: str) -> str:
    resource = next((part for part in path.split("/") if part and not part.startswith("{")), "")
    if not resource:
        resource = Path(target).stem
    name = re.sub(r"[^A-Za-z0-9_]+", "_", resource).strip("_").lower() or "resource"
    prefix = {
        "get": "get",
        "post": "create",
        "put": "update",
        "patch": "update",
        "delete": "delete",
    }.get(method, method)
    return f"{prefix}_{_singular(name)}"


def _singular(name: str) -> str:
    return name[:-1] if name.endswith("s") and len(name) > 1 else name


def _route_exists(tree: ast.AST, spec: _RouteSpec) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _decorator_method(decorator.func) != spec.method:
                continue
            if decorator.args and _literal_string(decorator.args[0]) == spec.path:
                return True
    return False


def _decorator_method(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and _name(node.value) == "router":
        return node.attr.lower()
    return None


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _has_router_assignment(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_name(target) == "router" for target in node.targets):
                return True
        if isinstance(node, ast.AnnAssign) and _name(node.target) == "router":
            return True
    return False


def _render_route(spec: _RouteSpec, newline: str) -> str:
    params = ", ".join(f"{param}: str" for param in spec.parameters)
    body = (
        [f'    return {{"{spec.parameters[0]}": {spec.parameters[0]}}}{newline}']
        if spec.parameters
        else [f'    return {{"status": "ok"}}{newline}']
    )
    return "".join(
        [
            f'{newline}@router.{spec.method}("{spec.path}"){newline}',
            f"async def {spec.function_name}({params}) -> dict[str, str]:{newline}",
            *body,
        ]
    )


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _write_crud_router(
    task: Task,
    project_dir: Path,
    spec: _CrudRouteSpec,
) -> CodegenResult:
    target = project_dir / task.target
    schema_module = f"api.schemas.{spec.resource_name}"
    read_schema = f"{spec.model_name}Read"
    create_schema = f"{spec.model_name}Create"
    update_schema = f"{spec.model_name}Update"
    id_name = f"{spec.resource_name}_id"
    target.parent.mkdir(parents=True, exist_ok=True)
    (target.parent / "__init__.py").touch()
    schema_dir = project_dir / "src" / "api" / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "__init__.py").touch()
    target.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from datetime import UTC, datetime",
                "from itertools import count",
                "",
                "from fastapi import APIRouter, HTTPException, Response, status",
                "",
                f"from {schema_module} import (",
                f"    {create_schema},",
                f"    {read_schema},",
                f"    {update_schema},",
                ")",
                "",
                f'router = APIRouter(prefix="{spec.prefix}", tags=["{spec.resource_name}"])',
                "_ids = count(1)",
                f"_items: dict[int, {read_schema}] = {{}}",
                "",
                "",
                f'@router.get("", response_model=list[{read_schema}])',
                f"async def list_{spec.resource_name}s() -> list[{read_schema}]:",
                "    return list(_items.values())",
                "",
                "",
                f'@router.post("", response_model={read_schema}, status_code=status.HTTP_201_CREATED)',
                f"async def create_{spec.resource_name}(payload: {create_schema}) -> {read_schema}:",
                "    item_id = next(_ids)",
                f"    item = {read_schema}(",
                "        id=item_id,",
                "        name=payload.name,",
                "        created_at=datetime.now(UTC),",
                "    )",
                "    _items[item_id] = item",
                "    return item",
                "",
                "",
                f'@router.get("/{{{id_name}}}", response_model={read_schema})',
                f"async def read_{spec.resource_name}({id_name}: int) -> {read_schema}:",
                f"    return _get_{spec.resource_name}({id_name})",
                "",
                "",
                f'@router.patch("/{{{id_name}}}", response_model={read_schema})',
                f"async def update_{spec.resource_name}(",
                f"    {id_name}: int, payload: {update_schema}",
                f") -> {read_schema}:",
                f"    current = _get_{spec.resource_name}({id_name})",
                "    data = payload.model_dump(exclude_unset=True)",
                "    updated = current.model_copy(update=data)",
                f"    _items[{id_name}] = updated",
                "    return updated",
                "",
                "",
                f'@router.delete("/{{{id_name}}}", status_code=status.HTTP_204_NO_CONTENT)',
                f"async def delete_{spec.resource_name}({id_name}: int) -> Response:",
                f"    _get_{spec.resource_name}({id_name})",
                f"    del _items[{id_name}]",
                "    return Response(status_code=status.HTTP_204_NO_CONTENT)",
                "",
                "",
                f"def _get_{spec.resource_name}({id_name}: int) -> {read_schema}:",
                "    try:",
                f"        return _items[{id_name}]",
                "    except KeyError as exc:",
                f'        raise HTTPException(status_code=404, detail="{spec.model_name} not found") from exc',  # noqa: E501
                "",
            ]
        ),
        encoding="utf-8",
    )
    changed = [target]
    main_path = project_dir / "src" / "main.py"
    if main_path.is_file() and _mount_router(main_path, spec):
        changed.append(main_path)
    return CodegenResult(
        passed=True,
        files_modified=changed,
        log=f"created CRUD FastAPI router for {spec.model_name}",
    )


def _mount_router(main_path: Path, spec: _CrudRouteSpec) -> bool:
    original = main_path.read_text(encoding="utf-8")
    import_line = f"from api.routes.{Path(spec.prefix).name} import router as {spec.resource_name}_router"
    include_line = f"    app.include_router({spec.resource_name}_router)"
    updated = original
    if import_line not in updated:
        updated = updated.replace(
            "from fastapi import FastAPI\n",
            f"from fastapi import FastAPI\n\n{import_line}\n",
        )
    if include_line not in updated:
        updated = updated.replace(
            '    @app.get("/health")',
            f'{include_line}\n\n    @app.get("/health")',
        )
    if updated == original:
        return False
    main_path.write_text(updated, encoding="utf-8")
    return True


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
