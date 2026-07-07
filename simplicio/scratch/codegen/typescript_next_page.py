"""Deterministic Next.js CRUD page generation for scratch tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..plan_schema import Task
from ..stack_registry import Stack
from .types import CodegenResult, TaskExecutor


@dataclass(frozen=True)
class _NextPageSpec:
    resource: str
    title: str
    item_type: str
    page_name: str
    variable_name: str
    singular_label: str


class TypeScriptAddNextPageExecutor(TaskExecutor):
    """Create a small typed CRUD page for Next.js app-router projects."""

    name = "typescript-add-next-page"

    def can_handle(self, task: Task, stack: Stack) -> bool:
        if not _is_next_stack(stack):
            return False
        if _page_parts(task.target) is None:
            return False
        text = _task_text(task).lower()
        return any(token in text for token in ("crud", "page", "screen", "ui", "form"))

    def execute(self, task: Task, project_dir: Path, stack: Stack) -> CodegenResult:
        spec = _parse_page_spec(task)
        if spec is None:
            return _fallback("unsupported Next.js page task shape")

        target = project_dir / task.target
        if target.exists() and not target.is_file():
            return _fallback(f"target is not a file: {task.target}")
        if target.exists() and _looks_generated(target.read_text(encoding="utf-8")):
            return CodegenResult(
                passed=True,
                files_modified=[],
                log=f"{task.target} already has a generated CRUD page",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_render_page(spec), encoding="utf-8", newline="\n")
        return CodegenResult(
            passed=True,
            files_modified=[target],
            log=f"generated Next.js CRUD page for {spec.resource}",
        )


def _is_next_stack(stack: Stack) -> bool:
    text = f"{stack.slug} {stack.language} {stack.framework}".lower()
    return "next" in text or stack.slug == "ts-nextjs"


def _task_text(task: Task) -> str:
    return "\n".join([task.goal, task.criteria, task.constraints])


def _parse_page_spec(task: Task) -> _NextPageSpec | None:
    parts = _page_parts(task.target)
    if parts is None:
        return None

    resource = _resource_from_parts(parts)
    if not resource:
        return None

    words = _words(resource)
    title = " ".join(word.capitalize() for word in words) or "Items"
    singular_words = _singular_words(words)
    singular_label = " ".join(word.capitalize() for word in singular_words) or "Item"
    item_type = _pascal_case(singular_words or words) or "Item"
    page_name = f"{_pascal_case(words) or 'Items'}Page"
    variable_name = _camel_case(words) or "items"
    return _NextPageSpec(
        resource=resource,
        title=title,
        item_type=item_type,
        page_name=page_name,
        variable_name=variable_name,
        singular_label=singular_label,
    )


def _page_parts(target: str) -> list[str] | None:
    normalized = target.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 4:
        return None
    if parts[:2] != ["src", "app"] or parts[-1] != "page.tsx":
        return None
    if "api" in parts[2:-1]:
        return None
    return parts[2:-1]


def _resource_from_parts(parts: list[str]) -> str:
    for part in reversed(parts):
        if part.startswith("[") and part.endswith("]"):
            continue
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "", part)
        if cleaned:
            return cleaned
    return ""


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
    if lower.endswith("es") and len(word) > 2:
        stem = word[:-2]
        if stem.lower().endswith(("ch", "sh", "x", "ss")):
            return stem
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
    return "data-simplicio-crud-page" in text and "export default async function" in text


def _render_page(spec: _NextPageSpec) -> str:
    return f'''type {spec.item_type} = {{
  id: string;
  name: string;
}};

async function fetch{spec.item_type}s(): Promise<{spec.item_type}[]> {{
  return [];
}}

export default async function {spec.page_name}() {{
  const {spec.variable_name} = await fetch{spec.item_type}s();

  return (
    <main data-simplicio-crud-page="{spec.resource}">
      <header>
        <h1>{spec.title}</h1>
        <p>Manage {spec.title.lower()} records.</p>
      </header>

      <section aria-labelledby="create-{spec.resource}">
        <h2 id="create-{spec.resource}">Create {spec.singular_label}</h2>
        <form>
          <label htmlFor="{spec.resource}-name">Name</label>
          <input id="{spec.resource}-name" name="name" type="text" />
          <button type="submit">Create</button>
        </form>
      </section>

      <section aria-labelledby="list-{spec.resource}">
        <h2 id="list-{spec.resource}">Existing {spec.title}</h2>
        <ul>
          {{{spec.variable_name}.length === 0 ? (
            <li>No {spec.title.lower()} yet.</li>
          ) : (
            {spec.variable_name}.map((item) => <li key={{item.id}}>{{item.name}}</li>)
          )}}
        </ul>
      </section>
    </main>
  );
}}
'''


def _fallback(log: str) -> CodegenResult:
    return CodegenResult(passed=False, log=log, fallback_to_llm=True)
