"""Deterministic Laravel route generation for scratch tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _LaravelCrudSpec:
    resource: str
    item_label: str


class PhpLaravelCrudRoutesExecutor(TaskExecutor):
    """Render compact JSON CRUD routes into routes/api.php."""

    name = "php-laravel-crud-routes"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if stack.slug != "php-laravel":
            return False
        if task.target.replace("\\", "/") != "routes/api.php":
            return False
        text = _task_text(task).lower()
        return "crud" in text and any(token in text for token in ("laravel", "route", "api"))

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        if task.target.replace("\\", "/") != "routes/api.php":
            return _fallback("unsupported php-laravel CRUD task shape")
        spec = _parse_spec(task)
        if spec is None:
            return _fallback("unsupported php-laravel CRUD task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")
        if target.exists() and _looks_generated(target.read_text(encoding="utf-8")):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{task.target} already has generated Laravel CRUD routes",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_routes(spec), encoding="utf-8", newline="\n")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"generated Laravel CRUD routes for {spec.resource}",
        )


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_spec(task: Task) -> _LaravelCrudSpec | None:
    text = _task_text(task)
    route_match = re.search(r"route prefix is /([A-Za-z0-9_-]+)", text, re.I)
    resource = route_match.group(1) if route_match else _resource_from_goal(task.goal)
    words = _words(resource)
    if not words:
        return None
    return _LaravelCrudSpec(
        resource="_".join(word.lower() for word in words),
        item_label=" ".join(word.lower() for word in _singular_words(words)),
    )


def _resource_from_goal(goal: str) -> str:
    match = re.search(
        r"for\s+([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,2})",
        goal,
        re.I,
    )
    return match.group(1) if match else "items"


def _words(value: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.strip())
    return re.findall(r"[A-Za-z0-9]+", expanded.replace("-", " ").replace("_", " "))


def _singular_words(words: list[str]) -> list[str]:
    if not words:
        return []
    out = list(words)
    out[-1] = _singularize(out[-1])
    return out


def _singularize(word: str) -> str:
    lower = word.lower()
    if lower.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if lower.endswith("s") and not lower.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _looks_generated(text: str) -> bool:
    return "simplicio generated php-laravel CRUD" in text


def _render_routes(spec: _LaravelCrudSpec) -> str:
    return f"""<?php

use Illuminate\\Http\\JsonResponse;
use Illuminate\\Http\\Request;
use Illuminate\\Support\\Facades\\Route;

Route::get('/health', function (): array {{
    return ['status' => 'ok'];
}})->name('health');

// simplicio generated php-laravel CRUD
Route::get('/{spec.resource}', function (): array {{
    return [];
}})->name('{spec.resource}.index');

Route::post('/{spec.resource}', function (Request $request): JsonResponse {{
    return response()->json([
        'id' => 1,
        'name' => $request->input('name', 'New {spec.item_label}'),
    ], 201);
}})->name('{spec.resource}.store');

Route::get('/{spec.resource}/{{id}}', function (int $id): array {{
    return [
        'id' => $id,
        'name' => 'Sample {spec.item_label}',
    ];
}})->name('{spec.resource}.show');
"""


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
