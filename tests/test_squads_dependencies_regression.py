"""Regression tests for Issue #1804:
[squads plan] ignores dependencies between issues; dependent work starts in parallel.

Reproduces the test case of issues #7552 and #7553, verifying:
- Parsing of dependencies in issue body with various formats:
  `depends on #N`, `depende de #N`, `parte de #N`, `blocked by #N`, `bloqueado por #N`,
  cross references, etc.
- In squad partitioning (`plan_squads`), topology is respected:
  dependent issues are allocated to the same squad (when capacity/area permits)
  or grouped into subsequent waves (`waves`).
- Dependency edges are emitted in `contracts` and `blocked_by` fields.
"""
from __future__ import annotations

import pytest

from simplicio_loop import squads


def test_issue_7552_7553_same_squad_topology_and_blocked_by():
    """Reproduce issues #7552 and #7553 when allocated to the same squad.

    #7553 depends on #7552. With default max_workers (4), both fit in the same squad.
    Verify that:
    - Worker for #7553 is marked blocked_by=[7552], while #7552 is unblocked.
    - MergeStep for #7553 is marked blocked_by=[7552].
    - Merge order merges #7552 before #7553.
    - Both belong to wave 1 of squads.
    """
    issues = [
        {"number": 7552, "title": "Base foundational engine", "area": "core"},
        {"number": 7553, "title": "Dependent feature", "area": "core", "body": "Depende de #7552"},
    ]
    plan = squads.plan_squads(issues)

    assert len(plan.squads) == 1
    squad = plan.squads[0]
    assert squad.issues == (7552, 7553)

    # Workers in the squad
    workers_by_issue = {w.issues[0]: w for w in squad.workers}
    assert workers_by_issue[7552].blocked_by == ()
    assert workers_by_issue[7553].blocked_by == (7552,)

    # Merge steps
    steps = {m.issue: m for m in plan.merge_order}
    assert steps[7552].blocked_by == ()
    assert steps[7553].blocked_by == (7552,)
    assert [m.issue for m in plan.merge_order] == [7552, 7553]

    # Waves
    assert plan.waves == ((squad.id,),)
    assert squad.wave == 1
    assert squad.blocked_by == ()


def test_issue_7552_7553_split_squads_subsequent_waves_and_contracts():
    """Reproduce issues #7552 and #7553 when allocated across different squads.

    When max_workers=1 (or different areas), #7552 and #7553 are partitioned into
    separate squads. Verify that:
    - Squads are grouped into subsequent waves (wave 1 for #7552, wave 2 for #7553).
    - Squad for #7553 is blocked_by the squad of #7552.
    - Contract is emitted between the producer squad and consumer squad.
    - Worker for #7553 has blocked_by=[7552].
    """
    issues = [
        {"number": 7552, "title": "Base foundational engine", "area": "backend"},
        {"number": 7553, "title": "Dependent feature", "area": "frontend", "body": "Depends on #7552"},
    ]
    plan = squads.plan_squads(issues)

    assert len(plan.squads) == 2
    squad_of = {s.issues[0]: s for s in plan.squads}
    sq_7552 = squad_of[7552]
    sq_7553 = squad_of[7553]

    # Wave assignment
    assert sq_7552.wave == 1
    assert sq_7553.wave == 2
    assert sq_7553.blocked_by == (sq_7552.id,)
    assert plan.waves == ((sq_7552.id,), (sq_7553.id,))

    # Contracts emitted between squads
    assert len(plan.contracts) == 1
    assert plan.contracts[0].producer == sq_7552.id
    assert plan.contracts[0].consumer == sq_7553.id

    # Worker level blocked_by
    worker_7553 = sq_7553.workers[0]
    assert worker_7553.blocked_by == (7552,)


@pytest.mark.parametrize("body", [
    "depends on #7552",
    "Depends on #7552",
    "depende de #7552",
    "Depende de #7552",
    "parte de #7552",
    "Parte de #7552",
    "part of #7552",
    "blocked by #7552",
    "bloqueado por #7552",
    "requires #7552",
    "requer #7552",
    "after #7552",
    "após #7552",
    "cross-reference: #7552",
    "ref: #7552",
    "## Dependencies\n- #7552",
    "## Dependências\n* #7552",
    "## Blocked by\n1. #7552",
    "depends on https://github.com/simpletibr/simplicio-loop/issues/7552",
])
def test_dependency_parsing_various_body_formats(body):
    """Verify that multiple dependency formats in issue body are recognized."""
    issues = [
        {"number": 7552, "title": "Issue 7552"},
        {"number": 7553, "title": "Issue 7553", "body": body},
    ]
    deps = squads.dependencies(issues)
    assert deps[7553] == (7552,)
    assert deps[7552] == ()

    plan = squads.plan_squads(issues, max_workers=1)
    assert len(plan.squads) == 2
    squad_7553 = next(s for s in plan.squads if 7553 in s.issues)
    assert squad_7553.wave == 2
    assert squad_7553.workers[0].blocked_by == (7552,)


def test_dependent_issues_packed_together_in_squad_when_capacity_permits():
    """Verify that connected dependency pairs in the same group are packed into the same squad."""
    # 4 issues: 1 and 2 depend on each other (2 -> 1), 3 and 4 depend on each other (4 -> 3)
    issues = [
        {"number": 1, "area": "api"},
        {"number": 2, "area": "api", "body": "depends on #1"},
        {"number": 3, "area": "api"},
        {"number": 4, "area": "api", "body": "depends on #3"},
    ]
    plan = squads.plan_squads(issues, max_workers=2)

    # Should form 2 squads of size 2: (1, 2) and (3, 4)
    # Neither squad depends on the other, so both run in wave 1 in parallel!
    assert len(plan.squads) == 2
    squad_issues = [s.issues for s in plan.squads]
    assert (1, 2) in squad_issues
    assert (3, 4) in squad_issues
    assert all(s.wave == 1 for s in plan.squads)
    assert plan.waves == ((plan.squads[0].id, plan.squads[1].id),)


def test_plan_to_dict_includes_waves_and_blocked_by():
    """Verify that serialized plan dictionary includes waves, blocked_by, and contracts."""
    issues = [
        {"number": 7552, "area": "a"},
        {"number": 7553, "area": "b", "body": "blocked by #7552"},
    ]
    plan = squads.plan_squads(issues)
    data = plan.to_dict()

    assert "waves" in data
    assert len(data["waves"]) == 2
    assert data["waves"][0] == [plan.squads[0].id]
    assert data["waves"][1] == [plan.squads[1].id]

    # Squad level
    squad_b = next(s for s in data["squads"] if 7553 in s["issues"])
    assert squad_b["wave"] == 2
    assert squad_b["blocked_by"] == [plan.squads[0].id]

    # Worker level
    worker_7553 = next(w for w in squad_b["workers"] if w["issues"] == [7553])
    assert worker_7553["blocked_by"] == [7552]

    # Merge step
    step_7553 = next(m for m in data["merge_order"] if m["issue"] == 7553)
    assert step_7553["blocked_by"] == [7552]
