"""Deterministic SQLAlchemy ORM model edits for scratch tasks."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .python_cst import LibCSTUnavailable, append_statement_to_class, ensure_from_import
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _FieldSpec:
    model_name: str
    field_name: str
    mapped_type: str


@dataclass(frozen=True)
class _ModelSpec:
    model_name: str
    table_name: str
    fields: tuple[str, ...]


class PythonAddOrmFieldExecutor(TaskExecutor):
    """Add one SQLAlchemy 2.0 ``Mapped[...]`` field to an existing model."""

    name = "python-add-orm-field"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_python_stack(stack):
            return False
        target = task.target.replace("\\", "/").lower()
        if not target.endswith(".py"):
            return False
        if "/src/db/" not in f"/{target}" and "model" not in Path(target).stem:
            return False
        text = _task_text(task).lower()
        return ("field" in text or "column" in text) and (
            "model" in text or "orm" in text or "sqlalchemy" in text
        )

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        model_spec = _parse_model_spec(task)
        target = project_dir / task.target
        if model_spec is not None and not target.exists():
            return _create_model_file(target, model_spec)

        spec = _parse_field_spec(task)
        if spec is None:
            return _fallback("unsupported ORM field task shape")

        if not target.is_file():
            return _fallback(f"target file not found: {task.target}")

        original = target.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original)
        except SyntaxError as exc:
            return _fallback(f"target is not valid Python: {exc.msg}")

        model = _find_model_class(tree, spec.model_name)
        if model is None:
            return _fallback(f"could not find SQLAlchemy model class {spec.model_name}")
        if not _looks_like_sqlalchemy_model(model):
            return _fallback(f"class {spec.model_name} is not a SQLAlchemy model")
        if _class_has_field(model, spec.field_name):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=(f"{spec.model_name}.{spec.field_name} already exists; no changes needed"),
            )

        try:
            updated = ensure_from_import(original, "sqlalchemy.orm", "Mapped")
            updated = append_statement_to_class(
                updated,
                spec.model_name,
                f"{spec.field_name}: Mapped[{spec.mapped_type}]\n",
            )
        except LibCSTUnavailable as exc:
            return _fallback(str(exc))
        if updated is None:
            return _fallback(f"could not update class {spec.model_name} with LibCST")

        target.write_text(updated, encoding="utf-8")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=(f"added {spec.model_name}.{spec.field_name}: Mapped[{spec.mapped_type}] with libcst"),
        )


def _is_python_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language}".lower()
    return "python" in text or stack.slug.startswith("py-")


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_field_spec(task: Task) -> _FieldSpec | None:
    text = _task_text(task)
    model_name = _parse_model_name(text)
    field_name, mapped_type = _parse_field(text)
    if not model_name or not field_name or not mapped_type:
        return None
    return _FieldSpec(
        model_name=model_name,
        field_name=field_name,
        mapped_type=mapped_type,
    )


def _parse_model_spec(task: Task) -> _ModelSpec | None:
    text = _task_text(task)
    lowered = text.lower()
    if "model" not in lowered or "sqlalchemy" not in lowered:
        return None
    model_name = _parse_model_name(text) or _pascal_case(Path(task.target).stem)
    if not model_name:
        return None
    fields = _parse_model_fields(text)
    if not fields:
        return None
    return _ModelSpec(
        model_name=model_name,
        table_name=_parse_table_name(text) or f"{_snake_case(model_name)}s",
        fields=tuple(fields),
    )


def _parse_model_name(text: str) -> str | None:
    patterns = [
        r"\b(?:define|create|add)\s+(?:the\s+)?([A-Z][A-Za-z0-9_]*)\s+(?:SQLAlchemy\s+)?(?:ORM\s+)?model\b",
        r"\bclass\s+([A-Z][A-Za-z0-9_]*)\b",
        r"`([A-Z][A-Za-z0-9_]*)`\s+(?:ORM\s+)?model\b",
        r"\b([A-Z][A-Za-z0-9_]*)\s+(?:SQLAlchemy\s+)?(?:ORM\s+)?model\b",
        r"\b(?:to|on|in)\s+(?:the\s+)?([A-Z][A-Za-z0-9_]*)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _parse_model_fields(text: str) -> list[str]:
    match = re.search(
        r"\bwith\s+([a-z_][a-z0-9_,\s]*(?:\s+and\s+[a-z_][a-z0-9_]*)?)\s+(?:fields|columns)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        raw = re.sub(r"\band\b", ",", match.group(1), flags=re.IGNORECASE)
        fields = [
            field.strip() for field in raw.split(",") if re.fullmatch(r"[a-z_][a-z0-9_]*", field.strip())
        ]
        if fields:
            return list(dict.fromkeys(fields))

    lowered = text.lower()
    known = ["id", "name", "created_at", "updated_at"]
    fields = [field for field in known if re.search(rf"\b{field}\b", lowered)]
    return fields or ["id", "name"]


def _parse_table_name(text: str) -> str | None:
    match = re.search(
        r"\btable\s+name\s+(?:is|=)\s+`?([a-z_][a-z0-9_]*)`?",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _pascal_case(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    if not cleaned:
        return None
    if cleaned.endswith("ies") and len(cleaned) > 3:
        cleaned = f"{cleaned[:-3]}y"
    elif cleaned.endswith("s") and len(cleaned) > 1:
        cleaned = cleaned[:-1]
    return "".join(part[:1].upper() + part[1:] for part in cleaned.split("_") if part)


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _parse_field(text: str) -> tuple[str | None, str | None]:
    explicit = re.search(
        r"\b([a-z_][A-Za-z0-9_]*)\s*:\s*Mapped\[([A-Za-z0-9_., \[\]\"']+)\]",
        text,
    )
    if explicit:
        return explicit.group(1), explicit.group(2).strip()

    name_patterns = [
        r"\badd\s+(?:the\s+)?`?([a-z_][A-Za-z0-9_]*)`?\s+(?:field|column)\b",
        r"\b(?:field|column)\s+`?([a-z_][A-Za-z0-9_]*)`?\b",
    ]
    field_name = None
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            field_name = match.group(1)
            break

    if field_name is None:
        return None, None

    lowered = text.lower()
    if "mapped[str]" in lowered or " string" in lowered or field_name == "email":
        return field_name, "str"
    if "mapped[int]" in lowered or " integer" in lowered:
        return field_name, "int"
    if "mapped[bool]" in lowered or " boolean" in lowered:
        return field_name, "bool"
    return None, None


def _find_model_class(tree: ast.AST, model_name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == model_name:
            return node
    return None


def _looks_like_sqlalchemy_model(node: ast.ClassDef) -> bool:
    if any(_base_name(base) in {"Base", "DeclarativeBase"} for base in node.bases):
        return True
    for item in node.body:
        if isinstance(item, ast.Assign):
            if any(_target_name(target) == "__tablename__" for target in item.targets):
                return True
        if isinstance(item, ast.AnnAssign):
            if _target_name(item.target) == "__tablename__":
                return True
    return False


def _base_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return None


def _class_has_field(node: ast.ClassDef, field_name: str) -> bool:
    for item in node.body:
        if isinstance(item, ast.AnnAssign):
            if _target_name(item.target) == field_name:
                return True
        if isinstance(item, ast.Assign):
            if any(_target_name(target) == field_name for target in item.targets):
                return True
    return False


def _create_model_file(target: Path, spec: _ModelSpec) -> CodegenResult:
    target.parent.mkdir(parents=True, exist_ok=True)
    field_lines = []
    for field in spec.fields:
        if field == "id":
            field_lines.append("    id: Mapped[int] = mapped_column(primary_key=True)")
        elif field.endswith("_id"):
            field_lines.append(f"    {field}: Mapped[int]")
        elif field == "created_at":
            field_lines.append(
                "    created_at: Mapped[datetime] = mapped_column("
                "DateTime(timezone=True), server_default=func.now())"
            )
        elif field == "updated_at":
            field_lines.append(
                "    updated_at: Mapped[datetime | None] = mapped_column("
                "DateTime(timezone=True), nullable=True)"
            )
        elif field in {"area", "amount", "total"}:
            field_lines.append(f"    {field}: Mapped[float]")
        else:
            field_lines.append(f"    {field}: Mapped[str]")
    content = "\n".join(
        [
            "from __future__ import annotations",
            "",
            "from datetime import datetime",
            "",
            "from sqlalchemy import DateTime, func",
            "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column",
            "",
            "",
            "class Base(DeclarativeBase):",
            "    pass",
            "",
            "",
            f"class {spec.model_name}(Base):",
            f'    __tablename__ = "{spec.table_name}"',
            "",
            *field_lines,
            "",
        ]
    )
    target.write_text(content, encoding="utf-8")
    return CodegenResult(
        passed=True,
        files_modified=[target],
        log=f"created SQLAlchemy model {spec.model_name} in {target.name}",
    )


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
