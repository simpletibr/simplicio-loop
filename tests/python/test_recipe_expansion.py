from __future__ import annotations

import pytest

from simplicio.scratch.recipes import RecipeRegistry, plan_from_recipe


@pytest.mark.parametrize(
    ("stack_slug", "goal", "recipe_name"),
    [
        ("py-fastapi", "add file upload for avatar images", "file-upload"),
        ("py-fastapi", "create websocket chat rooms", "websocket"),
        ("py-fastapi", "background worker for email delivery", "background-worker"),
        ("py-fastapi", "scheduled job for nightly cleanup", "scheduled-job"),
        ("py-fastapi", "OAuth integration with GitHub", "oauth-integration"),
    ],
)
def test_new_llm_reduction_recipe_types_match_for_fastapi(
    stack_slug: str,
    goal: str,
    recipe_name: str,
) -> None:
    registry = RecipeRegistry()

    match = registry.match(goal, stack_slug)

    assert match is not None
    assert match.recipe_name == recipe_name
    plan = plan_from_recipe(goal, stack_slug, "demo-app")
    assert plan is not None
    assert plan.stack == stack_slug
    assert plan.tasks


@pytest.mark.parametrize(
    ("stack_slug", "target"),
    [
        ("php-laravel", "routes/api.php"),
        ("go-gin", "internal/http/router.go"),
        ("rust-axum", "src/main.rs"),
    ],
)
def test_admin_crud_parity_for_remaining_web_stacks(
    stack_slug: str,
    target: str,
) -> None:
    plan = plan_from_recipe(f"admin CRUD for Invoice", stack_slug, "demo-app")

    assert plan is not None
    assert plan.stack == stack_slug
    assert plan.tasks[0].target == target
    assert "admin" in plan.rationale.lower()
