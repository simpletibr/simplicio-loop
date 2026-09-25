"""Tests for deterministic Markdown docs scratch codegen."""

from __future__ import annotations

from pathlib import Path

from simplicio.scratch.codegen import MarkdownDocumentExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="php-vanilla",
        path=tmp_path,
        meta={"language": "PHP", "framework": "Vanilla"},
    )


def _task() -> Task:
    return Task(
        id="T01-doc-marker",
        goal=(
            "Create or update docs/simplicio-code-desktop-debug-flow.md "
            "with marker text `SimplicioCode Desktop DEBUG E2E`."
        ),
        target="docs/simplicio-code-desktop-debug-flow.md",
        criteria=(
            "- file contains marker text `SimplicioCode Desktop DEBUG E2E`\n"
            "- document remains Markdown and reviewable"
        ),
        constraints="- keep the change limited to the requested evidence document",
        verify='grep -q "SimplicioCode Desktop DEBUG E2E" docs/simplicio-code-desktop-debug-flow.md',
    )


def test_markdown_document_executor_generates_marker_doc(tmp_path):
    executor = MarkdownDocumentExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    target = tmp_path / "docs/simplicio-code-desktop-debug-flow.md"
    assert result.passed is True
    assert result.files_modified == [target]
    text = target.read_text(encoding="utf-8")
    assert "# Simplicio Code Desktop Debug Flow" in text
    assert "SimplicioCode Desktop DEBUG E2E" in text


def test_markdown_document_executor_is_idempotent(tmp_path):
    executor = MarkdownDocumentExecutor()
    first = executor.execute(_task(), tmp_path, _stack(tmp_path))
    second = executor.execute(_task(), tmp_path, _stack(tmp_path))

    assert first.passed is True
    assert second.passed is True
    assert second.files_modified == []
    assert "already contains marker text" in second.log


def test_markdown_document_executor_registered() -> None:
    assert any(
        isinstance(executor, MarkdownDocumentExecutor) for executor in codegen_registry.registered_executors()
    )
