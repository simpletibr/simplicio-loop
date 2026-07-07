from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from simplicio.scratch import cli as scratch_cli
from simplicio.scratch.plan_schema import EXAMPLE_PLAN, validate_plan


def _plan(stack_slug: str, project_name: str):
    raw = {**EXAMPLE_PLAN, "stack": stack_slug, "project_name": project_name}
    return validate_plan(raw)


@dataclass
class _FakeRecipe:
    name: str
    description: str
    applies_to: list[str]
    matches: list[re.Pattern[str]]
    slots_spec: dict[str, object]


class _FakeRecipeRegistry:
    def list(self):
        return [
            _FakeRecipe(
                name="crud-resource",
                description="REST CRUD endpoints for one entity",
                applies_to=["py-fastapi", "ts-nextjs"],
                matches=[re.compile(r"(?i)CRUD\s+(?P<entity>\w+)")],
                slots_spec={"entity": {"required": True}},
            )
        ]


def test_list_recipes_outputs_registered_patterns(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        scratch_cli,
        "_load_recipe_registry",
        lambda: _FakeRecipeRegistry(),
    )

    rc = scratch_cli.main(["--list-recipes"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "crud-resource" in out
    assert "py-fastapi,ts-nextjs" in out
    assert "entity" in out
    assert r"(?i)CRUD\s+(?P<entity>\w+)" in out


def test_list_recipes_json_outputs_machine_readable_registry(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        scratch_cli,
        "_load_recipe_registry",
        lambda: _FakeRecipeRegistry(),
    )

    rc = scratch_cli.main(["--list-recipes", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data == [
        {
            "name": "crud-resource",
            "description": "REST CRUD endpoints for one entity",
            "applies_to": ["py-fastapi", "ts-nextjs"],
            "slots": ["entity"],
            "matches": [r"(?i)CRUD\s+(?P<entity>\w+)"],
        }
    ]


def test_list_recipes_reports_missing_registry(monkeypatch, capsys) -> None:
    monkeypatch.setattr(scratch_cli, "_load_recipe_registry", lambda: None)

    rc = scratch_cli.main(["--list-recipes"])

    assert rc == 2
    assert "recipe registry is not available" in capsys.readouterr().err


def test_slot_values_are_passed_to_generate_plan_signature(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, object] = {}

    def fake_generate_plan(stack, goal, project_name, *, slots):
        captured["stack"] = stack.slug
        captured["goal"] = goal
        captured["project_name"] = project_name
        captured["slots"] = slots
        return _plan(stack.slug, project_name)

    monkeypatch.setattr(scratch_cli, "generate_plan", fake_generate_plan)
    monkeypatch.setattr(scratch_cli, "planner_info", lambda: "test-planner")

    rc = scratch_cli.main(
        [
            "CRUD API for Unit",
            "--stack",
            "py-fastapi",
            "--plan-only",
            "--json",
            "--slot",
            "entity=Unit",
        ]
    )

    assert rc == 0
    assert captured == {
        "stack": "py-fastapi",
        "goal": "CRUD API for Unit",
        "project_name": "crud-api-for-unit",
        "slots": {"entity": "Unit"},
    }
    assert json.loads(capsys.readouterr().out)["project_name"] == ("crud-api-for-unit")


def test_slot_values_fall_back_to_environment_for_old_planner_signature(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_generate_plan(stack, goal, project_name):
        captured["recipe_slots"] = os.environ.get("SIMPLICIO_RECIPE_SLOTS")
        return _plan(stack.slug, project_name)

    monkeypatch.setenv("SIMPLICIO_RECIPE_SLOTS", "previous")
    monkeypatch.setattr(scratch_cli, "generate_plan", fake_generate_plan)
    monkeypatch.setattr(scratch_cli, "planner_info", lambda: "test-planner")

    rc = scratch_cli.main(
        [
            "CRUD API for Unit",
            "--stack",
            "py-fastapi",
            "--plan-only",
            "--slot",
            "entity=Unit",
        ]
    )

    assert rc == 0
    assert captured["recipe_slots"] == '{"entity": "Unit"}'
    assert os.environ["SIMPLICIO_RECIPE_SLOTS"] == "previous"


def test_empty_slot_value_fails_before_planner(monkeypatch, capsys) -> None:
    called = False

    def fake_generate_plan(stack, goal, project_name):
        nonlocal called
        called = True
        return _plan(stack.slug, project_name)

    monkeypatch.setattr(scratch_cli, "generate_plan", fake_generate_plan)

    rc = scratch_cli.main(
        [
            "CRUD API for Unit",
            "--stack",
            "py-fastapi",
            "--plan-only",
            "--slot",
            "entity=",
        ]
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert called is False
    assert "slot 'entity' requires a value" in err
    assert "--slot entity=X" in err


def test_infer_stack_from_existing_dotnet_solution_root(tmp_path) -> None:
    (tmp_path / "BeyondLabs.MaturityMatrix.slnx").write_text(
        "<Solution></Solution>",
        encoding="utf-8",
    )

    assert (
        scratch_cli._infer_stack(
            scratch_cli.StackRegistry(),
            "align frontend endpoints with existing backend",
            root=str(tmp_path),
        )
        == "csharp-aspnet"
    )


def test_infer_stack_from_existing_angular_root(tmp_path) -> None:
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")

    assert (
        scratch_cli._infer_stack(
            scratch_cli.StackRegistry(),
            "align frontend endpoints with existing backend",
            root=str(tmp_path),
        )
        == "react-vite"
    )
