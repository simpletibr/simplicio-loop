"""Shared contracts for deterministic scratch task executors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack


@dataclass
class CodegenResult:
    passed: bool
    files_modified: list[Path] = field(default_factory=list)
    log: str = ""
    fallback_to_llm: bool = False
    executor_name: str | None = None


class TaskExecutor(ABC):
    name: str

    @abstractmethod
    def can_handle(self, task: Task, stack: Stack) -> bool:
        """Return True when this executor can handle the task mechanically."""

    @abstractmethod
    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        """Apply the deterministic task edit and return the execution result."""
