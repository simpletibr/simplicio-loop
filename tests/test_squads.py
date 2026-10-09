"""Squad planning and merge gate (#1502)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess

import pytest

from simplicio_loop import model_roles, squads


def _issues(n):
    return [{"number": i, "title": "issue %d" % i, "area": "alpha"} for i in range(1, n + 1)]


def _plan_dict(plan):
    return json.loads(json.dumps(plan.to_dict()))


# ---------------------------------------------------------------- plan: models per family


def test_claude_roles_use_the_table_models():
    plan = squads.plan_squads(_issues(2), family="claude")
    assert plan.general_coordinator.role == "planning"
    assert plan.general_coordinator.model == "claude-opus-5-5"
    assert plan.general_coordinator.effort == "high"
    squad = plan.squads[0]
    assert squad.coordinator.role == "coordination"
    assert squad.coordinator.model == "claude-sonnet-5-5"
    assert {w.model for w in squad.workers} == {"claude-haiku-5-5"}
    assert {w.role for w in squad.workers} == {"execution"}


def test_codex_roles_use_their_equivalents():
    plan = squads.plan_squads(_issues(1), family="codex")
    assert plan.general_coordinator.model == model_roles.resolve("codex", "planning")["model"]
    assert plan.squads[0].coordinator.model == "gpt-6.1-sol"
    assert plan.squads[0].workers[0].model == "gpt-6-luna"


def test_unknown_family_is_refused():
    with pytest.raises(model_roles.ModelRoleError):
        squads.plan_squads(_issues(1), family="nope")


# ---------------------------------------------------------------- plan: split and grouping


def test_a_group_larger_than_max_workers_is_split_into_squads():
    plan = squads.plan_squads(_issues(9), max_workers=4)
    assert [len(s.workers) for s in plan.squads] == [4, 4, 1]
    assert all(len(s.workers) <= 4 for s in plan.squads)
    assigned = [n for s in plan.squads for n in s.issues]
    assert sorted(assigned) == list(range(1, 10))
    assert len({s.id for s in plan.squads}) == 3


def test_each_worker_has_one_issue_and_max_workers_is_respected():
    plan = squads.plan_squads(_issues(5), max_workers=2)
    assert all(len(s.workers) <= 2 for s in plan.squads)
    assert all(len(w.issues) == 1 for s in plan.squads for w in s.workers)


def test_invalid_max_workers_is_refused():
    with pytest.raises(squads.SquadPlanError):
        squads.plan_squads(_issues(1), max_workers=0)


def test_grouping_by_area_and_by_label():
    issues = [
        {"number": 1, "area": "api"},
        {"number": 2, "labels": ["bug", "area:ui"]},
        {"number": 3, "labels": [{"name": "area:api"}]},
        {"number": 4},
    ]
    plan = squads.plan_squads(issues)
    by_name = {s.name: s.issues for s in plan.squads}
    assert by_name == {"api": (1, 3), "geral": (4,), "ui": (2,)}


def test_grouping_by_path_ownership_when_given():
    issues = [
        {"number": 1, "paths": ["simplicio_loop/dashboard/runs.py"]},
        {"number": 2, "paths": ["simplicio_loop/watcher247/tick.py"]},
        {"number": 3, "paths": ["simplicio_loop/dashboard/x.py"]},
    ]
    ownership = {"dashboard": ["simplicio_loop/dashboard/**"], "watcher": ["simplicio_loop/watcher247/*"]}
    plan = squads.plan_squads(issues, ownership=ownership)
    by_name = {s.name: s for s in plan.squads}
    assert by_name["dashboard"].issues == (1, 3)
    assert by_name["watcher"].issues == (2,)
    assert by_name["dashboard"].owned_paths == (
        "simplicio_loop/dashboard/runs.py",
        "simplicio_loop/dashboard/x.py",
    )


def test_shared_files_are_not_owned_by_any_squad():
    issues = [{"number": 1, "area": "a", "paths": ["a.py", "simplicio_loop/cli_impl.py", "CHANGELOG.md"]}]
    plan = squads.plan_squads(issues)
    assert plan.squads[0].owned_paths == ("a.py",)
    assert "simplicio_loop/cli_impl.py" in plan.shared_files
    assert "tests/conftest.py" in plan.shared_files


def test_a_path_claimed_by_two_squads_becomes_shared():
    issues = [
        {"number": 1, "area": "a", "paths": ["x.py", "only_a.py"]},
        {"number": 2, "area": "b", "paths": ["x.py"]},
    ]
    plan = squads.plan_squads(issues)
    owned = {s.name: s.owned_paths for s in plan.squads}
    assert owned == {"a": ("only_a.py",), "b": ()}
    assert "x.py" in plan.shared_files


# ---------------------------------------------------------------- plan: determinism


def test_output_is_deterministic_and_input_order_independent():
    issues = [
        {"number": 7, "area": "b", "body": "depends on #3"},
        {"number": 3, "area": "a"},
        {"number": 5, "area": "a", "paths": ["z.py", "y.py"]},
    ]
    first = _plan_dict(squads.plan_squads(issues))
    second = _plan_dict(squads.plan_squads(list(reversed(issues))))
    assert first == second
    assert first == _plan_dict(squads.plan_squads(issues))


def test_plan_is_frozen_and_json_serializable():
    plan = squads.plan_squads(_issues(2))
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.family = "codex"
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.squads[0].id = "x"
    payload = _plan_dict(plan)
    assert payload["schema"] == "simplicio.squad-plan/v1"
    assert payload["escalation"]["ladder"] == ["execution", "coordination", "planning"]
    assert payload["escalation"]["max_failures"] == 2
    roles = {(a["role"], a["model"], a["effort"]) for a in payload["agents"]}
    assert ("planning", "claude-opus-5-5", "high") in roles


def test_empty_issue_list_gives_an_empty_plan():
    plan = squads.plan_squads([])
    assert plan.squads == () and plan.merge_order == ()


def test_duplicate_issue_numbers_are_refused():
    with pytest.raises(squads.SquadPlanError):
        squads.plan_squads([{"number": 1}, {"number": 1}])


# ---------------------------------------------------------------- plan: merge order


def test_merge_order_is_topological_over_declared_dependencies():
    issues = [
        {"number": 10, "area": "a", "body": "Depends on #30"},
        {"number": 20, "area": "b", "body": "Parte de #10"},
        {"number": 30, "area": "c"},
        {"number": 40, "area": "a", "depends_on": [20]},
    ]
    plan = squads.plan_squads(issues)
    assert [m.issue for m in plan.merge_order] == [30, 10, 20, 40]
    squad_of = {n: s.id for s in plan.squads for n in s.issues}
    assert all(m.squad == squad_of[m.issue] for m in plan.merge_order)


def test_dependencies_outside_the_set_and_self_references_are_ignored():
    issues = [{"number": 2, "body": "Parte de #1429 e depende de #2"}, {"number": 1}]
    plan = squads.plan_squads(issues)
    assert [m.issue for m in plan.merge_order] == [1, 2]


def test_dependency_cycle_raises_a_typed_error():
    issues = [
        {"number": 1, "body": "depends on #2"},
        {"number": 2, "body": "depends on #3"},
        {"number": 3, "body": "depends on #1"},
        {"number": 4},
    ]
    with pytest.raises(squads.SquadCycleError) as exc:
        squads.plan_squads(issues)
    assert exc.value.cycle == (1, 2, 3)
    assert isinstance(exc.value, squads.SquadPlanError)


# ---------------------------------------------------------------- gate

APPROVAL = "APROVADO PELO SQUAD\n\nEvidencia: 12 passed. squash: feat(x): y (#1)"


def _commit(oid, headline, date, body=""):
    return {"oid": oid, "messageHeadline": headline, "messageBody": body, "committedDate": date}


def _comment(body, date, cid="c1"):
    return {"id": cid, "body": body, "createdAt": date, "author": {"login": "coord"}}


def test_approval_newer_than_last_commit_passes():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = squads.squad_gate(pr)
    assert result["approved"] is True
    assert result["approval_comment_id"] == "c1"
    assert result["last_commit_oid"] == "a"


def test_commit_after_approval_invalidates_it():
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("b", "fix: y", "2026-10-09T01:10:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = squads.squad_gate(pr)
    assert result["approved"] is False
    assert result["reason"] == "approval_older_than_commit"


@pytest.mark.parametrize("headline", [
    "Merge remote-tracking branch 'origin/main' into feat/x",
    "Merge branch 'main' into feat/x",
    "Merge branch 'origin/main' of github.com:o/r into feat/x",
    "Merge branch 'origin/main' into feat/x",
    "Merge origin/main into feat/x",
    "Merge main into feat/x",
])
def test_clean_merge_of_main_does_not_invalidate(headline):
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", headline, "2026-10-09T02:00:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = squads.squad_gate(pr)
    assert result["approved"] is True
    assert result["last_commit_oid"] == "a"


def test_merge_with_conflict_resolution_counts_as_a_change():
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", "Merge branch 'main' into feat/x", "2026-10-09T02:00:00Z",
                    body="# Conflicts:\n#\tsimplicio_loop/cli_impl.py"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert squads.squad_gate(pr)["approved"] is False


@pytest.mark.parametrize("headline", [
    "Merge origin/main into feat/x",
    "Merge main into feat/x",
    "Merge remote-tracking branch 'origin/main' into feat/x",
])
def test_every_clean_merge_form_with_conflicts_still_invalidates(headline):
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", headline, "2026-10-09T02:00:00Z", body="Conflicts:\n\ta.py"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert squad_gate_approved(pr) is False


def squad_gate_approved(pr):
    return squads.squad_gate(pr)["approved"]


@pytest.mark.parametrize("headline", [
    "Merge main-feature into feat/x",
    "Merge origin/mainline into feat/x",
    "Merge pull request #5 from o/main",
])
def test_lookalike_merge_titles_count_as_a_change(headline):
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", headline, "2026-10-09T02:00:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert squad_gate_approved(pr) is False


def test_merge_of_another_branch_counts_as_a_change():
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", "Merge branch 'feat/other' into feat/x", "2026-10-09T02:00:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert squads.squad_gate(pr)["approved"] is False


def test_no_approval_comment():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment("LGTM", "2026-10-09T01:05:00Z"),
                     _comment("> APROVADO PELO SQUAD (citado)", "2026-10-09T01:06:00Z")],
    }
    result = squads.squad_gate(pr)
    assert result["approved"] is False and result["reason"] == "no_approval"


def test_no_commits_and_bad_timestamps_fail_closed():
    assert squads.squad_gate({"commits": [], "comments": []})["reason"] == "no_commits"
    pr = {
        "commits": [_commit("a", "feat: x", "garbage")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = squads.squad_gate(pr)
    assert result["approved"] is False and result["reason"] == "unparseable_timestamp"


def test_gate_accepts_json_text():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert squads.squad_gate(json.dumps(pr))["approved"] is True


def test_only_the_newest_valid_approval_matters():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T00:30:00Z", "old"),
                     _comment(APPROVAL, "2026-10-09T01:30:00Z", "new")],
    }
    assert squads.squad_gate(pr)["approval_comment_id"] == "new"


# ---------------------------------------------------------------- async wrapper (fake gh)


class _FakeGh:
    def __init__(self, payload, returncode=0):
        self.payload, self.returncode, self.calls = payload, returncode, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.returncode, json.dumps(self.payload), "boom")


def test_async_wrapper_fetches_through_gh():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    fake = _FakeGh(pr)
    result = asyncio.run(squads.squad_gate_for_pr("o/r", 12, runner=fake))
    assert result["approved"] is True
    assert fake.calls[0] == ["gh", "pr", "view", "12", "--repo", "o/r", "--json", "commits,comments"]


def test_async_wrapper_raises_on_gh_failure():
    with pytest.raises(squads.SquadGateError):
        asyncio.run(squads.squad_gate_for_pr("o/r", 12, runner=_FakeGh({}, returncode=1)))
