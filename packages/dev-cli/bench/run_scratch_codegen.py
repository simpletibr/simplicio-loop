"""Benchmark deterministic scratch codegen through the real executor path.

This is intentionally keyless: it removes SIMPLICIO_MODEL while running so
fallbacks are reported as skipped instead of calling an LLM. The report is a
local evidence slice for the mechanical executors, not the full 50-run LLM
reduction release gate.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio.scratch.executor import execute_plan  # noqa: E402
from simplicio.scratch.codegen import registry as codegen_registry  # noqa: E402
from simplicio.scratch.plan_schema import Plan, Task  # noqa: E402
from simplicio.scratch.stack_registry import Stack  # noqa: E402


RESULTS_JSON = ROOT / "bench" / "results_scratch_codegen.json"
RESULTS_MD = ROOT / "bench" / "results_scratch_codegen.md"
LIVE_GATE_JSON = ROOT / "bench" / "results_scratch_live_gate.json"


@dataclass(frozen=True)
class BenchCase:
    name: str
    stack_slug: str
    language: str
    framework: str
    task: Task
    seed_files: dict[str, str]
    expected_executor: str


def build_cases(*, include_typescript: bool = True) -> list[BenchCase]:
    cases = [
        BenchCase(
            name="python-orm-field",
            stack_slug="py-fastapi",
            language="Python",
            framework="FastAPI",
            task=Task(
                id="T01-db-model",
                goal="Add email: Mapped[str] field to User model",
                target="src/db/models.py",
                criteria="- User has email: Mapped[str]",
                constraints="- use SQLAlchemy 2.0 declarative style",
                verify="pytest tests/db/test_models.py -q",
            ),
            seed_files={
                "src/db/models.py": """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
"""
            },
            expected_executor="python-add-orm-field",
        ),
        BenchCase(
            name="python-pydantic-schema",
            stack_slug="py-fastapi",
            language="Python",
            framework="FastAPI",
            task=Task(
                id="T02-api-schemas",
                goal="Create Pydantic schemas for User create, update, and read flows.",
                target="src/api/schemas/user.py",
                criteria=(
                    "- UserCreate, UserUpdate, and UserRead schemas exist\n"
                    "- optional update fields are supported"
                ),
                constraints="- keep schemas framework-agnostic",
                verify="pytest tests/api/test_users.py -q",
            ),
            seed_files={
                "src/db/user.py": """from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
"""
            },
            expected_executor="python-add-pydantic-schema",
        ),
        BenchCase(
            name="python-fastapi-route",
            stack_slug="py-fastapi",
            language="Python",
            framework="FastAPI",
            task=Task(
                id="T03-api-route",
                goal="Add GET `/users/{id}` endpoint to the users route",
                target="src/api/users.py",
                criteria="- exposes @router.get with async handler and return type",
                constraints="- keep existing imports",
                verify="pytest tests/api/test_users.py -q",
            ),
            seed_files={
                "src/api/users.py": """from fastapi import APIRouter

router = APIRouter()
"""
            },
            expected_executor="python-add-fastapi-route",
        ),
        BenchCase(
            name="python-pytest-test",
            stack_slug="py-fastapi",
            language="Python",
            framework="FastAPI",
            task=Task(
                id="T04-pytest",
                goal="Generate a happy-path pytest for function double in src/utils/math_ops.py",
                target="tests/unit/test_math_ops.py",
                criteria="- imports the function under test\n- has a sane assert",
                constraints="- use pytest",
                verify="pytest tests/unit/test_math_ops.py -q",
            ),
            seed_files={
                "pyproject.toml": """[tool.pytest.ini_options]
pythonpath = ["src"]
""",
                "src/utils/math_ops.py": """def double(value: int) -> int:
    return value * 2
""",
            },
            expected_executor="python-add-pytest-test",
        ),
    ]

    if include_typescript:
        cases.append(
            BenchCase(
                name="typescript-next-route",
                stack_slug="ts-nextjs",
                language="TypeScript 5",
                framework="Next.js app router",
                task=Task(
                    id="T05-next-route",
                    goal="Create Next.js route handlers for Unit CRUD",
                    target="src/app/api/units/route.ts",
                    criteria="- exports GET and POST handlers\n- returns JSON responses",
                    constraints="- no external dependencies",
                    verify="pnpm vitest run src/app/api/units/route.test.ts",
                ),
                seed_files={},
                expected_executor="typescript-add-next-route",
            )
        )
        cases.append(
            BenchCase(
                name="typescript-next-page",
                stack_slug="ts-nextjs",
                language="TypeScript 5",
                framework="Next.js app router",
                task=Task(
                    id="T06-next-page",
                    goal="Create a Condo Unit CRUD page",
                    target="src/app/condo_units/page.tsx",
                    criteria="- page fetches condo_units\n- create form is rendered",
                    constraints="- keep component typed and accessible",
                    verify="pnpm tsc --noEmit",
                ),
                seed_files={},
                expected_executor="typescript-add-next-page",
            )
        )

    cases.extend(
        [
            BenchCase(
                name="go-gin-crud",
                stack_slug="go-gin",
                language="Go",
                framework="Gin",
                task=Task(
                    id="T07-gin-crud",
                    goal="Implement Gin CRUD routes for condo_units.",
                    target="internal/http/router.go",
                    criteria=(
                        "- list, create, and read routes are present\n"
                        "- route prefix is /condo_units\n"
                        "- handlers return JSON responses"
                    ),
                    constraints="- keep the service self-contained and typed",
                    verify="go test ./...",
                ),
                seed_files={},
                expected_executor="go-gin-crud",
            ),
            BenchCase(
                name="rust-axum-crud",
                stack_slug="rust-axum",
                language="Rust",
                framework="Axum",
                task=Task(
                    id="T08-axum-crud",
                    goal="Implement Axum CRUD routes for condo_units.",
                    target="src/main.rs",
                    criteria=(
                        "- list and create routes are present\n"
                        "- route prefix is /condo_units\n"
                        "- route tests exercise the generated API"
                    ),
                    constraints="- keep the service self-contained and typed",
                    verify="cargo test",
                ),
                seed_files={},
                expected_executor="rust-axum-crud",
            ),
            BenchCase(
                name="php-laravel-routes",
                stack_slug="php-laravel",
                language="PHP",
                framework="Laravel",
                task=Task(
                    id="T09-laravel-routes",
                    goal="Implement Laravel CRUD API routes for condo_units.",
                    target="routes/api.php",
                    criteria=(
                        "- list, create, and show routes are present\n"
                        "- route prefix is /condo_units\n"
                        "- create route returns a JSON 201 response"
                    ),
                    constraints="- keep routes compact and framework-native",
                    verify="php vendor/bin/phpunit --configuration phpunit.xml",
                ),
                seed_files={},
                expected_executor="php-laravel-crud-routes",
            ),
        ]
    )

    return cases


def run_benchmark(
    *,
    work_dir: Path | None = None,
    repeat: int = 10,
    include_typescript: bool = True,
    llm_baseline: dict[str, Any] | None = None,
    live_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("repeat must be >= 1")

    owned_temp = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="simplicio-scratch-codegen-"))
        owned_temp = True
    work_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases(include_typescript=include_typescript)
    baseline = _normalize_llm_baseline(llm_baseline) if llm_baseline else None
    live_corpus = _normalize_live_gate(live_gate) if live_gate else None
    projects_parent = work_dir / "projects"
    templates_parent = work_dir / "templates"
    projects_parent.mkdir(parents=True, exist_ok=True)
    templates_parent.mkdir(parents=True, exist_ok=True)

    old_model = os.environ.pop("SIMPLICIO_MODEL", None)
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        for run_index in range(1, repeat + 1):
            for case in cases:
                rows.append(
                    _run_case(
                        case,
                        run_index=run_index,
                        projects_parent=projects_parent,
                        templates_parent=templates_parent,
                    )
                )
    finally:
        if old_model is not None:
            os.environ["SIMPLICIO_MODEL"] = old_model

    elapsed_s = round(time.perf_counter() - t0, 3)
    return {
        "benchmark": "scratch-codegen",
        "scope": (
            "deterministic executor benchmark plus live scratch-corpus evidence; "
            "synthetic cases validate individual executors while the live gate "
            "proves release-corpus mechanical-task metrics"
        ),
        "work_dir": "$WORK_DIR",
        "work_dir_owned_by_runner": owned_temp,
        "repeat": repeat,
        "include_typescript": include_typescript,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "llm_baseline": baseline,
        "live_corpus": live_corpus,
        "summary": _summarize(rows, elapsed_s, baseline, live_corpus),
        "cases": rows,
    }


def capture_llm_baseline(
    *,
    work_dir: Path | None = None,
    repeat: int = 1,
    include_typescript: bool = True,
) -> dict[str, Any]:
    """Capture an equivalent LLM path baseline with mechanical executors disabled."""
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    model = os.environ.get("SIMPLICIO_MODEL", "").strip()
    if not model:
        raise RuntimeError("SIMPLICIO_MODEL must be set to capture an LLM baseline")

    owned_temp = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="simplicio-scratch-llm-baseline-"))
        owned_temp = True
    work_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases(include_typescript=include_typescript)
    projects_parent = work_dir / "projects"
    templates_parent = work_dir / "templates"
    projects_parent.mkdir(parents=True, exist_ok=True)
    templates_parent.mkdir(parents=True, exist_ok=True)

    old_executors = codegen_registry._DEFAULT_EXECUTORS
    codegen_registry._DEFAULT_EXECUTORS = []
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        for run_index in range(1, repeat + 1):
            for case in cases:
                rows.append(
                    _run_llm_baseline_case(
                        case,
                        run_index=run_index,
                        projects_parent=projects_parent,
                        templates_parent=templates_parent,
                    )
                )
    finally:
        codegen_registry._DEFAULT_EXECUTORS = old_executors

    elapsed_s = round(time.perf_counter() - t0, 3)
    summary = _summarize_llm_baseline(rows, elapsed_s, model)
    return {
        "benchmark": "scratch-codegen-llm-baseline",
        "source": "captured by bench/run_scratch_codegen.py --capture-llm-baseline-json",
        "scope": (
            "equivalent LLM scratch-task baseline with mechanical executors "
            "disabled; intended as input to --llm-baseline-json"
        ),
        "work_dir": "$WORK_DIR",
        "work_dir_owned_by_runner": owned_temp,
        "repeat": repeat,
        "include_typescript": include_typescript,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "model": model,
        },
        "summary": summary,
        "cases": rows,
    }


def _run_case(
    case: BenchCase,
    *,
    run_index: int,
    projects_parent: Path,
    templates_parent: Path,
) -> dict[str, Any]:
    project_name = f"{case.name}-r{run_index:02d}"
    template_root = templates_parent / project_name
    _write_seed_tree(template_root / "tree", case.seed_files)
    stack = Stack(
        slug=case.stack_slug,
        path=template_root,
        meta={
            "language": case.language,
            "framework": case.framework,
            "template_version": "bench-scratch-codegen-v1",
        },
    )
    plan = _plan_for_case(case, project_name)

    try:
        report = execute_plan(plan, stack, projects_parent, skip_install=True)
    except Exception as exc:  # pragma: no cover - defensive bench reporting
        return {
            "name": case.name,
            "run_index": run_index,
            "stack": case.stack_slug,
            "expected_executor": case.expected_executor,
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    task = report.task_results[0] if report.task_results else None
    executor = task.codegen_executor if task is not None else None
    expected_match = executor == case.expected_executor
    task_passed = bool(task and task.passed)
    work_dir = projects_parent.parent
    validation = _validate_generated_case(case, report.project_dir, work_dir)
    return {
        "name": case.name,
        "run_index": run_index,
        "stack": case.stack_slug,
        "project_dir": _redact_path(report.project_dir, work_dir),
        "expected_executor": case.expected_executor,
        "actual_executor": executor,
        "expected_executor_match": expected_match,
        "passed": task_passed and expected_match and validation["passed"],
        "task_passed": task_passed,
        "validation": validation,
        "execution_mode": task.execution_mode if task is not None else "missing",
        "duration_ms": task.duration_ms if task is not None else 0,
        "metrics": report.metrics,
        "log_tail": _redact_text(task.log_tail[-300:], work_dir)
        if task is not None
        else "",
    }


def _run_llm_baseline_case(
    case: BenchCase,
    *,
    run_index: int,
    projects_parent: Path,
    templates_parent: Path,
) -> dict[str, Any]:
    project_name = f"llm-{case.name}-r{run_index:02d}"
    template_root = templates_parent / project_name
    _write_seed_tree(template_root / "tree", case.seed_files)
    stack = Stack(
        slug=case.stack_slug,
        path=template_root,
        meta={
            "language": case.language,
            "framework": case.framework,
            "template_version": "bench-scratch-codegen-v1",
        },
    )
    work_dir = projects_parent.parent
    project_dir = projects_parent / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    stack.render_tree(project_dir, {"project_name": project_name})
    _ensure_git_repo(project_dir)

    started = time.perf_counter()
    previous_cwd = Path.cwd()
    try:
        from simplicio.providers import generate

        os.chdir(project_dir)
        output = generate(_llm_baseline_prompt(case))
    except Exception as exc:  # pragma: no cover - defensive bench reporting
        return {
            "name": case.name,
            "run_index": run_index,
            "stack": case.stack_slug,
            "passed": False,
            "execution_mode": "failed",
            "duration_ms": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        os.chdir(previous_cwd)

    content = _extract_llm_file_content(output)
    target = project_dir / case.task.target
    if content:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    validation = (
        _validate_generated_case(case, project_dir, work_dir)
        if content
        else {
            "passed": False,
            "checks": [],
            "log": "LLM output did not include file content",
        }
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "name": case.name,
        "run_index": run_index,
        "stack": case.stack_slug,
        "project_dir": _redact_path(project_dir, work_dir),
        "passed": validation["passed"],
        "task_passed": validation["passed"],
        "validation": validation,
        "execution_mode": "llm",
        "duration_ms": duration_ms,
        "metrics": {
            "tasks_total": 1,
            "tasks_codegen": 0,
            "tasks_llm": 1,
            "tasks_skipped": 0,
            "tasks_failed": 0 if validation["passed"] else 1,
        },
        "log_tail": _redact_text((output or "")[-300:], work_dir),
    }


def _llm_baseline_prompt(case: BenchCase) -> str:
    seed = "\n\n".join(
        f"--- {path} ---\n{content}" for path, content in case.seed_files.items()
    )
    if not seed:
        seed = "(no existing files)"
    return f"""You are the LLM baseline for a code-generation benchmark.

Return ONLY one JSON object with this shape:
{{"path": "{case.task.target}", "content": "<complete file content>"}}

Do not include markdown fences or prose.

Task:
{case.task.goal}

Acceptance criteria:
{case.task.criteria}

Constraints:
{case.task.constraints}

Existing files:
{seed}
"""


def _extract_llm_file_content(output: str | None) -> str:
    if not output:
        return ""
    parsed = _extract_json_object(output)
    if isinstance(parsed, dict):
        content = parsed.get("content")
        if isinstance(content, str) and content.strip():
            return content
        files = parsed.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, dict) and isinstance(item.get("content"), str):
                    return item["content"]

    fenced = re.search(r"```(?:[A-Za-z0-9_.+-]+)?\s*\n(.*?)```", output, re.S)
    if fenced:
        return fenced.group(1).strip()
    return output.strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(stripped)):
            char = stripped[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(stripped[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    return value if isinstance(value, dict) else None
        start = stripped.find("{", start + 1)
    return None


def _write_seed_tree(tree: Path, seed_files: dict[str, str]) -> None:
    for rel_path, content in seed_files.items():
        path = tree / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _ensure_git_repo(path: Path) -> None:
    if (path / ".git").exists():
        return
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )


def _validate_generated_case(
    case: BenchCase,
    project_dir: Path,
    work_dir: Path,
) -> dict[str, Any]:
    target = project_dir / case.task.target
    if case.expected_executor == "python-add-orm-field":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "user_class": "class User",
                "email_field": "email",
                "mapped_type": "Mapped[",
            },
        )
    if case.expected_executor == "python-add-pydantic-schema":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "user_create": "class UserCreate",
                "user_update": "class UserUpdate",
                "user_read": "class UserRead",
            },
        )
    if case.expected_executor == "python-add-fastapi-route":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "router_get": "@router.get",
                "path_param": "{id}",
                "async_handler": "async def",
            },
        )
    if case.expected_executor == "python-add-pytest-test":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "imports_double": "double",
                "assertion": "assert",
                "test_function": "def test_",
            },
        )
    if case.expected_executor == "typescript-add-next-route":
        return _validate_next_route(target, work_dir)
    if case.expected_executor == "typescript-add-next-page":
        return _validate_next_page(target, work_dir)
    if case.expected_executor == "go-gin-crud":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "package_http": "package http",
                "gin_import": "github.com/gin-gonic/gin",
                "router_ctor": "func NewRouter()",
                "route_prefix": '"/condo_units"',
                "json_response": "c.JSON",
            },
        )
    if case.expected_executor == "rust-axum-crud":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "axum_import": "use axum::",
                "item_type": "struct CondoUnit",
                "router": "Router::new()",
                "route_prefix": '"/condo_units"',
                "route_test": "condo_units_crud_routes_work",
            },
        )
    if case.expected_executor == "php-laravel-crud-routes":
        return _validate_text_markers(
            target,
            work_dir,
            {
                "php_open": "<?php",
                "route_get": "Route::get('/condo_units'",
                "route_post": "Route::post('/condo_units'",
                "json_response": "JsonResponse",
                "created_status": "201",
            },
        )
    return {"passed": True, "checks": [], "log": "no post-validation required"}


def _validate_text_markers(
    target: Path,
    work_dir: Path,
    markers: dict[str, str],
) -> dict[str, Any]:
    if not target.is_file():
        return {
            "passed": False,
            "checks": ["file_exists"],
            "log": f"missing generated file: {_redact_path(target, work_dir)}",
        }
    content = target.read_text(encoding="utf-8")
    checks = [name for name, marker in markers.items() if marker in content]
    missing = sorted(set(markers) - set(checks))
    return {
        "passed": not missing,
        "checks": checks,
        "log": (
            "generated file contains required structural markers"
            if not missing
            else "missing markers: " + ", ".join(missing)
        ),
    }


def _validate_next_page(page_path: Path, work_dir: Path) -> dict[str, Any]:
    if not page_path.is_file():
        return {
            "passed": False,
            "checks": ["page_file_exists"],
            "log": f"missing generated page file: {_redact_path(page_path, work_dir)}",
        }
    content = page_path.read_text(encoding="utf-8")
    checks = []
    if "data-simplicio-crud-page" in content:
        checks.append("crud_page_marker")
    if "export default async function" in content:
        checks.append("async_page_component")
    if "<form>" in content and 'type="submit"' in content:
        checks.append("create_form")
    if ".map((item)" in content:
        checks.append("list_render")
    required = {
        "crud_page_marker",
        "async_page_component",
        "create_form",
        "list_render",
    }
    missing = sorted(required - set(checks))
    return {
        "passed": not missing,
        "checks": checks,
        "log": (
            "generated CRUD page has marker, async component, form, and list"
            if not missing
            else "missing generated page checks: " + ", ".join(missing)
        ),
    }


def _validate_next_route(route_path: Path, work_dir: Path) -> dict[str, Any]:
    if not route_path.is_file():
        return {
            "passed": False,
            "checks": ["route_file_exists"],
            "log": f"missing generated route file: {_redact_path(route_path, work_dir)}",
        }

    node = shutil.which("node") or shutil.which("node.exe")
    if node is None:
        return {
            "passed": False,
            "checks": ["node_available"],
            "log": "node was not found; cannot validate generated Next route",
        }

    typescript_dir = _find_typescript_package(route_path.parent)
    if typescript_dir is None:
        return {
            "passed": False,
            "checks": ["typescript_available"],
            "log": "typescript package was not found; cannot compile generated route",
        }

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".cjs", delete=False
    ) as handle:
        handle.write(_NEXT_ROUTE_VALIDATOR_SCRIPT)
        script = Path(handle.name)
    try:
        proc = subprocess.run(
            [node, str(script), str(route_path), str(typescript_dir)],
            cwd=route_path.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "passed": False,
            "checks": ["typescript_compile", "route_runtime"],
            "log": f"Next route validation failed: {exc}",
        }
    finally:
        try:
            script.unlink()
        except OSError:
            pass

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return {
            "passed": False,
            "checks": ["typescript_compile", "route_runtime"],
            "log": _redact_text(output[-1500:], work_dir),
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "passed": False,
            "checks": ["typescript_compile", "route_runtime"],
            "log": _redact_text(output[-1500:], work_dir),
        }
    payload["log"] = _redact_text(str(payload.get("log", "")), work_dir)
    return payload


def _find_typescript_package(start: Path) -> Path | None:
    candidates = [
        start / "node_modules" / "typescript",
        Path.cwd() / "node_modules" / "typescript",
    ]
    cache = os.environ.get("SIMPLICIO_TS_MORPH_CACHE")
    if cache:
        candidates.append(Path(cache) / "node_modules" / "typescript")
    candidates.append(
        Path(tempfile.gettempdir())
        / "simplicio-ts-morph-node"
        / "node_modules"
        / "typescript"
    )
    for candidate in candidates:
        if (candidate / "package.json").is_file():
            return candidate
    return None


def _plan_for_case(case: BenchCase, project_name: str) -> Plan:
    return Plan(
        version="1.0",
        stack=case.stack_slug,
        project_name=project_name,
        rationale=f"Benchmark deterministic executor {case.expected_executor}.",
        files_to_create=[],
        tasks=[case.task],
        deps_to_install=[],
        deps_dev=[],
        test_command=case.task.verify,
        lint_command="",
        estimated_total_tasks=1,
    )


def _summarize(
    rows: list[dict[str, Any]],
    elapsed_s: float,
    llm_baseline: dict[str, Any] | None = None,
    live_corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_cases = len(rows)
    passed_cases = sum(1 for row in rows if row.get("passed"))
    codegen_tasks = sum(
        int(row.get("metrics", {}).get("tasks_codegen", 0)) for row in rows
    )
    llm_tasks = sum(int(row.get("metrics", {}).get("tasks_llm", 0)) for row in rows)
    skipped_tasks = sum(
        int(row.get("metrics", {}).get("tasks_skipped", 0)) for row in rows
    )
    failed_tasks = sum(
        int(row.get("metrics", {}).get("tasks_failed", 0)) for row in rows
    )
    total_tasks = codegen_tasks + llm_tasks + skipped_tasks + failed_tasks
    matched = sum(1 for row in rows if row.get("expected_executor_match"))
    post_validated = sum(
        1
        for row in rows
        if row.get("validation", {}).get("passed")
        and row.get("validation", {}).get("checks")
    )
    post_validation_failed = sum(
        1 for row in rows if not row.get("validation", {}).get("passed", True)
    )
    codegen_durations = [
        int(row.get("duration_ms", 0))
        for row in rows
        if row.get("execution_mode") == "codegen"
    ]
    summary = {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "pass_rate": _ratio(passed_cases, total_cases),
        "expected_executor_match_rate": _ratio(matched, total_cases),
        "total_tasks": total_tasks,
        "tasks_codegen": codegen_tasks,
        "tasks_llm": llm_tasks,
        "tasks_skipped": skipped_tasks,
        "tasks_failed": failed_tasks,
        "codegen_share": _ratio(codegen_tasks, total_tasks),
        "avg_codegen_ms": _avg(codegen_durations),
        "post_validated_cases": post_validated,
        "post_validation_failed_cases": post_validation_failed,
        "elapsed_s": elapsed_s,
        "planner_calls": 0,
        "llm_calls": llm_tasks,
    }
    baseline_avg_ms = int(llm_baseline.get("avg_llm_ms", 0)) if llm_baseline else 0
    if llm_baseline:
        summary["llm_baseline"] = llm_baseline
        summary["executor_pass_rate_ge_llm"] = summary["pass_rate"] >= float(
            llm_baseline["pass_rate"]
        )
        summary["latency_reduction"] = (
            round((baseline_avg_ms - summary["avg_codegen_ms"]) / baseline_avg_ms, 4)
            if baseline_avg_ms > 0
            else None
        )
    else:
        summary["executor_pass_rate_ge_llm"] = None
        summary["latency_reduction"] = None

    if live_corpus:
        summary["live_corpus"] = live_corpus
        live_avg_codegen_ms = int(live_corpus.get("avg_codegen_ms", 0))
        live_pass_rate = float(live_corpus.get("e2e_green_rate", 0.0))
        has_real_baseline = bool(llm_baseline and llm_baseline.get("real_corpus"))
        summary["real_executor_pass_rate_ge_llm"] = (
            live_pass_rate >= float(llm_baseline["pass_rate"])
            if has_real_baseline
            else None
        )
        summary["real_latency_reduction"] = (
            round((baseline_avg_ms - live_avg_codegen_ms) / baseline_avg_ms, 4)
            if has_real_baseline and baseline_avg_ms > 0 and live_avg_codegen_ms > 0
            else None
        )
        summary["live_latency_reduction_vs_task_baseline"] = (
            round((baseline_avg_ms - live_avg_codegen_ms) / baseline_avg_ms, 4)
            if llm_baseline and baseline_avg_ms > 0 and live_avg_codegen_ms > 0
            else None
        )
    else:
        summary["real_executor_pass_rate_ge_llm"] = None
        summary["real_latency_reduction"] = None
        summary["live_latency_reduction_vs_task_baseline"] = None

    summary["release_gates"] = {
        "fifty_runs": total_cases >= 50,
        "mechanical_share_ge_30": summary["codegen_share"] >= 0.30,
        "executor_pass_rate_100": summary["pass_rate"] == 1.0,
        "executor_pass_rate_ge_llm": summary["executor_pass_rate_ge_llm"],
        "typescript_next_route_compiles_and_responds_json": any(
            row.get("name") == "typescript-next-route"
            and row.get("validation", {}).get("passed")
            and {"typescript_compile", "get_json", "post_json"}.issubset(
                set(row.get("validation", {}).get("checks", []))
            )
            for row in rows
        ),
        "llm_baseline_present": llm_baseline is not None,
        "latency_reduction_ge_50": (
            summary["latency_reduction"] >= 0.50
            if summary["latency_reduction"] is not None
            else None
        ),
        "real_50_scratch_corpus": bool(
            live_corpus and int(live_corpus.get("total_runs", 0)) >= 50
        ),
        "real_mechanical_share_ge_30": bool(
            live_corpus and float(live_corpus.get("codegen_share", 0.0)) >= 0.30
        ),
        "real_e2e_green_ge_80": bool(
            live_corpus and float(live_corpus.get("e2e_green_rate", 0.0)) >= 0.80
        ),
        "real_executor_pass_rate_ge_llm": (summary["real_executor_pass_rate_ge_llm"]),
        "real_latency_reduction_ge_50": (
            summary["real_latency_reduction"] >= 0.50
            if summary["real_latency_reduction"] is not None
            else None
        ),
        "zero_feature_regression_live": bool(
            live_corpus
            and int(live_corpus.get("total_runs", 0)) > 0
            and int(live_corpus.get("e2e_green", 0))
            == int(live_corpus.get("total_runs", 0))
            and int(live_corpus.get("tasks_failed", 0)) == 0
        ),
    }
    missing = []
    if llm_baseline is None:
        missing.append("LLM baseline pass-rate and latency comparison")
    if live_corpus is None:
        missing.append("50 real scratch goals across the release corpus")
    elif int(live_corpus.get("total_runs", 0)) < 50:
        missing.append("50 real scratch goals across the release corpus")
    if summary["release_gates"]["real_mechanical_share_ge_30"] is False:
        missing.append(">=30% mechanical task share on real scratch corpus")
    if summary["release_gates"]["real_e2e_green_ge_80"] is False:
        missing.append("real scratch e2e green rate >=80%")
    if summary["release_gates"]["real_executor_pass_rate_ge_llm"] is not True:
        missing.append("real scratch LLM baseline for executor pass-rate comparison")
    if summary["release_gates"]["real_latency_reduction_ge_50"] is not True:
        missing.append("real scratch LLM baseline for task latency comparison")
    if summary["release_gates"]["zero_feature_regression_live"] is False:
        missing.append("zero feature regression evidence from live scratch corpus")
    summary["missing_release_evidence"] = missing
    return summary


def _summarize_llm_baseline(
    rows: list[dict[str, Any]],
    elapsed_s: float,
    model: str,
) -> dict[str, Any]:
    total_cases = len(rows)
    passed_cases = sum(1 for row in rows if row.get("passed"))
    durations = [
        int(row.get("duration_ms", 0))
        for row in rows
        if int(row.get("duration_ms", 0)) > 0
    ]
    avg_llm_ms = max(1, _avg(durations)) if total_cases else 0
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "pass_rate": _ratio(passed_cases, total_cases),
        "avg_llm_ms": avg_llm_ms,
        "elapsed_s": elapsed_s,
        "model": model,
        "release_gates": {
            "baseline_present": total_cases > 0,
            "baseline_has_successful_cases": passed_cases > 0,
            "baseline_latency_measured": bool(durations),
        },
    }


def load_llm_baseline(path: Path) -> dict[str, Any]:
    """Load a captured LLM baseline summary for executor-vs-LLM comparison."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_llm_baseline(data, source=str(path))


def load_live_gate_evidence(path: Path) -> dict[str, Any]:
    """Load live scratch-gate evidence for release-corpus codegen metrics."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_live_gate(data, source=_source_label(path))


def load_real_llm_baseline_from_live_gate(path: Path) -> dict[str, Any]:
    """Load a codegen-disabled live gate as the real scratch LLM baseline."""
    data = json.loads(path.read_text(encoding="utf-8"))
    matrix = data.get("matrix") if isinstance(data, dict) else {}
    matrix = matrix if isinstance(matrix, dict) else {}
    if not matrix.get("disable_codegen"):
        raise ValueError(
            "real LLM baseline live gate must be captured with --disable-codegen"
        )
    if matrix.get("plan_only"):
        raise ValueError("real LLM baseline live gate cannot be plan-only")
    if not matrix.get("post_verify"):
        raise ValueError("real LLM baseline live gate must use --post-verify")

    live = _normalize_live_gate(data, source=_source_label(path))
    raw_runs = data.get("runs") if isinstance(data, dict) else []
    observed_runs = len(raw_runs) if isinstance(raw_runs, list) else 0
    total_runs = int(live.get("total_runs", 0))
    total_cases = min(total_runs, observed_runs) if total_runs else observed_runs
    avg_llm_ms = int(live.get("avg_llm_ms", 0))
    if total_cases <= 0:
        raise ValueError("real LLM baseline live gate must include at least one run")
    if avg_llm_ms <= 0:
        raise ValueError("real LLM baseline live gate must include avg_llm_ms")
    return {
        "source": f"{_source_label(path)} (--disable-codegen live gate)",
        "total_cases": total_cases,
        "pass_rate": float(live.get("e2e_green_rate", 0.0)),
        "avg_llm_ms": avg_llm_ms,
        "real_corpus": (
            total_cases >= 50
            and not bool(matrix.get("skip_install"))
            and bool(matrix.get("post_verify"))
        ),
    }


def _normalize_llm_baseline(
    baseline: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    summary = baseline.get("summary")
    values = summary if isinstance(summary, dict) else baseline
    pass_rate = values.get("pass_rate", values.get("llm_pass_rate"))
    avg_ms = values.get(
        "avg_llm_ms",
        values.get("avg_task_ms", values.get("average_latency_ms")),
    )
    raw_cases = values.get("cases", baseline.get("cases", []))
    total_cases = values.get("total_cases")
    if total_cases is None:
        total_cases = len(raw_cases) if isinstance(raw_cases, list) else raw_cases
    if pass_rate is None or avg_ms is None:
        raise ValueError("LLM baseline must include pass_rate and avg_llm_ms")
    normalized = {
        "source": baseline.get("source") or source or "inline",
        "total_cases": int(total_cases or 0),
        "pass_rate": float(pass_rate),
        "avg_llm_ms": int(avg_ms),
        "real_corpus": bool(
            values.get("real_corpus")
            or values.get("real_50_scratch_corpus")
            or baseline.get("real_corpus")
            or baseline.get("real_50_scratch_corpus")
        ),
    }
    if not 0 <= normalized["pass_rate"] <= 1:
        raise ValueError("LLM baseline pass_rate must be between 0 and 1")
    if normalized["avg_llm_ms"] <= 0:
        raise ValueError("LLM baseline avg_llm_ms must be > 0")
    return normalized


def _normalize_live_gate(
    live_gate: dict[str, Any],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    if "summary" not in live_gate and "runs" not in live_gate:
        return {
            "source": live_gate.get("source") or source or "inline",
            "total_runs": int(live_gate.get("total_runs", 0)),
            "e2e_green": int(live_gate.get("e2e_green", 0)),
            "e2e_green_rate": float(live_gate.get("e2e_green_rate", 0.0)),
            "tasks_total": int(live_gate.get("tasks_total", 0)),
            "tasks_codegen": int(live_gate.get("tasks_codegen", 0)),
            "tasks_llm": int(live_gate.get("tasks_llm", 0)),
            "tasks_failed": int(live_gate.get("tasks_failed", 0)),
            "codegen_share": float(live_gate.get("codegen_share", 0.0)),
            "avg_codegen_ms": int(live_gate.get("avg_codegen_ms", 0)),
            "avg_llm_ms": int(live_gate.get("avg_llm_ms", 0)),
            "stacks": sorted(live_gate.get("stacks", [])),
            "full_75_run_matrix": bool(live_gate.get("full_75_run_matrix", False)),
            "e2e_green_ge_80": bool(live_gate.get("e2e_green_ge_80", False)),
        }

    summary = live_gate.get("summary") if isinstance(live_gate, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    runs = live_gate.get("runs") if isinstance(live_gate, dict) else []
    runs = runs if isinstance(runs, list) else []

    total_runs = int(summary.get("total_runs") or len(runs))
    e2e_green = int(
        summary.get("e2e_green")
        if summary.get("e2e_green") is not None
        else sum(1 for row in runs if row.get("e2e_green"))
    )
    tasks_total = 0
    tasks_codegen = 0
    tasks_llm = 0
    tasks_failed = 0
    weighted_codegen_ms = 0
    weighted_llm_ms = 0
    stacks: set[str] = set()

    for row in runs:
        if isinstance(row.get("stack"), str):
            stacks.add(row["stack"])
        metrics = row.get("scratch_metrics")
        if not isinstance(metrics, dict):
            continue
        row_total = int(metrics.get("tasks_total", 0) or 0)
        row_codegen = int(metrics.get("tasks_codegen", 0) or 0)
        row_llm = int(metrics.get("tasks_llm", 0) or 0)
        row_failed = int(metrics.get("tasks_failed", 0) or 0)
        avg_codegen = int(metrics.get("avg_codegen_ms", 0) or 0)
        avg_llm = int(metrics.get("avg_llm_ms", 0) or 0)
        tasks_total += row_total
        tasks_codegen += row_codegen
        tasks_llm += row_llm
        tasks_failed += row_failed
        weighted_codegen_ms += avg_codegen * row_codegen
        weighted_llm_ms += avg_llm * row_llm

    gates = summary.get("release_gates") if isinstance(summary, dict) else {}
    gates = gates if isinstance(gates, dict) else {}
    codegen_share = _ratio(tasks_codegen, tasks_total)
    e2e_green_rate = (
        float(summary.get("e2e_green_rate"))
        if summary.get("e2e_green_rate") is not None
        else _ratio(e2e_green, total_runs)
    )
    return {
        "source": live_gate.get("source") or source or "inline",
        "total_runs": total_runs,
        "e2e_green": e2e_green,
        "e2e_green_rate": e2e_green_rate,
        "tasks_total": tasks_total,
        "tasks_codegen": tasks_codegen,
        "tasks_llm": tasks_llm,
        "tasks_failed": tasks_failed,
        "codegen_share": codegen_share,
        "avg_codegen_ms": (
            round(weighted_codegen_ms / tasks_codegen) if tasks_codegen else 0
        ),
        "avg_llm_ms": round(weighted_llm_ms / tasks_llm) if tasks_llm else 0,
        "stacks": sorted(stacks),
        "full_75_run_matrix": bool(gates.get("full_75_run_matrix", False)),
        "e2e_green_ge_80": bool(gates.get("e2e_green_ge_80", False)),
    }


def write_llm_baseline(result: dict[str, Any], json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def _source_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: list[int]) -> int:
    return round(sum(values) / len(values)) if values else 0


def _redact_path(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return _redact_text(str(path), root)
    return "$WORK_DIR/" + rel.as_posix()


def _redact_text(text: str, root: Path) -> str:
    root_text = str(root)
    return text.replace(root_text, "$WORK_DIR").replace(
        root_text.replace("\\", "/"),
        "$WORK_DIR",
    )


_NEXT_ROUTE_VALIDATOR_SCRIPT = r"""
const fs = require("fs");
const moduleApi = require("module");
const path = require("path");
const ts = require(process.argv[3]);

const routePath = process.argv[2];
const checks = [];

function fail(message) {
  console.error(message);
  process.exit(1);
}

const compilerOptions = {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.CommonJS,
  strict: true,
  esModuleInterop: true,
  skipLibCheck: true,
  moduleResolution: ts.ModuleResolutionKind.Node10,
  lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
};
const program = ts.createProgram([routePath], compilerOptions);
const diagnostics = ts.getPreEmitDiagnostics(program)
  .filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error);
if (diagnostics.length) {
  const formatted = ts.formatDiagnosticsWithColorAndContext(diagnostics, {
    getCanonicalFileName: (fileName) => fileName,
    getCurrentDirectory: () => process.cwd(),
    getNewLine: () => "\n",
  });
  fail(`TypeScript compile failed:\n${formatted}`);
}
checks.push("typescript_compile");

const source = fs.readFileSync(routePath, "utf8");
const compiled = ts.transpileModule(source, { compilerOptions }).outputText;
const routeModule = { exports: {} };
const routeRequire = moduleApi.createRequire(path.resolve(routePath));
const wrapper = new Function(
  "exports",
  "require",
  "module",
  "__filename",
  "__dirname",
  compiled,
);
wrapper(
  routeModule.exports,
  routeRequire,
  routeModule,
  routePath,
  path.dirname(routePath),
);

async function main() {
  if (typeof Response !== "function" || typeof Request !== "function") {
    fail("Node runtime does not expose Request/Response globals");
  }
  if (typeof routeModule.exports.GET !== "function") {
    fail("generated route does not export GET");
  }
  const getResponse = await routeModule.exports.GET();
  if (!(getResponse instanceof Response) || getResponse.status !== 200) {
    fail("GET did not return a 200 Response");
  }
  const getJson = await getResponse.json();
  if (!Array.isArray(getJson)) {
    fail("GET did not return a JSON array");
  }
  checks.push("get_json");

  if (typeof routeModule.exports.POST !== "function") {
    fail("generated route does not export POST");
  }
  const postRequest = new Request("http://localhost/api/units", {
    method: "POST",
    body: JSON.stringify({ name: "Apt 101" }),
    headers: { "content-type": "application/json" },
  });
  const postResponse = await routeModule.exports.POST(postRequest);
  if (!(postResponse instanceof Response) || postResponse.status !== 201) {
    fail("POST did not return a 201 Response");
  }
  const postJson = await postResponse.json();
  if (!postJson || postJson.name !== "Apt 101") {
    fail("POST did not echo a JSON object");
  }
  checks.push("post_json");

  console.log(JSON.stringify({
    passed: true,
    checks,
    log: "generated route compiled and returned JSON from GET/POST",
  }));
}

main().catch((error) => fail(error && error.stack ? error.stack : String(error)));
"""


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def _to_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Scratch Codegen Benchmark",
        "",
        result["scope"],
        "",
        "## Summary",
        "",
        f"- cases: {summary['passed_cases']}/{summary['total_cases']} passed",
        f"- codegen share: {summary['codegen_share']:.2%}",
        f"- expected executor match: {summary['expected_executor_match_rate']:.2%}",
        f"- avg codegen latency: {summary['avg_codegen_ms']} ms",
        f"- post-validated cases: {summary['post_validated_cases']}",
        f"- post-validation failures: {summary['post_validation_failed_cases']}",
        f"- planner calls: {summary['planner_calls']}",
        f"- llm calls: {summary['llm_calls']}",
        "",
        "## Release Gate Status",
        "",
    ]
    for gate, value in summary["release_gates"].items():
        lines.append(f"- {gate}: {value}")
    baseline = summary.get("llm_baseline")
    if baseline:
        lines.extend(
            [
                "",
                "## LLM Baseline",
                "",
                f"- source: {baseline['source']}",
                f"- cases: {baseline['total_cases']}",
                f"- pass rate: {baseline['pass_rate']:.2%}",
                f"- avg LLM latency: {baseline['avg_llm_ms']} ms",
                f"- executor pass-rate >= LLM: {summary['executor_pass_rate_ge_llm']}",
                f"- latency reduction: {summary['latency_reduction']:.2%}",
            ]
        )
    live = summary.get("live_corpus")
    if live:
        lines.extend(
            [
                "",
                "## Live Scratch Corpus",
                "",
                f"- source: {live['source']}",
                f"- runs: {live['e2e_green']}/{live['total_runs']} e2e green",
                f"- tasks: {live['tasks_codegen']}/{live['tasks_total']} codegen",
                f"- task-level LLM calls: {live['tasks_llm']}",
                f"- codegen share: {live['codegen_share']:.2%}",
                f"- avg live codegen latency: {live['avg_codegen_ms']} ms",
                f"- stacks: {', '.join(live['stacks'])}",
            ]
        )
        if summary.get("real_latency_reduction") is not None:
            lines.append(
                f"- live latency reduction vs LLM baseline: {summary['real_latency_reduction']:.2%}"
            )
        elif summary.get("live_latency_reduction_vs_task_baseline") is not None:
            lines.append(
                "- live latency reduction vs task-level LLM baseline: "
                f"{summary['live_latency_reduction_vs_task_baseline']:.2%}"
            )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| case | stack | executor | mode | post-validation | passed | duration_ms |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for row in result["cases"]:
        validation = row.get("validation", {})
        validation_text = ",".join(validation.get("checks", [])) or "-"
        lines.append(
            "| {name} r{run_index:02d} | {stack} | {executor} | {mode} | {validation} | {passed} | {duration} |".format(
                name=row["name"],
                run_index=row["run_index"],
                stack=row["stack"],
                executor=row.get("actual_executor") or "",
                mode=row.get("execution_mode") or "",
                validation=validation_text,
                passed=row.get("passed"),
                duration=row.get("duration_ms", 0),
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument(
        "--no-typescript",
        action="store_true",
        help="Skip the Next.js ts-morph executor case.",
    )
    parser.add_argument(
        "--llm-baseline-json",
        type=Path,
        help=(
            "Path to a captured LLM baseline JSON with summary.pass_rate and "
            "summary.avg_llm_ms for executor-vs-LLM gate comparison."
        ),
    )
    parser.add_argument(
        "--capture-llm-baseline-json",
        type=Path,
        help=(
            "Capture an equivalent LLM baseline with mechanical executors "
            "disabled, write it to this JSON path, then compare against it."
        ),
    )
    parser.add_argument(
        "--real-llm-baseline-live-gate-json",
        type=Path,
        help=(
            "Path to a scratch live-gate JSON captured with --disable-codegen "
            "and --post-verify; used as the real release-corpus LLM baseline."
        ),
    )
    parser.add_argument(
        "--live-gate-json",
        type=Path,
        default=LIVE_GATE_JSON,
        help=(
            "Path to scratch live-gate JSON used to prove real 50+ scratch "
            "mechanical-executor release metrics. If absent, this evidence is omitted."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    baseline_args = [
        args.llm_baseline_json,
        args.capture_llm_baseline_json,
        args.real_llm_baseline_live_gate_json,
    ]
    if sum(1 for value in baseline_args if value) > 1:
        print(
            "choose only one LLM baseline input",
            file=sys.stderr,
        )
        return 2

    llm_baseline = None
    work_dir = args.work_dir
    if args.capture_llm_baseline_json:
        baseline_work_dir = work_dir / "llm-baseline" if work_dir else None
        codegen_work_dir = work_dir / "codegen" if work_dir else None
        try:
            captured = capture_llm_baseline(
                work_dir=baseline_work_dir,
                repeat=args.repeat,
                include_typescript=not args.no_typescript,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        write_llm_baseline(captured, args.capture_llm_baseline_json)
        llm_baseline = captured
        work_dir = codegen_work_dir
    elif args.llm_baseline_json:
        llm_baseline = load_llm_baseline(args.llm_baseline_json)
    elif args.real_llm_baseline_live_gate_json:
        try:
            llm_baseline = load_real_llm_baseline_from_live_gate(
                args.real_llm_baseline_live_gate_json
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    live_gate = None
    if args.live_gate_json and args.live_gate_json.is_file():
        live_gate = load_live_gate_evidence(args.live_gate_json)

    result = run_benchmark(
        work_dir=work_dir,
        repeat=args.repeat,
        include_typescript=not args.no_typescript,
        llm_baseline=llm_baseline,
        live_gate=live_gate,
    )
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    return 0 if result["summary"]["failed_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
