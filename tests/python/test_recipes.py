"""Tests for scratch-mode declarative recipe matching and instantiation."""

from __future__ import annotations

from typing import Optional

import pytest

from simplicio.scratch.plan_schema import Plan
from simplicio.scratch.recipes import (
    RecipeMatch,
    RecipeRegistry,
    RecipeSlotError,
    plan_from_recipe,
)


MATCH_CASES = [
    ("py-fastapi", "CRUD API for Unit", "crud-resource", "Unit"),
    (
        "py-fastapi",
        "CRUD app for condo units with owner contact search",
        "crud-resource",
        "CondoUnits",
    ),
    ("py-fastapi", "REST API for Invoice", "crud-resource", "Invoice"),
    ("ts-nextjs", "Manage Product with CRUD", "crud-resource", "Product"),
    (
        "ts-nextjs",
        "CRUD app for condo units with owner contact search",
        "crud-resource",
        "CondoUnits",
    ),
    ("py-fastapi", "add JWT auth", "auth-jwt", None),
    ("ts-nextjs", "authentication with JWT", "auth-jwt", None),
    ("py-fastapi", "login with JWT", "auth-jwt", None),
    ("py-fastapi", "admin panel for Booking", "admin-crud", "Booking"),
    ("ts-nextjs", "admin CRUD for Tenant", "admin-crud", "Tenant"),
    ("ts-nextjs", "backoffice to manage Subscription", "admin-crud", "Subscription"),
    ("go-gin", "add JWT auth", "auth-jwt", None),
    ("php-laravel", "authentication with JWT", "auth-jwt", None),
    ("rust-axum", "login with JWT", "auth-jwt", None),
    (
        "rust-axum",
        "CRUD app for condo units with owner contact search",
        "crud-resource",
        "CondoUnits",
    ),
    (
        "go-gin",
        "CRUD app for condo units with owner contact search",
        "crud-resource",
        "CondoUnits",
    ),
    (
        "php-laravel",
        "CRUD app for condo units with owner contact search",
        "crud-resource",
        "CondoUnits",
    ),
    (
        "php-vanilla",
        "Create or update `docs/simplicio-code-desktop-debug-flow.md` and include the marker text `SimplicioCode Desktop DEBUG E2E`.",
        "docs-marker",
        None,
    ),
]


MISS_CASES = [
    ("py-fastapi", "Build a recommendation engine for movies"),
    ("ts-nextjs", "Create a marketing landing page"),
    ("py-fastapi", "Analyze CSV exports overnight"),
    ("ts-nextjs", "Render a public docs site"),
    ("py-fastapi", "Create websocket chat rooms"),
    ("ts-nextjs", "Add image optimization pipeline"),
    ("py-fastapi", "Generate a billing report"),
    ("ts-nextjs", "Design a pricing comparison table"),
    ("py-fastapi", "Import legacy XML data"),
]


def test_registry_loads_three_pilot_recipes_for_each_stack() -> None:
    registry = RecipeRegistry()

    for stack_slug in ("py-fastapi", "ts-nextjs"):
        names = {recipe.name for recipe in registry.list(stack_slug)}
        assert {"crud-resource", "auth-jwt", "admin-crud"} <= names

    for stack_slug in ("rust-axum", "go-gin", "php-laravel"):
        names = {recipe.name for recipe in registry.list(stack_slug)}
        assert {"crud-resource", "auth-jwt", "admin-crud"} <= names

    assert {recipe.name for recipe in registry.list("php-vanilla")} == {"docs-marker"}


@pytest.mark.parametrize(
    ("stack_slug", "goal", "recipe_name", "entity"),
    MATCH_CASES,
)
def test_recipe_match_cases(
    stack_slug: str,
    goal: str,
    recipe_name: str,
    entity: Optional[str],
) -> None:
    registry = RecipeRegistry()

    match = registry.match(goal, stack_slug)

    assert match is not None
    assert match.recipe_name == recipe_name
    assert match.stack_slug == stack_slug
    if entity is not None:
        assert match.slots.get("Entity", match.slots.get("entity")) == entity


@pytest.mark.parametrize(("stack_slug", "goal"), MISS_CASES)
def test_recipe_miss_cases_fall_back_to_planner(
    stack_slug: str,
    goal: str,
) -> None:
    registry = RecipeRegistry()

    assert registry.match(goal, stack_slug) is None
    assert plan_from_recipe(goal, stack_slug, "demo-app") is None


@pytest.mark.parametrize(
    ("stack_slug", "goal", "recipe_name", "entity"),
    MATCH_CASES,
)
def test_recipe_instantiation_returns_valid_plan(
    stack_slug: str,
    goal: str,
    recipe_name: str,
    entity: Optional[str],
) -> None:
    registry = RecipeRegistry()
    match = registry.match(goal, stack_slug)
    assert match is not None

    recipe = registry.get(match.recipe_name, match.stack_slug)
    plan = recipe.instantiate(match, "demo-app")

    assert isinstance(plan, Plan)
    assert plan.stack == stack_slug
    assert plan.project_name == "demo-app"
    assert plan.estimated_total_tasks == len(plan.tasks)
    assert plan.tasks
    assert match.recipe_name == recipe_name
    if entity is not None:
        assert entity in plan.rationale


def test_plan_from_recipe_skips_planner_for_match() -> None:
    plan = plan_from_recipe("CRUD API for Unit", "py-fastapi", "demo-app")

    assert plan is not None
    assert plan.stack == "py-fastapi"
    assert plan.tasks[0].target == "src/db/unit.py"


def test_php_vanilla_docs_marker_recipe_targets_requested_document() -> None:
    goal = (
        "Create or update `docs/simplicio-code-desktop-debug-flow.md`. "
        "Include the marker text `SimplicioCode Desktop DEBUG E2E`."
    )
    plan = plan_from_recipe(goal, "php-vanilla", "sindico")

    assert plan is not None
    assert plan.stack == "php-vanilla"
    assert plan.tasks[0].target == "docs/simplicio-code-desktop-debug-flow.md"
    assert "SimplicioCode Desktop DEBUG E2E" in plan.tasks[0].criteria


def test_required_slot_error_mentions_slot_flag() -> None:
    registry = RecipeRegistry()
    recipe = registry.get("crud-resource", "py-fastapi")
    empty_match = RecipeMatch(
        recipe_name="crud-resource",
        slots={},
        stack_slug="py-fastapi",
    )

    with pytest.raises(RecipeSlotError) as exc:
        recipe.instantiate(empty_match, "demo-app")

    assert "entity" in str(exc.value)
    assert "--slot entity=VALUE" in str(exc.value)


def test_same_recipe_name_renders_stack_specific_plan() -> None:
    registry = RecipeRegistry()
    py_match = registry.match("CRUD API for Unit", "py-fastapi")
    ts_match = registry.match("CRUD page for Unit", "ts-nextjs")
    assert py_match is not None
    assert ts_match is not None

    py_plan = registry.get("crud-resource", "py-fastapi").instantiate(
        py_match,
        "demo-app",
    )
    ts_plan = registry.get("crud-resource", "ts-nextjs").instantiate(
        ts_match,
        "demo-app",
    )

    assert py_plan.tasks[0].target == "src/db/unit.py"
    assert ts_plan.tasks[0].target == "src/app/api/units/route.ts"


def test_ts_nextjs_crud_recipe_renders_multi_word_entity() -> None:
    registry = RecipeRegistry()
    match = registry.match(
        "CRUD app for condo units with owner contact search",
        "ts-nextjs",
    )
    assert match is not None

    plan = registry.get("crud-resource", "ts-nextjs").instantiate(
        match,
        "demo-app",
    )

    assert plan.tasks[0].target == "src/app/api/condo_units/route.ts"
    assert plan.tasks[1].target == "src/app/condo_units/page.tsx"


def test_rust_axum_crud_recipe_renders_multi_word_entity() -> None:
    registry = RecipeRegistry()
    match = registry.match(
        "CRUD app for condo units with owner contact search",
        "rust-axum",
    )
    assert match is not None

    plan = registry.get("crud-resource", "rust-axum").instantiate(
        match,
        "demo-app",
    )

    assert plan.tasks[0].target == "src/main.rs"
    assert "route prefix is /condo_units" in plan.tasks[0].criteria


def test_go_gin_crud_recipe_renders_multi_word_entity() -> None:
    registry = RecipeRegistry()
    match = registry.match(
        "CRUD app for condo units with owner contact search",
        "go-gin",
    )
    assert match is not None

    plan = registry.get("crud-resource", "go-gin").instantiate(
        match,
        "demo-app",
    )

    assert plan.tasks[0].target == "internal/http/router.go"
    assert "route prefix is /condo_units" in plan.tasks[0].criteria


def test_php_laravel_crud_recipe_renders_multi_word_entity() -> None:
    registry = RecipeRegistry()
    match = registry.match(
        "CRUD app for condo units with owner contact search",
        "php-laravel",
    )
    assert match is not None

    plan = registry.get("crud-resource", "php-laravel").instantiate(
        match,
        "demo-app",
    )

    assert plan.tasks[0].target == "routes/api.php"
    assert "route prefix is /condo_units" in plan.tasks[0].criteria


AUTH_JWT_TARGETS = {
    "go-gin": [
        "internal/auth/jwt.go",
        "internal/http/auth_routes.go",
        "internal/http/auth_test.go",
    ],
    "php-laravel": [
        "app/Services/JwtService.php",
        "app/Http/Controllers/AuthController.php",
        "tests/Feature/AuthJwtTest.php",
    ],
    "rust-axum": [
        "src/auth.rs",
        "src/main.rs",
    ],
}


@pytest.mark.parametrize(("stack_slug", "targets"), list(AUTH_JWT_TARGETS.items()))
def test_auth_jwt_recipe_renders_stack_specific_targets(
    stack_slug: str,
    targets: list[str],
) -> None:
    registry = RecipeRegistry()
    match = registry.match("add JWT auth", stack_slug)
    assert match is not None
    assert match.recipe_name == "auth-jwt"

    plan = registry.get("auth-jwt", stack_slug).instantiate(match, "demo-app")

    assert [task.target for task in plan.tasks] == targets
    assert plan.estimated_total_tasks == len(plan.tasks)


def test_auth_jwt_default_subject_does_not_require_slot() -> None:
    for stack_slug in AUTH_JWT_TARGETS:
        plan = plan_from_recipe("authentication with JWT", stack_slug, "demo-app")
        assert plan is not None
        assert plan.stack == stack_slug
        assert plan.tasks
