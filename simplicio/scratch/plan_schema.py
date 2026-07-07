"""plan_schema.py — strict schema for the planner output.

The planner emits a JSON document. We parse, validate against this schema,
and only then hand to the executor. Anything off-schema is a planner error —
the planner is RE-PROMPTED with the diff between schema + actual, up to
PLANNER_MAX_RETRIES (handled in planner.py).

Schema is hand-rolled instead of jsonschema to keep the package zero-dep.
The structure is simple enough that a manual validator gives clearer errors
than jsonschema-default output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"


@dataclass
class Task:
    id: str
    goal: str
    target: str
    criteria: str
    constraints: str
    verify: str
    depends_on: list[str] = field(default_factory=list)
    required_skill: str | None = None


@dataclass
class FileToCreate:
    path: str
    purpose: str


@dataclass
class Plan:
    version: str
    stack: str
    project_name: str
    rationale: str
    files_to_create: list[FileToCreate]
    tasks: list[Task]
    deps_to_install: list[str]
    deps_dev: list[str]
    test_command: str
    lint_command: str
    estimated_total_tasks: int


class PlanValidationError(ValueError):
    """Raised when the planner output is off-schema. Carries the human-readable
    diff so the planner can be re-prompted with the exact violation list."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("plan validation failed:\n  - " + "\n  - ".join(errors))


_TASK_ID_RE = re.compile(r"^T\d{2,3}-[a-z0-9][a-z0-9-]{0,40}$")
_PROJECT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def _need(d: dict, key: str, typ: type, errors: list[str], path: str) -> Any:
    if key not in d:
        errors.append(f"{path}.{key} missing")
        return None
    v = d[key]
    if not isinstance(v, typ):
        errors.append(f"{path}.{key} must be {typ.__name__}, got {type(v).__name__}")
        return None
    return v


def _list_of_str(v: Any, errors: list[str], path: str) -> list[str]:
    if not isinstance(v, list):
        errors.append(f"{path} must be list, got {type(v).__name__}")
        return []
    out = []
    for i, item in enumerate(v):
        if not isinstance(item, str):
            errors.append(f"{path}[{i}] must be str, got {type(item).__name__}")
            continue
        out.append(item)
    return out


def validate_plan(raw: dict) -> Plan:
    """Parse + validate. Raises PlanValidationError with the full error list
    so the planner can be re-prompted with diff context."""
    errors: list[str] = []

    if not isinstance(raw, dict):
        raise PlanValidationError([f"root must be object, got {type(raw).__name__}"])

    version = _need(raw, "version", str, errors, "")
    if version is not None and version != SCHEMA_VERSION:
        errors.append(f"version must be '{SCHEMA_VERSION}', got '{version}'")

    stack = _need(raw, "stack", str, errors, "") or ""
    project_name = _need(raw, "project_name", str, errors, "") or ""
    if project_name and not _PROJECT_NAME_RE.match(project_name):
        errors.append(f"project_name '{project_name}' must match {_PROJECT_NAME_RE.pattern}")

    rationale = _need(raw, "rationale", str, errors, "") or ""

    files_raw = _need(raw, "files_to_create", list, errors, "") or []
    files: list[FileToCreate] = []
    for i, fr in enumerate(files_raw):
        if not isinstance(fr, dict):
            errors.append(f"files_to_create[{i}] must be object")
            continue
        p = _need(fr, "path", str, errors, f"files_to_create[{i}]")
        pp = _need(fr, "purpose", str, errors, f"files_to_create[{i}]")
        if p is not None and pp is not None:
            files.append(FileToCreate(path=p, purpose=pp))

    tasks_raw = _need(raw, "tasks", list, errors, "") or []
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for i, tr in enumerate(tasks_raw):
        if not isinstance(tr, dict):
            errors.append(f"tasks[{i}] must be object")
            continue
        path = f"tasks[{i}]"
        tid = _need(tr, "id", str, errors, path) or ""
        if tid:
            if not _TASK_ID_RE.match(tid):
                errors.append(f"{path}.id '{tid}' must match {_TASK_ID_RE.pattern}")
            elif tid in seen_ids:
                errors.append(f"{path}.id '{tid}' is duplicated")
            else:
                seen_ids.add(tid)
        g = _need(tr, "goal", str, errors, path) or ""
        t = _need(tr, "target", str, errors, path) or ""
        c = _need(tr, "criteria", str, errors, path) or ""
        co = _need(tr, "constraints", str, errors, path) or ""
        v = _need(tr, "verify", str, errors, path) or ""
        d = tr.get("depends_on", [])
        deps = _list_of_str(d, errors, f"{path}.depends_on")
        required_skill = tr.get("required_skill")
        if required_skill is not None and not isinstance(required_skill, str):
            errors.append(f"{path}.required_skill must be str, got {type(required_skill).__name__}")
        if g and t and c and co and v:
            tasks.append(
                Task(
                    id=tid,
                    goal=g,
                    target=t,
                    criteria=c,
                    constraints=co,
                    verify=v,
                    depends_on=deps,
                    required_skill=required_skill,
                )
            )

    # Cross-task validation: depends_on must reference existing IDs
    for t in tasks:
        for dep in t.depends_on:
            if dep not in seen_ids:
                errors.append(f"tasks[{t.id}].depends_on references unknown id '{dep}'")

    deps_to_install = _list_of_str(raw.get("deps_to_install", []), errors, "deps_to_install")
    deps_dev = _list_of_str(raw.get("deps_dev", []), errors, "deps_dev")
    test_command = _need(raw, "test_command", str, errors, "") or ""
    lint_command = _need(raw, "lint_command", str, errors, "") or ""
    estimated = _need(raw, "estimated_total_tasks", int, errors, "")
    if estimated is None:
        estimated = 0
    elif estimated != len(tasks):
        errors.append(f"estimated_total_tasks={estimated} but tasks has {len(tasks)} entries")

    if errors:
        raise PlanValidationError(errors)

    return Plan(
        version=version or SCHEMA_VERSION,
        stack=stack,
        project_name=project_name,
        rationale=rationale,
        files_to_create=files,
        tasks=tasks,
        deps_to_install=deps_to_install,
        deps_dev=deps_dev,
        test_command=test_command,
        lint_command=lint_command,
        estimated_total_tasks=estimated,
    )


# Example minimal valid plan, used by tests + the --show-schema help command
EXAMPLE_PLAN: dict = {
    "version": "1.0",
    "stack": "py-fastapi",
    "project_name": "condo-mgmt",
    "rationale": "FastAPI is the lightest Python web stack with type hints; "
    "fits a CRUD admin app with low operational overhead.",
    "files_to_create": [
        {"path": "src/api/units.py", "purpose": "REST endpoints for the Unit entity"},
        {"path": "src/db/models.py", "purpose": "SQLAlchemy ORM model for Unit"},
    ],
    "tasks": [
        {
            "id": "T01-db-model",
            "depends_on": [],
            "goal": "Define the Unit ORM model with id, number, area, owner_id",
            "target": "src/db/models.py",
            "criteria": "- Unit class declared\n- 4 columns typed\n- 1 unit test asserting tablename",
            "constraints": "- use SQLAlchemy 2.0 declarative style",
            "verify": "pytest tests/db/test_models.py",
        },
    ],
    "deps_to_install": [
        "fastapi>=0.136.3",
        "sqlalchemy>=2.0.50",
        "uvicorn[standard]>=0.48.0",
    ],
    "deps_dev": ["pytest>=9.0.3", "httpx>=0.28.1"],
    "test_command": "pytest -q",
    "lint_command": "ruff check src tests",
    "estimated_total_tasks": 1,
}
