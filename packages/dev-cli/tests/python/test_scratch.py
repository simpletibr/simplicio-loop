"""Unit tests for simplicio.scratch — schema, registry, executor stub mode."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from simplicio.scratch.plan_schema import (
    EXAMPLE_PLAN,
    PlanValidationError,
    Task,
    validate_plan,
)
from simplicio.scratch.stack_registry import Stack, StackRegistry, slugify_project

# ----- plan_schema ----- #


def test_example_plan_validates() -> None:
    plan = validate_plan(
        {
            **EXAMPLE_PLAN,
            "tasks": [
                {
                    "id": "T01-unsupported",
                    "depends_on": [],
                    "goal": "Summarize quarterly revenue from an external source",
                    "target": "src/reports/summary.py",
                    "criteria": "- requires project-specific business logic",
                    "constraints": "- no deterministic executor applies",
                    "verify": "pytest tests/reports/test_summary.py",
                }
            ],
            "estimated_total_tasks": 1,
        }
    )
    assert plan.project_name == "condo-mgmt"
    assert plan.estimated_total_tasks == len(plan.tasks)


def test_rejects_bad_project_slug() -> None:
    bad = {**EXAMPLE_PLAN, "project_name": "Bad-CASE"}
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(bad)
    assert any("project_name" in e for e in exc.value.errors)


def test_rejects_missing_required_field() -> None:
    bad = {k: v for k, v in EXAMPLE_PLAN.items() if k != "tasks"}
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(bad)
    assert any("tasks missing" in e for e in exc.value.errors)


def test_rejects_estimated_count_mismatch() -> None:
    bad = {**EXAMPLE_PLAN, "estimated_total_tasks": 42}
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(bad)
    assert any("estimated_total_tasks" in e for e in exc.value.errors)


def test_rejects_unknown_depends_on() -> None:
    bad = {
        **EXAMPLE_PLAN,
        "tasks": [{**EXAMPLE_PLAN["tasks"][0], "depends_on": ["T99-ghost"]}],
    }
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(bad)
    assert any("ghost" in e for e in exc.value.errors)


def test_rejects_duplicate_task_id() -> None:
    bad = {
        **EXAMPLE_PLAN,
        "tasks": [EXAMPLE_PLAN["tasks"][0], EXAMPLE_PLAN["tasks"][0]],
        "estimated_total_tasks": 2,
    }
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(bad)
    assert any("duplicated" in e for e in exc.value.errors)


def test_accepts_optional_required_skill_on_task() -> None:
    raw = {
        **EXAMPLE_PLAN,
        "tasks": [
            {
                **EXAMPLE_PLAN["tasks"][0],
                "required_skill": "Create Liquibase migrations safely",
            }
        ],
    }

    plan = validate_plan(raw)

    assert plan.tasks[0].required_skill == "Create Liquibase migrations safely"


def test_rejects_non_string_required_skill() -> None:
    raw = {
        **EXAMPLE_PLAN,
        "tasks": [
            {
                **EXAMPLE_PLAN["tasks"][0],
                "required_skill": ["liquibase"],
            }
        ],
    }

    with pytest.raises(PlanValidationError) as exc:
        validate_plan(raw)

    assert any("required_skill" in e for e in exc.value.errors)


# ----- stack_registry ----- #


def test_registry_lists_pilot_stacks() -> None:
    reg = StackRegistry()
    slugs = {s.slug for s in reg.list()}
    assert {
        "bash-cli",
        "csharp-aspnet",
        "csharp-blazor",
        "dart-flutter",
        "elixir-phoenix",
        "java-spring",
        "go-gin",
        "go-cli",
        "go-echo",
        "js-express",
        "kotlin-android",
        "kotlin-ktor",
        "kotlin-spring",
        "php-laravel",
        "php-symfony",
        "php-vanilla",
        "py-cli",
        "py-django",
        "py-fastapi",
        "py-flask",
        "react-vite",
        "rust-axum",
        "rust-cli",
        "rust-leptos",
        "swift-ios",
        "swift-vapor",
        "ts-nextjs",
        "ts-nestjs",
        "ts-remix",
        "ruby-rails",
    } <= slugs


def test_registry_loads_full_metadata() -> None:
    reg = StackRegistry()
    py = reg.get("py-fastapi")
    assert py is not None
    assert py.language.startswith("Python")
    assert py.test_command == "pytest -q"
    assert py.install_command == "python3 -m pip install -e .[dev]"
    assert py.readme.startswith("# py-fastapi")
    assert "best practices" in py.practices.lower()


def test_registry_filters_by_tag() -> None:
    reg = StackRegistry()
    web_stacks = {s.slug for s in reg.by_tags(["web"])}
    assert "js-express" in web_stacks
    assert "py-django" in web_stacks
    assert "py-fastapi" in web_stacks
    assert "py-flask" in web_stacks
    assert "react-vite" in web_stacks
    assert "ts-nextjs" in web_stacks
    assert "go-gin" in web_stacks
    assert "rust-axum" in web_stacks
    assert "php-laravel" in web_stacks


@pytest.mark.parametrize(
    ("slug", "language", "framework", "test_command"),
    [
        ("js-express", "JavaScript", "Express", "npm test"),
        ("bash-cli", "Bash", "shellcheck", "bats test"),
        ("csharp-aspnet", "C#", "ASP.NET Core", "dotnet test"),
        ("csharp-blazor", "C#", "Blazor", "dotnet test"),
        ("dart-flutter", "Dart", "Flutter", "flutter test"),
        ("elixir-phoenix", "Elixir", "Phoenix", "mix test"),
        ("go-cli", "Go", "Cobra", "go test ./..."),
        ("go-echo", "Go", "Echo", "go test ./..."),
        ("java-spring", "Java", "Spring Boot", "./gradlew test"),
        ("kotlin-android", "Kotlin", "Jetpack Compose", "./gradlew test"),
        ("kotlin-ktor", "Kotlin", "Ktor", "./gradlew test"),
        ("kotlin-spring", "Kotlin", "Spring Boot", "./gradlew test"),
        ("php-symfony", "PHP", "Symfony", "vendor/bin/phpunit"),
        (
            "php-vanilla",
            "PHP",
            "Composer",
            "vendor/bin/phpunit --configuration phpunit.xml",
        ),
        ("py-cli", "Python", "Typer", "pytest -q"),
        ("py-django", "Python", "Django", "python manage.py test"),
        ("py-flask", "Python", "Flask", "pytest -q"),
        ("react-vite", "TypeScript", "React", "npm test"),
        ("ruby-rails", "Ruby", "Rails", "bin/rails test"),
        ("rust-cli", "Rust", "Clap", "cargo test"),
        ("rust-leptos", "Rust", "Leptos", "cargo test"),
        ("swift-ios", "Swift", "SwiftUI", "xcodebuild test"),
        ("swift-vapor", "Swift", "Vapor", "swift test"),
        ("ts-nestjs", "TypeScript", "NestJS", "npm test"),
        ("ts-remix", "TypeScript", "Remix", "npm test"),
    ],
)
def test_registry_loads_expansion_stack_metadata(
    slug: str,
    language: str,
    framework: str,
    test_command: str,
) -> None:
    reg = StackRegistry()
    stack = reg.get(slug)

    assert stack is not None
    assert stack.language.startswith(language)
    assert stack.framework.startswith(framework)
    assert stack.test_command == test_command
    assert "best practices" in stack.practices.lower()


@pytest.mark.parametrize(
    "slug",
    [
        "bash-cli",
        "csharp-aspnet",
        "csharp-blazor",
        "dart-flutter",
        "elixir-phoenix",
        "go-cli",
        "go-echo",
        "java-spring",
        "js-express",
        "kotlin-android",
        "kotlin-ktor",
        "kotlin-spring",
        "php-symfony",
        "php-vanilla",
        "py-cli",
        "py-django",
        "py-flask",
        "react-vite",
        "ruby-rails",
        "rust-cli",
        "rust-leptos",
        "swift-ios",
        "swift-vapor",
        "ts-nestjs",
        "ts-remix",
    ],
)
def test_expansion_stacks_render_minimal_project(slug: str) -> None:
    reg = StackRegistry()
    stack = reg.get(slug)
    assert stack is not None

    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "out"
        written = stack.render_tree(
            dest,
            {"project_name": "demo-app", "goal": "Demo goal"},
        )

        assert written
        assert (dest / "README.md").is_file()
        assert "demo-app" in (dest / "README.md").read_text(encoding="utf-8")


def test_registry_loads_go_gin_stack_metadata() -> None:
    reg = StackRegistry()
    stack = reg.get("go-gin")
    assert stack is not None
    assert stack.language.startswith("Go")
    assert stack.framework == "Gin"
    assert stack.install_command == "go mod tidy"
    assert stack.test_command == "go test ./..."
    assert "best practices" in stack.practices.lower()


def test_registry_loads_rust_axum_stack_metadata() -> None:
    reg = StackRegistry()
    stack = reg.get("rust-axum")
    assert stack is not None
    assert stack.language.startswith("Rust")
    assert stack.framework == "Axum"
    assert stack.install_command == "cargo fetch"
    assert stack.test_command == "cargo test"
    assert "best practices" in stack.practices.lower()


def test_registry_loads_php_laravel_stack_metadata() -> None:
    reg = StackRegistry()
    stack = reg.get("php-laravel")
    assert stack is not None
    assert stack.language.startswith("PHP")
    assert stack.framework == "Laravel"
    assert stack.install_command == "composer install"
    assert stack.test_command == "php vendor/bin/phpunit --configuration phpunit.xml"
    assert "best practices" in stack.practices.lower()


def test_rust_axum_stack_renders_cargo_project_name() -> None:
    reg = StackRegistry()
    stack = reg.get("rust-axum")
    assert stack is not None

    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "out"
        written = stack.render_tree(dest, {"project_name": "demo-api"})

        assert (dest / "Cargo.toml").is_file()
        assert (dest / "src/main.rs").is_file()
        assert (dest / "Cargo.toml").read_text(encoding="utf-8").startswith('[package]\nname = "demo-api"')
        assert any(path.name == "main.rs" for path in written)


def test_php_laravel_stack_renders_composer_project_name() -> None:
    reg = StackRegistry()
    stack = reg.get("php-laravel")
    assert stack is not None

    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "out"
        written = stack.render_tree(dest, {"project_name": "demo-api"})

        assert (dest / "composer.json").is_file()
        assert (dest / "routes/api.php").is_file()
        assert (dest / "bootstrap/cache").is_dir()
        assert '"name": "simplicio/demo-api"' in (dest / "composer.json").read_text(encoding="utf-8")
        with (dest / "routes/api.php").open(encoding="utf-8", newline="") as fh:
            assert "\r\n" not in fh.read()
        assert any(path.name == "HealthTest.php" for path in written)


def test_stack_render_tree_ignores_tool_cache_dirs() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "stack"
        tree = root / "tree"
        (tree / ".ruff_cache" / "0.15.13").mkdir(parents=True)
        (tree / ".ruff_cache" / "0.15.13" / "cache").write_bytes(b"\xff\xfe")
        (tree / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        (tree / "README.md").write_text("# {project_name}\n", encoding="utf-8")

        dest = Path(td) / "out"
        stack = Stack(slug="test", path=root)
        written = stack.render_tree(dest, {"project_name": "demo"})

        assert sorted(p.relative_to(dest).as_posix() for p in written) == [
            ".gitignore",
            "README.md",
        ]
        assert (dest / "README.md").read_text(encoding="utf-8") == "# demo\n"
        assert not (dest / ".ruff_cache").exists()


def test_slugify_project_normalizes_name() -> None:
    assert slugify_project("Condo Mgmt App!") == "condo-mgmt-app"
    assert slugify_project("  ") == "scratch-project"
    assert slugify_project("123-num-only").startswith("p-")  # must start with letter


def test_generate_plan_passes_stack_template_version(monkeypatch) -> None:
    from simplicio.scratch import planner as planner_module

    seen = {}
    stack = Stack(
        slug="custom-stack",
        path=Path("."),
        meta={
            "language": "Python",
            "framework": "FastAPI",
            "template_version": "stack-v1",
        },
        readme="Custom stack readme",
        practices="Custom stack practices",
        verify={"test_runner": "pytest"},
    )
    plan_payload = {
        **EXAMPLE_PLAN,
        "stack": "custom-stack",
        "project_name": "cached-plan",
    }

    def fake_planner_complete(prompt, **kwargs):
        seen["prompt"] = prompt
        seen.update(kwargs)
        return json.dumps(plan_payload)

    monkeypatch.setattr(planner_module, "planner_complete", fake_planner_complete)

    plan = planner_module.generate_plan(
        stack,
        "Build a uniquely named planner-cache fixture",
        "cached-plan",
    )

    assert plan.project_name == "cached-plan"
    assert seen["template_version"] == "stack-v1"


# ----- executor stub mode ----- #


def test_executor_scaffolds_tree_in_stub_mode() -> None:
    """Without SIMPLICIO_MODEL, unsupported tasks are recorded as skipped after
    scaffolding. Deterministic codegen tasks may still pass without an LLM."""
    reg = StackRegistry()
    stack = reg.get("py-fastapi")
    assert stack is not None
    plan = validate_plan(
        {
            **EXAMPLE_PLAN,
            "tasks": [
                {
                    "id": "T01-unsupported",
                    "depends_on": [],
                    "goal": "Summarize quarterly revenue from an external source",
                    "target": "src/reports/summary.py",
                    "criteria": "- requires project-specific business logic",
                    "constraints": "- no deterministic executor applies",
                    "verify": "pytest tests/reports/test_summary.py",
                }
            ],
            "estimated_total_tasks": 1,
        }
    )

    # ensure no SIMPLICIO_MODEL leak from the test runner
    prev = os.environ.pop("SIMPLICIO_MODEL", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            from simplicio.scratch.executor import execute_plan

            report = execute_plan(plan, stack, Path(td), skip_install=True)
            assert report.project_dir.exists()
            assert report.project_dir.name == "condo-mgmt"
            assert report.files_written
            assert (report.project_dir / ".simplicio-loop" / "plan.json").is_file()
            assert (report.project_dir / "pyproject.toml").is_file()
            # tasks in stub mode are recorded but not passed
            assert report.tasks_total == 1
            assert report.tasks_passed == 0
            assert report.metrics["tasks_skipped"] == 1
            assert report.metrics["codegen_share"] == 0.0
            assert report.task_results[0].skipped_reason is not None
    finally:
        if prev is not None:
            os.environ["SIMPLICIO_MODEL"] = prev


def test_executor_report_records_codegen_metrics() -> None:
    reg = StackRegistry()
    stack = reg.get("ts-nextjs")
    assert stack is not None
    plan = validate_plan(
        {
            **EXAMPLE_PLAN,
            "stack": "ts-nextjs",
            "project_name": "next-api",
            "tasks": [
                {
                    "id": "T01-next-route",
                    "depends_on": [],
                    "goal": "Create Next.js route handlers for Unit CRUD",
                    "target": "src/app/api/units/route.ts",
                    "criteria": "- exports GET and POST handlers\n- returns JSON",
                    "constraints": "- use deterministic codegen",
                    "verify": "pnpm vitest run",
                }
            ],
            "estimated_total_tasks": 1,
        }
    )

    with tempfile.TemporaryDirectory() as td:
        from simplicio.scratch.executor import execute_plan

        report = execute_plan(plan, stack, Path(td), skip_install=True)
        data = report.to_dict()

        assert report.metrics["tasks_codegen"] == 1
        assert report.metrics["codegen_share"] == 1.0
        assert report.metrics["lines_generated_total"] > 0
        assert report.metrics["files_created_total"] >= 1
        assert data["tasks"][0]["execution_mode"] == "codegen"
        assert data["tasks"][0]["codegen_executor"] == "typescript-add-next-route"
        assert data["tasks"][0]["line_stats"]["lines_generated"] > 0
        assert data["tasks"][0]["file_line_stats"]
        assert (report.project_dir / "src/app/api/units/route.ts").is_file()


def test_executor_line_diff_counts_created_changed_and_deleted_files() -> None:
    from simplicio.scratch.executor import _line_diff

    before = {
        "existing.py": ["old", "same"],
        "deleted.py": ["gone", "gone too"],
    }
    after = {
        "existing.py": ["new", "same", "extra"],
        "created.py": ["one", "two"],
    }

    totals, rows = _line_diff(before, after)

    assert totals["files_created"] == 1
    assert totals["files_changed"] == 2
    assert totals["files_deleted"] == 1
    assert totals["lines_generated"] == 2
    assert totals["lines_modified"] == 5
    assert totals["lines_added"] == 4
    assert totals["lines_removed"] == 3
    assert {row["path"] for row in rows} == {
        "existing.py",
        "created.py",
        "deleted.py",
    }
    assert [row for row in rows if row["path"] == "deleted.py"][0]["deleted"] is True


def test_executor_runs_ts_nextjs_crud_recipe_without_llm(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    reg = StackRegistry()
    stack = reg.get("ts-nextjs")
    assert stack is not None

    from simplicio.scratch.executor import execute_plan
    from simplicio.scratch.planner import generate_plan

    plan = generate_plan(
        stack,
        "CRUD app for condo units with owner contact search",
        "next-crud",
    )

    with tempfile.TemporaryDirectory() as td:
        report = execute_plan(plan, stack, Path(td), skip_install=True)

        assert report.tasks_total == 2
        assert report.tasks_passed == 2
        assert report.metrics["tasks_codegen"] == 2
        assert report.metrics["tasks_skipped"] == 0
        assert {task.codegen_executor for task in report.task_results} == {
            "typescript-add-next-route",
            "typescript-add-next-page",
        }
        assert (report.project_dir / "src/app/api/condo_units/route.ts").is_file()
        assert (report.project_dir / "src/app/condo_units/page.tsx").is_file()


def test_executor_runs_rust_axum_crud_recipe_without_llm(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    reg = StackRegistry()
    stack = reg.get("rust-axum")
    assert stack is not None

    from simplicio.scratch.executor import execute_plan
    from simplicio.scratch.planner import generate_plan

    plan = generate_plan(
        stack,
        "CRUD app for condo units with owner contact search",
        "rust-crud",
    )

    with tempfile.TemporaryDirectory() as td:
        report = execute_plan(plan, stack, Path(td), skip_install=True)

        assert report.tasks_total == 1
        assert report.tasks_passed == 1
        assert report.metrics["tasks_codegen"] == 1
        assert report.task_results[0].codegen_executor == "rust-axum-crud"
        assert (report.project_dir / "src/main.rs").is_file()


def test_executor_runs_go_gin_crud_recipe_without_llm(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    reg = StackRegistry()
    stack = reg.get("go-gin")
    assert stack is not None

    from simplicio.scratch.executor import execute_plan
    from simplicio.scratch.planner import generate_plan

    plan = generate_plan(
        stack,
        "CRUD app for condo units with owner contact search",
        "go-crud",
    )

    with tempfile.TemporaryDirectory() as td:
        report = execute_plan(plan, stack, Path(td), skip_install=True)

        assert report.tasks_total == 1
        assert report.tasks_passed == 1
        assert report.metrics["tasks_codegen"] == 1
        assert report.task_results[0].codegen_executor == "go-gin-crud"
        assert (report.project_dir / "internal/http/router.go").is_file()


def test_executor_runs_php_laravel_crud_recipe_without_llm(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    reg = StackRegistry()
    stack = reg.get("php-laravel")
    assert stack is not None

    from simplicio.scratch.executor import execute_plan
    from simplicio.scratch.planner import generate_plan

    plan = generate_plan(
        stack,
        "CRUD app for condo units with owner contact search",
        "laravel-crud",
    )

    with tempfile.TemporaryDirectory() as td:
        report = execute_plan(plan, stack, Path(td), skip_install=True)

        assert report.tasks_total == 1
        assert report.tasks_passed == 1
        assert report.metrics["tasks_codegen"] == 1
        assert report.task_results[0].codegen_executor == "php-laravel-crud-routes"
        assert (report.project_dir / "routes/api.php").is_file()


def test_pipeline_adapter_runs_llm_pipeline_inside_project_dir(
    tmp_path,
    monkeypatch,
) -> None:
    from simplicio import pipeline
    from simplicio.scratch import _pipeline_adapter

    outer = tmp_path / "outer"
    project_dir = tmp_path / "project"
    outer.mkdir()
    project_dir.mkdir()
    monkeypatch.chdir(outer)
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest old")
    git_inits = []

    def fake_pipeline_run(**kwargs):
        assert Path.cwd() == project_dir
        Path("cwd_marker.txt").write_text("ok", encoding="utf-8")
        assert kwargs["root"] == str(project_dir)
        return {"applied": True}

    def fake_git_init(cmd, **kwargs):
        git_inits.append((cmd, kwargs["cwd"]))

    monkeypatch.setattr(pipeline, "run", fake_pipeline_run)
    monkeypatch.setattr(_pipeline_adapter.subprocess, "run", fake_git_init)
    task = Task(
        id="T01",
        goal="create file",
        target="src/app.py",
        criteria="- marker",
        constraints="- stay in project",
        verify="pytest new",
    )
    stack = Stack(
        slug="py-fastapi",
        path=project_dir,
        meta={"language": "Python", "framework": "FastAPI"},
    )

    passed, log = _pipeline_adapter.run_task(task, project_dir, stack)

    assert passed is True
    assert '"applied": true' in log
    assert git_inits == [(["git", "init"], project_dir)]
    assert Path.cwd() == outer
    assert os.environ["SIMPLICIO_TEST_CMD"] == "pytest old"
    assert (project_dir / "cwd_marker.txt").read_text(encoding="utf-8") == "ok"
    assert not (outer / "cwd_marker.txt").exists()


def test_executor_refuses_existing_project_dir() -> None:
    reg = StackRegistry()
    stack = reg.get("py-fastapi")
    plan = validate_plan(EXAMPLE_PLAN)
    with tempfile.TemporaryDirectory() as td:
        existing = Path(td) / plan.project_name
        existing.mkdir()
        from simplicio.scratch.executor import execute_plan

        with pytest.raises(FileExistsError):
            execute_plan(plan, stack, Path(td), skip_install=True)
