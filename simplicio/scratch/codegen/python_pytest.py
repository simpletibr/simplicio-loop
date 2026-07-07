"""Deterministic pytest test generation for scratch tasks."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .python_cst import LibCSTUnavailable, format_module
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _FunctionTarget:
    name: str
    source_path: Path
    module: str
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class _CrudApiTestSpec:
    model_name: str
    resource_name: str
    prefix: str


class PythonAddPytestTestExecutor(TaskExecutor):
    """Generate one minimal pytest happy-path test for a Python function."""

    name = "python-add-pytest-test"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_python_stack(stack):
            return False
        target = task.target.replace("\\", "/").lower()
        if not target.endswith(".py"):
            return False
        if "tests/" not in f"{target}/" and "/tests/" not in f"/{target}":
            return False
        text = _task_text(task).lower()
        return "pytest" in text or "test" in text or Path(target).name.startswith("test_")

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        crud_spec = _parse_crud_api_test_spec(task)
        if crud_spec is not None:
            return _write_crud_api_test(task, project_dir, crud_spec)

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")

        function_target = _resolve_function_target(task, project_dir)
        if function_target is None:
            return _fallback("could not resolve a unique Python function to test")

        call_args = _call_args(function_target.node)
        if call_args is None:
            return _fallback(f"could not synthesize happy-path arguments for {function_target.name}")

        original = ""
        if target.exists():
            original = target.read_text(encoding="utf-8")
            try:
                tree = ast.parse(original)
            except SyntaxError as exc:
                return _fallback(f"target test file is not valid Python: {exc.msg}")
            test_name = _test_name(function_target.name)
            if _module_has_function(tree, test_name):
                return CodegenResult(
                    passed=True,
                    files_modified=[],
                    log=f"{test_name} already exists; no changes needed",
                )

        rendered = _render_test(function_target, call_args)
        try:
            updated = format_module(_append_test(original, rendered))
        except LibCSTUnavailable as exc:
            return _fallback(str(exc))
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return _fallback(f"generated pytest is not valid Python: {exc.msg}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=(
                f"generated pytest with libcst {target.relative_to(project_dir)} "
                f"for {function_target.module}.{function_target.name}"
            ),
        )


def _is_python_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language}".lower()
    return "python" in text or stack.slug.startswith("py-")


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_crud_api_test_spec(task: Task) -> _CrudApiTestSpec | None:
    target = task.target.replace("\\", "/").lower()
    text = _task_text(task)
    lowered = text.lower()
    if "tests/api/" not in f"/{target}" or "crud" not in lowered:
        return None
    if "route" not in lowered and "router" not in lowered:
        return None
    model_name = _parse_model_name(text) or _pascal_case(Path(task.target).stem)
    if not model_name:
        return None
    return _CrudApiTestSpec(
        model_name=model_name,
        resource_name=_snake_case(model_name),
        prefix=_parse_prefix_from_target(task.target),
    )


def _parse_model_name(text: str) -> str | None:
    match = re.search(r"\b([A-Z][A-Za-z0-9_]*)\s+CRUD\s+router\b", text)
    return match.group(1) if match else None


def _parse_prefix_from_target(target: str) -> str:
    stem = Path(target).stem
    if stem.startswith("test_"):
        stem = stem[5:]
    return f"/{stem}"


def _pascal_case(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    if cleaned.startswith("test_"):
        cleaned = cleaned[5:]
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


def _resolve_function_target(task: Task, project_dir: Path) -> _FunctionTarget | None:
    text = _task_text(task)
    source_paths = _source_paths_from_text(text, project_dir)
    function_name = _function_name_from_text(text)

    if function_name is None and len(source_paths) == 1:
        functions = _top_level_functions(source_paths[0])
        if len(functions) == 1:
            function_name = functions[0].name

    if function_name is None:
        return None

    if not source_paths:
        source_paths = _find_source_paths_defining(project_dir, function_name)
    if len(source_paths) != 1:
        return None

    source_path = source_paths[0]
    function = _find_function(source_path, function_name)
    if function is None:
        return None

    module = _module_name(source_path, project_dir)
    if module is None:
        return None

    return _FunctionTarget(
        name=function_name,
        source_path=source_path,
        module=module,
        node=function,
    )


def _source_paths_from_text(text: str, project_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for match in re.finditer(r"(?P<path>(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.py)", text):
        raw = match.group("path").strip("`'\"()[],;:")
        normalized = raw.replace("\\", "/")
        if normalized.startswith("tests/") or "/tests/" in f"/{normalized}":
            continue
        path = project_dir / normalized
        if path.is_file() and path not in paths:
            paths.append(path)
    return paths


def _function_name_from_text(text: str) -> str | None:
    patterns = [
        r"\bfunction\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:\(\s*\))?",
        r"\btarget\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:\(\s*\))?",
        r"\bfor\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\(",
        r"\btest\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:\(\s*\))?",
        r"`([A-Za-z_][A-Za-z0-9_]*)`\s+function\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _find_source_paths_defining(project_dir: Path, function_name: str) -> list[Path]:
    roots = [project_dir / "src"] if (project_dir / "src").is_dir() else [project_dir]
    paths: list[Path] = []
    for root in roots:
        for path in root.rglob("*.py"):
            normalized = path.relative_to(project_dir).as_posix()
            if normalized.startswith("tests/") or "/tests/" in f"/{normalized}":
                continue
            if _find_function(path, function_name) is not None:
                paths.append(path)
    return paths


def _top_level_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    return [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _find_function(path: Path, function_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in _top_level_functions(path):
        if node.name == function_name:
            return node
    return None


def _module_name(source_path: Path, project_dir: Path) -> str | None:
    roots = _import_roots(project_dir)
    resolved_source = source_path.resolve()
    for root in sorted(roots, key=lambda item: len(item.parts), reverse=True):
        try:
            relative = resolved_source.relative_to(root.resolve())
        except ValueError:
            continue
        module_path = relative.with_suffix("")
        parts = list(module_path.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if parts:
            return ".".join(parts)
    return None


def _import_roots(project_dir: Path) -> list[Path]:
    roots: list[Path] = []
    for entry in _pytest_pythonpath(project_dir):
        path = project_dir / entry
        if path.exists() and path not in roots:
            roots.append(path)
    src = project_dir / "src"
    if src.exists() and src not in roots:
        roots.append(src)
    if project_dir not in roots:
        roots.append(project_dir)
    return roots


def _pytest_pythonpath(project_dir: Path) -> list[str]:
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        return []
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*pythonpath\s*=\s*(.+)$", text)
    if not match:
        return []
    raw = match.group(1).strip()
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _call_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    args = node.args
    rendered: list[str] = []
    positional = list(args.posonlyargs) + list(args.args)
    required_positional = len(positional) - len(args.defaults)
    for arg in positional[:required_positional]:
        literal = _literal_for_arg(arg)
        if literal is None:
            return None
        rendered.append(literal)

    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if default is not None:
            continue
        literal = _literal_for_arg(arg)
        if literal is None:
            return None
        rendered.append(f"{arg.arg}={literal}")

    return ", ".join(rendered)


def _literal_for_arg(arg: ast.arg) -> str | None:
    annotation = _annotation_text(arg.annotation)
    lowered = annotation.lower().replace("typing.", "") if annotation else ""
    name = arg.arg.lower()

    if "str" in lowered:
        return '"sample"'
    if "int" in lowered:
        return "1"
    if "float" in lowered:
        return "1.0"
    if "bool" in lowered:
        return "True"
    if "list" in lowered or lowered.startswith("sequence") or lowered.startswith("iterable"):
        return "[]"
    if "dict" in lowered or lowered.startswith("mapping"):
        return "{}"
    if "set" in lowered:
        return "set()"
    if "tuple" in lowered:
        return "()"

    if any(token in name for token in ("text", "name", "email", "slug", "title", "query")):
        return '"sample"'
    if any(token in name for token in ("count", "index", "number", "size", "limit", "offset")):
        return "1"
    if name.endswith("_id") or name == "id":
        return "1"
    if any(token in name for token in ("items", "rows", "values")):
        return "[]"
    if any(token in name for token in ("data", "payload", "record")):
        return "{}"
    if name.startswith("is_") or name in {"enabled", "active"}:
        return "True"

    return None


def _annotation_text(annotation: ast.expr | None) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except AttributeError:
        if isinstance(annotation, ast.Name):
            return annotation.id
        return ""


def _render_test(function_target: _FunctionTarget, call_args: str) -> str:
    test_name = _test_name(function_target.name)
    call = f"{function_target.name}({call_args})"
    imports = []
    if isinstance(function_target.node, ast.AsyncFunctionDef):
        imports.append("import asyncio")
        call = f"asyncio.run({call})"
    imports.append(f"from {function_target.module} import {function_target.name}")

    return "\n".join(
        [
            *imports,
            "",
            "",
            f"def {test_name}() -> None:",
            f"    result = {call}",
            f"    {_assertion(function_target.node)}",
            "",
        ]
    )


def _test_name(function_name: str) -> str:
    return f"test_{function_name}_happy_path"


def _assertion(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    annotation = _annotation_text(node.returns).lower().replace("typing.", "")
    if annotation in {"none", "no return"}:
        return "assert result is None"
    if "bool" in annotation:
        return "assert isinstance(result, bool)"
    if "str" in annotation:
        return "assert isinstance(result, str)"
    if "int" in annotation:
        return "assert isinstance(result, int)"
    if "float" in annotation:
        return "assert isinstance(result, float)"
    if "list" in annotation:
        return "assert isinstance(result, list)"
    if "dict" in annotation:
        return "assert isinstance(result, dict)"
    if not _has_value_return(node):
        return "assert result is None"
    return "assert result is not None"


def _has_value_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            if isinstance(child.value, ast.Constant) and child.value.value is None:
                continue
            return True
    return False


def _append_test(original: str, rendered: str) -> str:
    if not original.strip():
        return rendered
    separator = "\n\n" if original.endswith("\n") else "\n\n\n"
    return f"{original}{separator}{rendered}"


def _module_has_function(tree: ast.AST, function_name: str) -> bool:
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        for node in getattr(tree, "body", [])
    )


def _write_crud_api_test(
    task: Task,
    project_dir: Path,
    spec: _CrudApiTestSpec,
) -> CodegenResult:
    target = project_dir / task.target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "from fastapi.testclient import TestClient",
                "",
                "from main import app",
                "",
                "",
                f"def test_{spec.resource_name}_crud_flow() -> None:",
                "    client = TestClient(app)",
                f'    created = client.post("{spec.prefix}", json={{"name": "Demo"}})',
                "    assert created.status_code == 201",
                "    created_payload = created.json()",
                '    item_id = created_payload["id"]',
                '    assert created_payload["name"] == "Demo"',
                "",
                f'    listed = client.get("{spec.prefix}")',
                "    assert listed.status_code == 200",
                '    assert any(item["id"] == item_id for item in listed.json())',
                "",
                f'    read = client.get(f"{spec.prefix}/{{item_id}}")',
                "    assert read.status_code == 200",
                '    assert read.json()["name"] == "Demo"',
                "",
                f'    updated = client.patch(f"{spec.prefix}/{{item_id}}", json={{"name": "Renamed"}})',
                "    assert updated.status_code == 200",
                '    assert updated.json()["name"] == "Renamed"',
                "",
                f'    deleted = client.delete(f"{spec.prefix}/{{item_id}}")',
                "    assert deleted.status_code == 204",
                "",
                f'    missing = client.get(f"{spec.prefix}/{{item_id}}")',
                "    assert missing.status_code == 404",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return CodegenResult(
        passed=True,
        files_modified=[target],
        log=f"generated CRUD API pytest for {spec.model_name}",
    )


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
