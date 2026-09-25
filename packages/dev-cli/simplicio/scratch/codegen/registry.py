"""Registry for deterministic scratch task executors."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .go_gin import GoGinCrudExecutor
from .markdown_document import MarkdownDocumentExecutor
from .php_laravel import PhpLaravelCrudRoutesExecutor
from .python_fastapi import PythonAddFastApiRouteExecutor
from .python_orm import PythonAddOrmFieldExecutor
from .python_pydantic import PythonAddPydanticSchemaExecutor
from .python_pytest import PythonAddPytestTestExecutor
from .rust_axum import RustAxumCrudExecutor
from .types import CodegenResult, TaskExecutor
from .typescript_next_page import TypeScriptAddNextPageExecutor
from .typescript_next_route import TypeScriptAddNextRouteExecutor

_DEFAULT_EXECUTORS: list[TaskExecutor] = [
    MarkdownDocumentExecutor(),
    PythonAddOrmFieldExecutor(),
    PythonAddPydanticSchemaExecutor(),
    PythonAddFastApiRouteExecutor(),
    PythonAddPytestTestExecutor(),
    TypeScriptAddNextRouteExecutor(),
    TypeScriptAddNextPageExecutor(),
    RustAxumCrudExecutor(),
    GoGinCrudExecutor(),
    PhpLaravelCrudRoutesExecutor(),
]


def registered_executors() -> list[TaskExecutor]:
    return list(_DEFAULT_EXECUTORS)


def register_executor(executor: TaskExecutor) -> None:
    _DEFAULT_EXECUTORS.append(executor)


def try_execute(
    task: Task,
    project_dir: Path,
    stack: Stack,
    executors: Iterable[TaskExecutor] | None = None,
) -> CodegenResult | None:
    for executor in executors if executors is not None else _DEFAULT_EXECUTORS:
        if executor.can_handle(task, stack):
            result = executor.execute(task, project_dir, stack)
            result.executor_name = executor.name
            return result
    return None
