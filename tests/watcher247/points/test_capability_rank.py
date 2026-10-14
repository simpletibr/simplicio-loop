"""capability_rank (plan): which skill fits the subtask, from the existing Prism route (simplicio_loop.route)."""
import pytest

from simplicio_loop import route
from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import capability_rank


def test_registered_at_plan_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "capability_rank"]
    assert (info.stage, info.blocking, info.conditional) == ("plan", False, True)


def test_contract(point_contract, make_ctx):
    point_contract("capability_rank", make_ctx(task_text="fix the login bug"), expect="ok")


def test_a_mutation_ranks_dev_cli_first(point_contract, make_ctx):
    result = point_contract("capability_rank", make_ctx(task_text="fix the login bug"), expect="ok")
    assert result.evidence["intent"] == "mutate"
    assert result.evidence["skills"] == ["simplicio-dev-cli", "simplicio-mapper"]
    assert result.evidence["top"] == "simplicio-dev-cli"


def test_a_lookup_ranks_the_mapper_first(point_contract, make_ctx):
    result = point_contract("capability_rank", make_ctx(task_text="find where the config is loaded"), expect="ok")
    assert result.evidence["intent"] == "retrieve"
    assert result.evidence["top"] == "simplicio-mapper"


def test_orchestration_ranks_the_loop_first(point_contract, make_ctx):
    result = point_contract("capability_rank", make_ctx(task_text="run all issues in batch"), expect="ok")
    assert result.evidence["intent"] == "orchestrate"
    assert result.evidence["skills"][0] == "simplicio-loop"


def test_every_skill_of_the_route_is_ranked_once():
    task = "implement the retry and add tests"
    ranked = capability_rank.rank(task)
    assert sorted(ranked["skills"]) == sorted(route.route(task)["skills_to_load"])
    assert len(set(ranked["skills"])) == len(ranked["skills"])


def test_without_a_task_text_it_is_skipped(point_contract, make_ctx):
    result = point_contract("capability_rank", make_ctx(), expect="skipped")
    assert result.reason_code == "not_applicable"
