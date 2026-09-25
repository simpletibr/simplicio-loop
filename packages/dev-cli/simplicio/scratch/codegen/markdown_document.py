"""Deterministic Markdown document generation for explicit docs tasks."""

from __future__ import annotations

import re
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor


class MarkdownDocumentExecutor(TaskExecutor):
    """Create or update a docs/*.md file when the task names a marker."""

    name = "markdown-doc-marker"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        del stack
        target = _normalized_target(task.target)
        if target is None or not target.startswith("docs/") or not target.endswith(".md"):
            return False
        return "marker" in _task_text(task).lower()

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        del stack
        target_name = _normalized_target(task.target)
        if target_name is None:
            return _fallback(f"unsafe markdown target: {task.target}")

        marker = _parse_marker(task)
        if marker is None:
            return _fallback("unsupported markdown docs task shape")

        target = project_dir / target_name
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")

        if target.exists():
            original = target.read_text(encoding="utf-8")
            if marker in original:
                return CodegenResult(
                    passed=True,
                    files_modified=[],
                    log=f"{target_name} already contains marker text",
                )
            updated = original.rstrip() + _render_marker_section(marker)
        else:
            updated = _render_document(target, marker)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8", newline="\n")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"updated markdown evidence document {target_name}",
        )


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _normalized_target(target: str) -> str | None:
    normalized = target.replace("\\", "/").strip()
    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        return None
    return normalized


def _parse_marker(task: Task) -> str | None:
    text = _task_text(task)
    patterns = [
        r"marker\s+text\s+`([^`]+)`",
        r"include\s+.*?`([^`]+)`",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            marker = match.group(1).strip()
            if marker:
                return marker
    return None


def _render_document(target: Path, marker: str) -> str:
    title = _title_from_target(target)
    return (
        f"# {title}\n\n"
        "This document records the requested SimplicioCode visual sprint evidence.\n\n"
        f"## Marker\n\n{marker}\n"
    )


def _render_marker_section(marker: str) -> str:
    return f"\n\n## Simplicio Evidence\n\n{marker}\n"


def _title_from_target(target: Path) -> str:
    words = re.findall(r"[A-Za-z0-9]+", target.stem.replace("-", " "))
    return " ".join(word[:1].upper() + word[1:] for word in words) or "Simplicio Evidence"


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
