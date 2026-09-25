"""Deterministic Gin CRUD route generation for scratch tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _GinCrudSpec:
    resource: str
    item_type: str
    input_type: str
    store_name: str
    list_handler: str
    create_handler: str
    read_handler: str


class GoGinCrudExecutor(TaskExecutor):
    """Render a compact Gin CRUD router into internal/http/router.go."""

    name = "go-gin-crud"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if stack.slug != "go-gin":
            return False
        if task.target.replace("\\", "/") != "internal/http/router.go":
            return False
        text = _task_text(task).lower()
        return "crud" in text and any(token in text for token in ("gin", "route", "api"))

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        if task.target.replace("\\", "/") != "internal/http/router.go":
            return _fallback("unsupported go-gin CRUD task shape")
        spec = _parse_spec(task)
        if spec is None:
            return _fallback("unsupported go-gin CRUD task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")
        if target.exists() and _looks_generated(target.read_text(encoding="utf-8")):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{task.target} already has generated Gin CRUD routes",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_router(spec), encoding="utf-8", newline="\n")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"generated Gin CRUD routes for {spec.resource}",
        )


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_spec(task: Task) -> _GinCrudSpec | None:
    text = _task_text(task)
    route_match = re.search(r"route prefix is /([A-Za-z0-9_-]+)", text, re.I)
    resource = route_match.group(1) if route_match else _resource_from_goal(task.goal)
    words = _words(resource)
    if not words:
        return None
    singular_words = _singular_words(words)
    item_type = _pascal_case(singular_words) or "Item"
    input_type = f"{item_type}Input"
    base = _pascal_case(words) or "Items"
    singular = _pascal_case(singular_words) or "Item"
    return _GinCrudSpec(
        resource="_".join(word.lower() for word in words),
        item_type=item_type,
        input_type=input_type,
        store_name=f"{_camel_case(words)}Store",
        list_handler=f"List{base}",
        create_handler=f"Create{singular}",
        read_handler=f"Read{singular}",
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


def _pascal_case(words: list[str]) -> str:
    return "".join(word.capitalize() for word in words)


def _camel_case(words: list[str]) -> str:
    pascal = _pascal_case(words)
    if not pascal:
        return ""
    return pascal[0].lower() + pascal[1:]


def _looks_generated(text: str) -> bool:
    return "simplicio generated go-gin CRUD" in text


def _render_router(spec: _GinCrudSpec) -> str:
    return f"""package http

import (
\t"net/http"
\t"strconv"
\t"sync"

\t"github.com/gin-gonic/gin"
)

// simplicio generated go-gin CRUD
type {spec.item_type} struct {{
\tID   int    `json:"id"`
\tName string `json:"name"`
}}

type {spec.input_type} struct {{
\tName string `json:"name" binding:"required"`
}}

var {spec.store_name} = struct {{
\tsync.Mutex
\titems []{spec.item_type}
}}{{}}

func NewRouter() *gin.Engine {{
\trouter := gin.New()
\trouter.Use(gin.Logger(), gin.Recovery())
\trouter.GET("/health", Health)
\trouter.GET("/{spec.resource}", {spec.list_handler})
\trouter.POST("/{spec.resource}", {spec.create_handler})
\trouter.GET("/{spec.resource}/:id", {spec.read_handler})
\treturn router
}}

func Health(c *gin.Context) {{
\tc.JSON(http.StatusOK, gin.H{{"status": "ok"}})
}}

func {spec.list_handler}(c *gin.Context) {{
\t{spec.store_name}.Lock()
\tdefer {spec.store_name}.Unlock()
\tc.JSON(http.StatusOK, {spec.store_name}.items)
}}

func {spec.create_handler}(c *gin.Context) {{
\tvar input {spec.input_type}
\tif err := c.ShouldBindJSON(&input); err != nil {{
\t\tc.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
\t\treturn
\t}}

\t{spec.store_name}.Lock()
\tdefer {spec.store_name}.Unlock()
\titem := {spec.item_type}{{ID: len({spec.store_name}.items) + 1, Name: input.Name}}
\t{spec.store_name}.items = append({spec.store_name}.items, item)
\tc.JSON(http.StatusCreated, item)
}}

func {spec.read_handler}(c *gin.Context) {{
\tid, err := strconv.Atoi(c.Param("id"))
\tif err != nil {{
\t\tc.JSON(http.StatusBadRequest, gin.H{{"error": "invalid id"}})
\t\treturn
\t}}

\t{spec.store_name}.Lock()
\tdefer {spec.store_name}.Unlock()
\tfor _, item := range {spec.store_name}.items {{
\t\tif item.ID == id {{
\t\t\tc.JSON(http.StatusOK, item)
\t\t\treturn
\t\t}}
\t}}
\tc.JSON(http.StatusNotFound, gin.H{{"error": "not found"}})
}}
"""


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
