"""Deterministic Pydantic schema generation for scratch tasks."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .python_cst import LibCSTUnavailable, format_module
from .types import CodegenResult, TaskExecutor

_AUTO_INPUT_FIELDS = {"id", "created_at", "updated_at", "created_on", "updated_on"}
_TYPE_IMPORTS = {
    "date": ("datetime", "date"),
    "datetime": ("datetime", "datetime"),
    "Decimal": ("decimal", "Decimal"),
    "UUID": ("uuid", "UUID"),
}


@dataclass(frozen=True)
class _SchemaSpec:
    model_name: str
    model_path: Path


@dataclass(frozen=True)
class _ModelField:
    name: str
    type_text: str
    primary_key: bool = False
    has_default: bool = False
    nullable: bool = False
    generated_input: bool = False


class PythonAddPydanticSchemaExecutor(TaskExecutor):
    """Generate ``XCreate``, ``XUpdate``, and ``XRead`` Pydantic schemas."""

    name = "python-add-pydantic-schema"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_fastapi_stack(stack):
            return False
        target = task.target.replace("\\", "/").lower()
        if not target.endswith(".py"):
            return False
        if "/src/api/schemas/" not in f"/{target}" and "schema" not in Path(target).stem:
            return False
        text = _task_text(task).lower()
        return "pydantic" in text or "schema" in text

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        spec = _parse_schema_spec(task, project_dir)
        if spec is None:
            return _fallback("unsupported Pydantic schema task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")

        fields = _extract_model_fields(spec.model_path, spec.model_name)
        if not fields:
            return _fallback(f"could not derive fields from {spec.model_name} model")

        original = target.read_text(encoding="utf-8") if target.exists() else ""
        try:
            tree = ast.parse(original or "\n")
        except SyntaxError as exc:
            return _fallback(f"target schema file is not valid Python: {exc.msg}")

        classes = _schema_class_names(spec.model_name)
        existing = _module_class_names(tree)
        missing = [name for name in classes if name not in existing]
        if not missing:
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=(f"{spec.model_name} Pydantic schemas already exist; no changes needed"),
            )

        try:
            updated = format_module(
                _render_updated_schema_module(
                    original=original,
                    tree=tree,
                    model_name=spec.model_name,
                    fields=fields,
                    class_names=missing,
                )
            )
        except LibCSTUnavailable as exc:
            return _fallback(str(exc))
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return _fallback(f"generated Pydantic schemas are not valid Python: {exc.msg}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=(
                f"generated Pydantic schemas with libcst for {spec.model_name} from "
                f"{spec.model_path.relative_to(project_dir)}"
            ),
        )


def _is_fastapi_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language} {stack.framework}".lower()
    return "fastapi" in text or stack.slug.startswith("py-")


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_schema_spec(task: Task, project_dir: Path) -> _SchemaSpec | None:
    model_name = _parse_model_name(_task_text(task), task.target)
    if model_name is None:
        return None
    model_path = _find_model_path(project_dir, model_name, task.target)
    if model_path is None:
        return None
    return _SchemaSpec(model_name=model_name, model_path=model_path)


def _parse_model_name(text: str, target: str) -> str | None:
    patterns = [
        r"\b([A-Z][A-Za-z0-9_]*)\s*(?:Create|Update|Read)\b",
        r"\bschemas?\s+for\s+(?:the\s+)?([A-Z][A-Za-z0-9_]*)\b",
        r"\b([A-Z][A-Za-z0-9_]*)\s+schemas?\b",
        r"\b(?:for|of)\s+(?:the\s+)?([A-Z][A-Za-z0-9_]*)\s+(?:model|resource)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return _pascal_case(Path(target).stem)


def _pascal_case(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    if not cleaned:
        return None
    if cleaned.endswith("ies") and len(cleaned) > 3:
        cleaned = f"{cleaned[:-3]}y"
    elif cleaned.endswith("s") and len(cleaned) > 1:
        cleaned = cleaned[:-1]
    parts = [part for part in cleaned.split("_") if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _find_model_path(project_dir: Path, model_name: str, target: str) -> Path | None:
    stem = _snake_case(model_name)
    target_stem = Path(target).stem
    candidates = [
        project_dir / "src" / "db" / f"{stem}.py",
        project_dir / "src" / "db" / f"{target_stem}.py",
        project_dir / "src" / "db" / "models.py",
    ]
    db_root = project_dir / "src" / "db"
    if db_root.is_dir():
        candidates.extend(sorted(db_root.rglob("*.py")))

    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        if _has_sqlalchemy_model(path, model_name):
            return path
    return None


def _has_sqlalchemy_model(path: Path, model_name: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    model = _find_class(tree, model_name)
    return model is not None and _looks_like_sqlalchemy_model(model)


def _extract_model_fields(path: Path, model_name: str) -> list[_ModelField]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    model = _find_class(tree, model_name)
    if model is None or not _looks_like_sqlalchemy_model(model):
        return []

    fields: list[_ModelField] = []
    for item in model.body:
        if not isinstance(item, ast.AnnAssign):
            continue
        field = _field_from_annassign(item)
        if field is not None:
            fields.append(field)
    return fields


def _field_from_annassign(node: ast.AnnAssign) -> _ModelField | None:
    name = _target_name(node.target)
    if name is None or name.startswith("_") or name == "__tablename__":
        return None
    if _is_relationship_assignment(node.value):
        return None
    type_text = _mapped_type_text(node.annotation)
    if type_text is None or type_text.startswith("ClassVar["):
        return None

    primary_key = _call_kw_is_true(node.value, "primary_key")
    nullable = _call_kw_is_true(node.value, "nullable") or _is_optional_type(type_text)
    if nullable:
        type_text = _optionalize(type_text)
    return _ModelField(
        name=name,
        type_text=type_text,
        primary_key=primary_key,
        has_default=_has_default(node.value),
        nullable=nullable,
        generated_input=primary_key or name in _AUTO_INPUT_FIELDS,
    )


def _mapped_type_text(annotation: ast.expr) -> str | None:
    if isinstance(annotation, ast.Subscript) and _qualified_name(annotation.value).endswith("Mapped"):
        return _normalize_type(ast.unparse(annotation.slice))
    return None


def _normalize_type(type_text: str) -> str:
    text = type_text.strip().replace("typing.", "")
    optional = re.fullmatch(r"Optional\[(.+)\]", text)
    if optional:
        return _optionalize(_normalize_type(optional.group(1)))
    union = re.fullmatch(r"Union\[(.+),\s*None\]", text)
    if union:
        return _optionalize(_normalize_type(union.group(1)))
    union_none_first = re.fullmatch(r"Union\[None,\s*(.+)\]", text)
    if union_none_first:
        return _optionalize(_normalize_type(union_none_first.group(1)))
    return text


def _find_class(tree: ast.AST, class_name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _looks_like_sqlalchemy_model(node: ast.ClassDef) -> bool:
    if any(_qualified_name(base).split(".")[-1] in {"Base", "DeclarativeBase"} for base in node.bases):
        return True
    for item in node.body:
        if isinstance(item, ast.Assign):
            if any(_target_name(target) == "__tablename__" for target in item.targets):
                return True
        if isinstance(item, ast.AnnAssign) and _target_name(item.target) == "__tablename__":
            return True
    return False


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _qualified_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _is_relationship_assignment(node: ast.AST | None) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return _qualified_name(node.func).split(".")[-1] == "relationship"


def _call_kw_is_true(node: ast.AST | None, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    for keyword in node.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


def _has_default(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if not isinstance(node, ast.Call):
        return True
    default_keywords = {"default", "default_factory", "server_default"}
    return any(keyword.arg in default_keywords for keyword in node.keywords)


def _is_optional_type(type_text: str) -> bool:
    return type_text.endswith("| None") or type_text.startswith("None |") or " | None | " in type_text


def _optionalize(type_text: str) -> str:
    if _is_optional_type(type_text):
        return type_text
    return f"{type_text} | None"


def _schema_class_names(model_name: str) -> list[str]:
    return [f"{model_name}Create", f"{model_name}Update", f"{model_name}Read"]


def _module_class_names(tree: ast.AST) -> set[str]:
    return {node.name for node in getattr(tree, "body", []) if isinstance(node, ast.ClassDef)}


def _render_updated_schema_module(
    *,
    original: str,
    tree: ast.AST,
    model_name: str,
    fields: list[_ModelField],
    class_names: list[str],
) -> str:
    classes = _render_schema_classes(model_name, fields, class_names)
    if not original.strip():
        return _render_new_schema_module(fields, classes)

    newline = _detect_newline(original)
    lines = original.splitlines(keepends=True)
    _ensure_pydantic_import(lines, tree, newline)
    tree = ast.parse("".join(lines) or "\n")
    _ensure_type_imports(lines, tree, fields, newline)
    updated = "".join(lines).rstrip()
    return f"{updated}{newline}{newline}{classes}"


def _render_new_schema_module(fields: list[_ModelField], classes: str) -> str:
    imports = _render_imports(fields)
    return f"from __future__ import annotations\n\n{imports}\n\n\n{classes}"


def _render_imports(fields: list[_ModelField]) -> str:
    imports = []
    type_imports = _needed_type_imports(fields)
    for module in sorted(type_imports):
        names = ", ".join(sorted(type_imports[module]))
        imports.append(f"from {module} import {names}")
    pydantic_import = "from pydantic import BaseModel, ConfigDict"
    if not imports:
        return pydantic_import
    type_import_block = "\n".join(imports)
    return f"{type_import_block}\n\n{pydantic_import}"


def _needed_type_imports(fields: list[_ModelField]) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {}
    pattern = r"\b[A-Z][A-Za-z0-9_]*\b|\bdate\b|\bdatetime\b"
    for field in fields:
        names = set(re.findall(pattern, field.type_text))
        for name in names:
            item = _TYPE_IMPORTS.get(name)
            if item is None:
                continue
            module, import_name = item
            imports.setdefault(module, set()).add(import_name)
    return imports


def _render_schema_classes(
    model_name: str,
    fields: list[_ModelField],
    class_names: list[str],
) -> str:
    blocks = []
    for class_name in class_names:
        suffix = class_name.removeprefix(model_name)
        if suffix == "Create":
            blocks.append(_render_model_class(class_name, _input_fields(fields), "create"))
        elif suffix == "Update":
            blocks.append(_render_model_class(class_name, _input_fields(fields), "update"))
        elif suffix == "Read":
            blocks.append(_render_model_class(class_name, fields, "read"))
    return "\n\n\n".join(blocks) + "\n"


def _input_fields(fields: list[_ModelField]) -> list[_ModelField]:
    return [field for field in fields if not field.generated_input]


def _render_model_class(class_name: str, fields: list[_ModelField], mode: str) -> str:
    lines = [f"class {class_name}(BaseModel):"]
    if mode == "read":
        lines.append("    model_config = ConfigDict(from_attributes=True)")
        if fields:
            lines.append("")
    if not fields:
        lines.append("    pass")
        return "\n".join(lines)
    for field in fields:
        lines.append(_render_field(field, mode))
    return "\n".join(lines)


def _render_field(field: _ModelField, mode: str) -> str:
    if mode == "update":
        return f"    {field.name}: {_optionalize(field.type_text)} = None"
    if mode == "create" and (field.nullable or field.has_default):
        return f"    {field.name}: {_optionalize(field.type_text)} = None"
    return f"    {field.name}: {field.type_text}"


def _ensure_pydantic_import(lines: list[str], tree: ast.AST, newline: str) -> None:
    _ensure_from_import(lines, tree, "pydantic", ["BaseModel", "ConfigDict"], newline)


def _ensure_type_imports(lines: list[str], tree: ast.AST, fields: list[_ModelField], newline: str) -> None:
    for module, names in _needed_type_imports(fields).items():
        _ensure_from_import(lines, tree, module, sorted(names), newline)
        tree = ast.parse("".join(lines) or "\n")


def _ensure_from_import(
    lines: list[str],
    tree: ast.AST,
    module: str,
    names: list[str],
    newline: str,
) -> None:
    missing = set(names)
    insert_at = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            insert_at = max(insert_at, getattr(node, "end_lineno", node.lineno))
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_at = max(insert_at, getattr(node, "end_lineno", node.lineno))
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_at = max(insert_at, getattr(node, "end_lineno", node.lineno))
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module):
            continue
        if any(alias.name == "*" for alias in node.names):
            return
        imported = {alias.name for alias in node.names}
        missing -= imported
        if not missing:
            return
        if node.lineno == getattr(node, "end_lineno", node.lineno):
            _add_names_to_import_line(lines, node.lineno - 1, module, sorted(missing))
            return
    lines.insert(insert_at, f"from {module} import {', '.join(names)}{newline}")


def _add_names_to_import_line(lines: list[str], index: int, module: str, names: list[str]) -> None:
    escaped = re.escape(module)
    match = re.match(
        rf"^(\s*from\s+{escaped}\s+import\s+)(.*?)(\s*(#.*)?\r?\n?)$",
        lines[index],
    )
    if not match:
        return
    existing = [part.strip() for part in match.group(2).split(",") if part.strip()]
    lines[index] = f"{match.group(1)}{', '.join([*existing, *names])}{match.group(3)}"


def _detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
