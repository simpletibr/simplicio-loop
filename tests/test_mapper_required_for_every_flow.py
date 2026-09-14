"""Mapper is mandatory for every Loop execution route."""

from __future__ import annotations

from simplicio_loop.execution_route import decide_mapper_requirement
from simplicio_loop.strict_mode import CORE_OPERATORS, required_bound_operators


def test_core_operators_always_include_mapper():
    assert CORE_OPERATORS[0] == "simplicio-mapper"
    required = required_bound_operators({"SIMPLICIO_LOOP_REQUIRE_RUNTIME": "off"})
    assert "simplicio-mapper" in required


def test_mapper_is_required_for_mechanical_and_empty_tasks():
    for description in (
        "",
        "edit site/checkers.html",
        "mechanical replace of a typo",
        "create a checkers game",
        "run tick then batch",
    ):
        decision = decide_mapper_requirement(description)
        assert decision["required"] is True, description
        assert decision["mode"] in {"targeted", "full"}, description
        assert decision["action"] in {"invoke", "reuse"}, description
        assert decision["action"] != "skip", description
