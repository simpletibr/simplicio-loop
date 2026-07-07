"""cli.py — argparse handler for `simplicio-py scratch ...`.

Wired into simplicio.cli.main; this module never expects to be invoked
directly. Top-level surface:

    simplicio-py scratch "<goal>" [--stack <slug>] [--planner <provider>]
    simplicio-py scratch --list-stacks
    simplicio-py scratch --show-stack <slug>
    simplicio-py scratch --plan-only "<goal>" --stack <slug>
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..providers import planner_info
from .planner import PlannerError, generate_plan
from .stack_registry import StackRegistry, slugify_project


def _add_scratch_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "goal",
        nargs="?",
        default=None,
        help="one-line description of the project to create",
    )
    p.add_argument(
        "--stack",
        default=None,
        help="explicit stack slug (e.g. py-fastapi); inferred if omitted",
    )
    p.add_argument(
        "--name",
        default=None,
        help="project directory name (derived from goal if omitted)",
    )
    p.add_argument(
        "--dest",
        default=".",
        help="parent directory where the project dir is created (default: cwd)",
    )
    p.add_argument(
        "--root",
        default=".",
        help="existing project root used for stack detection (default: cwd)",
    )
    p.add_argument("--planner", default=None, help="override SIMPLICIO_PLANNER for this run only")
    p.add_argument(
        "--plan-only",
        action="store_true",
        help="run planner and print the validated plan; skip execution",
    )
    p.add_argument(
        "--skip-install",
        action="store_true",
        help="skip package-manager install after scaffolding",
    )
    p.add_argument("--list-stacks", action="store_true", help="print available stack templates")
    p.add_argument(
        "--show-stack",
        default=None,
        metavar="SLUG",
        help="print readme + metadata for one stack",
    )
    p.add_argument(
        "--list-recipes",
        action="store_true",
        help="print registered scratch plan recipes",
    )
    p.add_argument(
        "--slot",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="fill a required recipe slot; may be repeated",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON output where applicable",
    )


def _cmd_list(reg: StackRegistry, as_json: bool) -> int:
    stacks = reg.list()
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "slug": s.slug,
                        "language": s.language,
                        "framework": s.framework,
                        "version": s.version,
                        "tags": s.meta.get("tags", []),
                    }
                    for s in stacks
                ],
                indent=2,
            )
        )
        return 0
    if not stacks:
        print("(no stack templates installed)")
        return 0
    print(f"{'slug':24s}  {'language':14s}  {'framework':30s}  version")
    print("-" * 86)
    for s in stacks:
        print(f"{s.slug:24s}  {s.language:14s}  {s.framework:30s}  {s.version}")
    return 0


def _cmd_show(reg: StackRegistry, slug: str, as_json: bool) -> int:
    s = reg.get(slug)
    if s is None:
        print(f"unknown stack: {slug}", file=sys.stderr)
        return 2
    if as_json:
        print(
            json.dumps(
                {
                    "slug": s.slug,
                    "meta": s.meta,
                    "verify": s.verify,
                    "readme": s.readme,
                    "practices": s.practices,
                },
                indent=2,
            )
        )
        return 0
    print(f"# {s.slug}")
    print(f"language : {s.language}")
    print(f"framework: {s.framework}")
    print(f"version  : {s.version}")
    print(f"verify   : install={s.install_command!r} test={s.test_command!r} lint={s.lint_command!r}")
    print()
    print("## README")
    print(s.readme or "(no README)")
    return 0


def _load_recipe_registry() -> Any | None:
    try:
        from .recipes import RecipeRegistry
    except ModuleNotFoundError as exc:
        if exc.name in {"simplicio.scratch.recipes", f"{__package__}.recipes"}:
            return None
        raise

    reg = RecipeRegistry()
    load = getattr(reg, "load", None)
    if callable(load):
        load()
    return reg


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _iter_recipes(reg: Any) -> list[Any]:
    for attr in ("list", "all", "recipes", "_recipes"):
        value = getattr(reg, attr, None)
        if callable(value):
            value = value()
        if value:
            if isinstance(value, dict):
                return list(value.values())
            return list(value)
    return []


def _recipe_summary(recipe: Any) -> dict[str, Any]:
    matches = _attr(recipe, "matches", []) or []
    patterns = [getattr(pattern, "pattern", str(pattern)) for pattern in matches]
    slots = _attr(recipe, "slots_spec", None) or _attr(recipe, "slots", None) or {}
    if isinstance(slots, dict):
        slot_names = sorted(str(key) for key in slots)
    else:
        slot_names = [str(slot) for slot in slots]
    return {
        "name": _attr(recipe, "name", "<unnamed>"),
        "description": _attr(recipe, "description", ""),
        "applies_to": list(_attr(recipe, "applies_to", []) or []),
        "slots": slot_names,
        "matches": patterns,
    }


def _cmd_list_recipes(as_json: bool) -> int:
    reg = _load_recipe_registry()
    if reg is None:
        print(
            "error: recipe registry is not available in this checkout",
            file=sys.stderr,
        )
        return 2

    recipes = [_recipe_summary(recipe) for recipe in _iter_recipes(reg)]
    if as_json:
        print(json.dumps(recipes, indent=2))
        return 0
    if not recipes:
        print("(no scratch recipes registered)")
        return 0

    print(f"{'recipe':24s}  {'stacks':24s}  slots")
    print("-" * 74)
    for recipe in recipes:
        stacks = ",".join(recipe["applies_to"]) or "-"
        slots = ",".join(recipe["slots"]) or "-"
        print(f"{recipe['name']:24s}  {stacks:24s}  {slots}")
        if recipe["description"]:
            print(f"  {recipe['description']}")
        for pattern in recipe["matches"]:
            print(f"  match: {pattern}")
    return 0


def _parse_slots(raw_slots: list[str]) -> dict[str, str]:
    slots: dict[str, str] = {}
    for raw in raw_slots:
        key, sep, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not key:
            raise ValueError(f"invalid --slot {raw!r}; use --slot key=value")
        if not value:
            raise ValueError(f"slot '{key}' requires a value; pass --slot {key}=X")
        slots[key] = value
    return slots


def _generate_plan_with_slots(
    stack: Any,
    goal: str,
    project_name: str,
    slots: dict[str, str],
) -> Any:
    params = inspect.signature(generate_plan).parameters
    if "slots" in params:
        return generate_plan(stack, goal, project_name, slots=slots)
    if "recipe_slots" in params:
        return generate_plan(stack, goal, project_name, recipe_slots=slots)
    if not slots:
        return generate_plan(stack, goal, project_name)

    previous = os.environ.get("SIMPLICIO_RECIPE_SLOTS")
    os.environ["SIMPLICIO_RECIPE_SLOTS"] = json.dumps(slots, sort_keys=True)
    try:
        return generate_plan(stack, goal, project_name)
    finally:
        if previous is None:
            os.environ.pop("SIMPLICIO_RECIPE_SLOTS", None)
        else:
            os.environ["SIMPLICIO_RECIPE_SLOTS"] = previous


def _infer_stack(reg: StackRegistry, goal: str, root: str = ".") -> str | None:
    """Infer stack from goal keywords, then from existing project files."""
    g = goal.lower()

    if any(k in g for k in ("nextjs", "next.js", "next ", "vercel")):
        if reg.get("ts-nextjs"):
            return "ts-nextjs"
    if any(k in g for k in ("nestjs", "nest.js", "nest ")) and reg.get("ts-nestjs"):
        return "ts-nestjs"
    if "remix" in g and reg.get("ts-remix"):
        return "ts-remix"
    if "fastapi" in g and reg.get("py-fastapi"):
        return "py-fastapi"
    if "django" in g and reg.get("py-django"):
        return "py-django"
    if "flask" in g and reg.get("py-flask"):
        return "py-flask"
    if any(k in g for k in ("typer", "python cli", "command line")) and reg.get("py-cli"):
        return "py-cli"
    if any(k in g for k in ("express", "node api", "node.js api")) and reg.get("js-express"):
        return "js-express"
    if any(k in g for k in ("vite", "react spa", "react app")) and reg.get("react-vite"):
        return "react-vite"
    if any(k in g for k in ("bash", "shell script", "shell cli")) and reg.get("bash-cli"):
        return "bash-cli"
    if any(k in g for k in ("axum", "rust ")) and reg.get("rust-axum"):
        return "rust-axum"
    if "leptos" in g and reg.get("rust-leptos"):
        return "rust-leptos"
    if any(k in g for k in ("rust cli", "clap ")) and reg.get("rust-cli"):
        return "rust-cli"
    if "laravel" in g and reg.get("php-laravel"):
        return "php-laravel"
    if any(k in g for k in ("plain php", "phpunit", "vanilla php")) and reg.get("php-vanilla"):
        return "php-vanilla"
    if "symfony" in g and reg.get("php-symfony"):
        return "php-symfony"
    if any(k in g for k in ("rails", "ruby on rails")) and reg.get("ruby-rails"):
        return "ruby-rails"
    if any(k in g for k in ("asp.net", "aspnet", "c# api")) and reg.get("csharp-aspnet"):
        return "csharp-aspnet"
    if any(k in g for k in ("blazor", "c# ui")) and reg.get("csharp-blazor"):
        return "csharp-blazor"
    if any(k in g for k in ("java spring", "spring boot java")) and reg.get("java-spring"):
        return "java-spring"
    if any(k in g for k in ("kotlin spring", "spring boot kotlin")) and reg.get("kotlin-spring"):
        return "kotlin-spring"
    if "ktor" in g and reg.get("kotlin-ktor"):
        return "kotlin-ktor"
    if any(k in g for k in ("phoenix", "elixir")) and reg.get("elixir-phoenix"):
        return "elixir-phoenix"
    if "flutter" in g and reg.get("dart-flutter"):
        return "dart-flutter"
    if any(k in g for k in ("android", "jetpack compose")) and reg.get("kotlin-android"):
        return "kotlin-android"
    if any(k in g for k in ("vapor", "swift api")) and reg.get("swift-vapor"):
        return "swift-vapor"
    if any(k in g for k in ("swiftui", "ios app", "iphone")) and reg.get("swift-ios"):
        return "swift-ios"
    if any(k in g for k in ("echo", "go api")) and reg.get("go-echo"):
        return "go-echo"
    if any(k in g for k in ("go cli", "cobra", "viper")) and reg.get("go-cli"):
        return "go-cli"
    if any(k in g for k in (" go ", "golang", "gin ")) and reg.get("go-gin"):
        return "go-gin"

    return _detect_stack_from_files(reg, root)


def _detect_stack_from_files(reg: StackRegistry, root: str = ".") -> str | None:
    """Inspect the target directory for common project markers."""
    try:
        root_path = Path(root).resolve()
    except Exception:
        return None

    if (
        list(root_path.glob("*.slnx"))
        or list(root_path.glob("*.csproj"))
        or list(root_path.rglob("*.csproj"))
    ):
        if reg.get("csharp-aspnet"):
            return "csharp-aspnet"
        if reg.get("csharp-blazor"):
            return "csharp-blazor"

    # JS/TS markers
    if (root_path / "angular.json").exists():
        if reg.get("ts-angular"):
            return "ts-angular"
        # fallback to generic ts if angular stack isn't registered
        return None
    if (root_path / "package.json").exists():
        if reg.get("ts-nextjs"):
            return "ts-nextjs"
        if reg.get("react-vite"):
            return "react-vite"
        return None

    pyproject = root_path / "pyproject.toml"
    requirements = root_path / "requirements.txt"

    has_fastapi = False
    has_streamlit = False

    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
            if "fastapi" in content:
                has_fastapi = True
            if "streamlit" in content:
                has_streamlit = True
        except Exception:
            pass

    if requirements.exists():
        try:
            content = requirements.read_text(encoding="utf-8", errors="ignore").lower()
            if "fastapi" in content:
                has_fastapi = True
            if "streamlit" in content:
                has_streamlit = True
        except Exception:
            pass

    if has_fastapi and reg.get("py-fastapi"):
        return "py-fastapi"
    if has_streamlit:
        if reg.get("py-fastapi"):
            return "py-fastapi"

    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
            if "typer" in content and reg.get("py-cli"):
                return "py-cli"
        except Exception:
            pass

    # Fallback: scan for .py files
    try:
        py_files = list(root_path.rglob("*.py"))
        if py_files and reg.get("py-cli"):
            return "py-cli"
    except Exception:
        pass

    return None


def _cmd_scratch(args: argparse.Namespace, reg: StackRegistry) -> int:
    goal = args.goal
    if not goal:
        print(
            'error: provide a goal, e.g. simplicio-py scratch "CRUD for condo units"',
            file=sys.stderr,
        )
        return 2

    stack_slug = args.stack or _infer_stack(reg, goal, getattr(args, "root", "."))
    if not stack_slug:
        print(
            "error: could not infer stack from goal; pass --stack <slug>. "
            "List available with `simplicio-py scratch --list-stacks`.",
            file=sys.stderr,
        )
        return 2
    stack = reg.get(stack_slug)
    if stack is None:
        print(
            f"error: unknown stack '{stack_slug}'. Run `simplicio-py scratch --list-stacks`.",
            file=sys.stderr,
        )
        return 2

    try:
        slots = _parse_slots(args.slot)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    project_name = args.name or slugify_project(goal)

    if args.planner:
        os.environ["SIMPLICIO_PLANNER"] = args.planner

    print(
        f"[scratch] stack:   {stack.slug} ({stack.language} / {stack.framework})",
        file=sys.stderr,
    )
    print(f"[scratch] project: {project_name}", file=sys.stderr)
    try:
        planner = planner_info()
    except SystemExit as exc:
        planner = f"unavailable ({exc})"
    print(f"[scratch] planner: {planner}", file=sys.stderr)
    if slots:
        print(f"[scratch] slots:   {', '.join(sorted(slots))}", file=sys.stderr)
    print("[scratch] generating plan...", file=sys.stderr)

    try:
        plan = _generate_plan_with_slots(stack, goal, project_name, slots)
    except PlannerError as e:
        print(f"[scratch] planner failed: {e}", file=sys.stderr)
        return 3

    print(f"[scratch] plan ok: {len(plan.tasks)} tasks", file=sys.stderr)

    if args.plan_only:
        if args.json:
            print(
                json.dumps(
                    {
                        "version": plan.version,
                        "stack": plan.stack,
                        "project_name": plan.project_name,
                        "rationale": plan.rationale,
                        "tasks": [
                            {
                                "id": t.id,
                                "goal": t.goal,
                                "target": t.target,
                                "criteria": t.criteria,
                                "constraints": t.constraints,
                                "verify": t.verify,
                                "depends_on": t.depends_on,
                            }
                            for t in plan.tasks
                        ],
                        "deps_to_install": plan.deps_to_install,
                        "deps_dev": plan.deps_dev,
                        "test_command": plan.test_command,
                        "lint_command": plan.lint_command,
                    },
                    indent=2,
                )
            )
        else:
            print(f"# scratch plan — {plan.project_name}")
            print(f"rationale: {plan.rationale}")
            print(f"tasks: {len(plan.tasks)}")
            for t in plan.tasks:
                deps = f" (depends_on={','.join(t.depends_on) or 'none'})"
                print(f"  - {t.id}{deps}: {t.goal}")
                print(f"     target: {t.target}")
                print(f"     verify: {t.verify}")
        return 0

    from .executor import execute_plan

    try:
        report = execute_plan(plan, stack, Path(args.dest), skip_install=args.skip_install)
    except FileExistsError as e:
        print(f"[scratch] {e}", file=sys.stderr)
        return 4

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"[scratch] done: {report.project_dir}", file=sys.stderr)
        print(f"          files written: {len(report.files_written)}", file=sys.stderr)
        print(
            f"          install: {'ok' if report.install_ok else 'fail/skipped'}",
            file=sys.stderr,
        )
        print(
            f"          tasks  : {report.tasks_passed}/{report.tasks_total} passed",
            file=sys.stderr,
        )
    return 0 if report.tasks_passed == report.tasks_total else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-py scratch")
    _add_scratch_args(parser)
    args = parser.parse_args(argv)

    reg = StackRegistry()

    if args.list_stacks:
        return _cmd_list(reg, args.json)
    if args.show_stack:
        return _cmd_show(reg, args.show_stack, args.json)
    if args.list_recipes:
        return _cmd_list_recipes(args.json)
    return _cmd_scratch(args, reg)
