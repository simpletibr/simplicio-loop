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
    assert plan.squads[0].coordinator.model == "gpt-5.5"
    assert plan.squads[0].workers[0].model == "gpt-5.6-luna"


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


def test_dependencies_lists_the_declared_edges_the_merge_order_uses():
    issues = [
        {"number": 10, "body": "Depends on #30 e parte de #20"},
        {"number": 20, "depends_on": [30]},
        {"number": 30},
        {"number": 40, "body": "Parte de #1429 e depende de #40"},
    ]
    assert squads.dependencies(issues) == {10: (20, 30), 20: (30,), 30: (), 40: ()}


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


# ---------------------------------------------------------------- plan: contracts (#1504, interfaces first)


def _squad_ids(plan):
    return {n: s.id for s in plan.squads for n in s.issues}


def test_cross_squad_dependency_edge_yields_a_contract():
    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "ui", "depends_on": [1]}]
    plan = squads.plan_squads(issues)
    ids = _squad_ids(plan)
    assert [(c.producer, c.consumer) for c in plan.contracts] == [(ids[1], ids[2])]
    contract = plan.contracts[0]
    assert contract.module_path.startswith(".simplicio-loop/contracts/")
    assert contract.signature.startswith("def ")


def test_no_dependency_means_no_contracts():
    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "ui"}]
    assert squads.plan_squads(issues).contracts == ()


def test_dependency_inside_one_squad_yields_no_contract():
    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "api", "depends_on": [1]}]
    plan = squads.plan_squads(issues)
    assert len(plan.squads) == 1
    assert plan.contracts == ()


def test_dependency_edge_across_split_squads_yields_a_contract():
    # same area, but max_workers=1 splits it into two squads
    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "api", "body": "Depends on #1"}]
    plan = squads.plan_squads(issues, max_workers=1)
    assert len(plan.squads) == 2 and len(plan.contracts) == 1


def test_several_issue_edges_between_the_same_squads_give_one_contract():
    issues = [
        {"number": 1, "area": "api"}, {"number": 2, "area": "api"},
        {"number": 3, "area": "ui", "depends_on": [1, 2]},
    ]
    plan = squads.plan_squads(issues)
    assert len(plan.contracts) == 1


def test_contracts_are_in_the_json_output_without_the_test_body():
    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "ui", "depends_on": [1]}]
    payload = _plan_dict(squads.plan_squads(issues))
    assert payload["schema"] == "simplicio.squad-plan/v1"
    assert len(payload["contracts"]) == 1
    entry = payload["contracts"][0]
    assert {"producer", "consumer", "module_path", "test_path", "signature", "function"} <= set(entry)
    assert "test_template" not in entry
    assert _plan_dict(squads.plan_squads(_issues(2)))["contracts"] == []


def test_plan_contracts_are_what_write_contracts_consumes(tmp_path):
    from simplicio_loop import squad_contracts

    issues = [{"number": 1, "area": "api"}, {"number": 2, "area": "ui", "depends_on": [1]}]
    plan = squads.plan_squads(issues)
    res = squad_contracts.write_contracts(tmp_path, plan.contracts)
    assert len(res["written"]) == 2 and (tmp_path / plan.contracts[0].module_path).is_file()


# ---------------------------------------------------------------- gate

OID_A = "a" * 40
APPROVAL = ("REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n\nEvidencia: 12 passed. squash: feat(x): y (#1)\n\n"
            f"<!-- simplicio-loop:squad-approval:{OID_A} -->")  # the approval of the commit "a" (M4, #1649: tied to the full head oid)


def _commit(oid, headline, date, body=""):
    return {"oid": (oid * 40)[:40], "messageHeadline": headline, "messageBody": body, "committedDate": date}


def _comment(body, date, cid="c1", login="coord", association=None):
    comment = {"id": cid, "body": body, "createdAt": date, "author": {"login": login}}
    if association is not None:
        comment["authorAssociation"] = association
    return comment


def _gate(pr, approvers=("coord",), **kwargs):
    """squad_gate with the squad coordinator's login authorized (the gate fails closed without an approver set)."""
    return squads.squad_gate(pr, approvers=approvers, **kwargs)


def test_approval_newer_than_last_commit_passes():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = _gate(pr)
    assert result["approved"] is True
    assert result["approval_comment_id"] == "c1"
    assert result["last_commit_oid"] == OID_A


def test_commit_after_approval_invalidates_it():
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("b", "fix: y", "2026-10-09T01:10:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = _gate(pr)
    assert result["approved"] is False
    assert result["reason"] == "approval_not_for_head"


@pytest.mark.parametrize("headline", [
    "Merge remote-tracking branch 'origin/main' into feat/x",
    "Merge branch 'main' into feat/x",
    "Merge origin/main into feat/x",
    "Merge main into feat/x",
])
def test_a_merge_of_main_is_a_new_head_and_needs_its_own_approval(headline):
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("e", headline, "2026-10-09T02:00:00Z"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert _gate(pr)["reason"] == "approval_not_for_head"
    pr["comments"].append(_comment(APPROVAL.replace(OID_A, "e" * 40), "2026-10-09T02:05:00Z", "c2"))
    result = _gate(pr)
    assert result["approved"] is True and result["last_commit_oid"] == "e" * 40 and result["approval_comment_id"] == "c2"


def test_a_new_commit_dated_before_the_approval_is_not_approved_M4():
    """The audit's reproduction: the committer date of the new head is older than the approval, and the head was never reviewed."""
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z"), _commit("b", "fix: y", "2020-01-01T00:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    result = _gate(pr)
    assert result["approved"] is False and result["reason"] == "approval_not_for_head"


def test_the_approval_marker_must_carry_the_full_head_oid_never_a_prefix_nor_a_longer_text():
    head = _commit("a", "feat: x", "2026-10-09T01:00:00Z")
    for marker in (OID_A[:7], OID_A[:39], "A" * 40, OID_A[:-1] + "b"):
        body = APPROVAL.replace(OID_A, marker)
        result = _gate({"commits": [head], "comments": [_comment(body, "2026-10-09T01:05:00Z")]})
        assert result["approved"] is False and result["reason"] == "approval_not_for_head", marker
    short = {"commits": [{"oid": "abc1234", "committedDate": "2026-10-09T01:00:00Z"}],
             "comments": [_comment(APPROVAL.replace(OID_A, "abc1234"), "2026-10-09T01:05:00Z")]}
    assert _gate(short)["reason"] == "head_unknown"  # the head itself has to be a full oid


def test_the_level_is_recomputed_from_the_files_of_the_diff_not_read_from_the_comment_M4():
    pr = {"commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")], "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")]}
    assert _gate({**pr, "files": [{"path": "src/app.py"}]})["approved"] is True  # level 1 on an ordinary diff
    for path in ("simplicio_loop/sandbox_guard.py", "simplicio_loop/watcher247/squad_flow.py", ".github/workflows/ci.yml",
                 "simplicio_loop/review_gate/gate.py"):
        result = _gate({**pr, "files": [{"path": "src/app.py"}, {"path": path}]})
        assert result["approved"] is False and result["reason"] == "level_below_diff" and result["level"] == 2, path


def test_merge_with_conflict_resolution_counts_as_a_change():
    pr = {
        "commits": [
            _commit("a", "feat: x", "2026-10-09T01:00:00Z"),
            _commit("m", "Merge branch 'main' into feat/x", "2026-10-09T02:00:00Z",
                    body="# Conflicts:\n#\tsimplicio_loop/cli_impl.py"),
        ],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert _gate(pr)["approved"] is False


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
    return _gate(pr)["approved"]


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
    assert _gate(pr)["approved"] is False


def test_no_approval_comment():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment("LGTM", "2026-10-09T01:05:00Z"),
                     _comment("> REVISÃO AUTOMÁTICA: APROVADA (nível 1) (citado)", "2026-10-09T01:06:00Z")],
    }
    result = _gate(pr)
    assert result["approved"] is False and result["reason"] == "no_approval"


def test_no_commits_and_a_head_without_a_full_oid_fail_closed():
    assert _gate({"commits": [], "comments": []})["reason"] == "no_commits"
    for oid in (None, "", "garbage", OID_A[:12]):
        pr = {"commits": [{"oid": oid, "committedDate": "2026-10-09T01:00:00Z"}], "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")]}
        result = _gate(pr)
        assert result["approved"] is False and result["reason"] == "head_unknown"


def test_a_head_longer_than_40_characters_is_head_unknown_even_when_its_first_40_are_a_full_oid():
    """A mutant read `head[:41]` with `match`: a 41-character head (right 40, one more) then passed as a full oid."""
    for oid in (OID_A + "a", OID_A + "\n", OID_A + "0" * 24, OID_A + " ", " " + OID_A):
        pr = {"commits": [{"oid": oid, "committedDate": "2026-10-09T01:00:00Z"}], "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")]}
        result = _gate(pr)
        assert result["approved"] is False and result["reason"] == "head_unknown", repr(oid)
    ok = {"commits": [{"oid": OID_A, "committedDate": "2026-10-09T01:00:00Z"}], "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")]}
    assert _gate(ok)["approved"] is True  # the same PR with exactly 40 characters is the approved one


def test_the_date_of_the_commit_does_not_matter_only_the_head_oid():
    pr = {"commits": [_commit("a", "feat: x", "garbage")], "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")]}
    assert _gate(pr)["approved"] is True
    assert _gate({**pr, "comments": [_comment(APPROVAL, "garbage")]})["approved"] is True


def test_gate_accepts_json_text():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z")],
    }
    assert _gate(json.dumps(pr))["approved"] is True


def test_only_the_newest_valid_approval_matters():
    pr = {
        "commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z")],
        "comments": [_comment(APPROVAL, "2026-10-09T00:30:00Z", "old"),
                     _comment(APPROVAL, "2026-10-09T01:30:00Z", "new")],
    }
    assert _gate(pr)["approval_comment_id"] == "new"


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
    result = asyncio.run(squads.squad_gate_for_pr("o/r", 12, runner=fake, approvers=["coord"]))
    assert result["approved"] is True
    assert fake.calls[0] == ["gh", "pr", "view", "12", "--repo", "o/r", "--json", "commits,comments,files"]


def test_async_wrapper_raises_on_gh_failure():
    with pytest.raises(squads.SquadGateError):
        asyncio.run(squads.squad_gate_for_pr("o/r", 12, runner=_FakeGh({}, returncode=1)))


# ---------------------------------------------------------------- who wrote the approval (#1534)


def _pr(*comments, commit_at="2026-10-09T01:00:00Z"):
    return {"commits": [_commit("a", "feat: x", commit_at)], "comments": list(comments)}


def test_approval_from_an_unauthorized_author_is_rejected():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="outsider"))
    result = _gate(pr)
    assert result["approved"] is False and result["reason"] == "unauthorized_approval"


def test_approval_from_an_authorized_author_is_accepted():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="coord"))
    assert _gate(pr)["approved"] is True


def test_authorized_login_matches_case_insensitively():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="Coord"))
    assert _gate(pr, approvers=["COORD"])["approved"] is True


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_trusted_association_authorizes_the_author(association):
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="maintainer", association=association))
    assert _gate(pr, approvers=(), trusted_associations=("OWNER", "MEMBER", "COLLABORATOR"))["approved"] is True


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "", None])
def test_untrusted_association_is_rejected(association):
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="outsider", association=association))
    assert _gate(pr, approvers=(), trusted_associations=("OWNER", "MEMBER", "COLLABORATOR"))["approved"] is False


def test_association_does_not_count_unless_the_caller_trusts_it():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="maintainer", association="OWNER"))
    assert _gate(pr, approvers=())["approved"] is False


@pytest.mark.parametrize("approvers", [None, (), [], set(), ("",)])
def test_no_approver_set_fails_closed(approvers):
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="coord"))
    result = squads.squad_gate(pr, approvers=approvers)
    assert result["approved"] is False and result["reason"] == "unauthorized_approval"


def test_gate_without_an_approvers_argument_fails_closed():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="coord"))
    assert squads.squad_gate(pr)["approved"] is False


def test_authorized_approval_of_another_head_is_still_rejected():
    pr = _pr(_comment(APPROVAL.replace(OID_A, "c" * 40), "2026-10-09T01:30:00Z", login="coord"))
    result = _gate(pr)
    assert result["approved"] is False and result["reason"] == "approval_not_for_head"


def test_a_newer_forged_approval_does_not_hide_the_authorized_one():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", "real", login="coord"),
             _comment(APPROVAL, "2026-10-09T01:30:00Z", "forged", login="outsider"))
    result = _gate(pr)
    assert result["approved"] is True and result["approval_comment_id"] == "real"


def test_a_forged_approval_does_not_revive_an_authorized_one_made_stale_by_a_commit():
    pr = {"commits": [_commit("a", "feat: x", "2026-10-09T01:00:00Z"), _commit("b", "fix: y", "2026-10-09T01:20:00Z")],
          "comments": [_comment(APPROVAL, "2026-10-09T01:05:00Z", "real", login="coord"),
                       _comment(APPROVAL, "2026-10-09T01:30:00Z", "forged", login="outsider")]}
    assert _gate(pr)["reason"] == "approval_not_for_head"


def test_marker_forged_inside_a_quoted_reply_by_another_user_is_rejected():
    quoted = "> REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n\nconcordo"
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", "real", login="outsider"),
             _comment(quoted, "2026-10-09T01:10:00Z", "quote", login="coord"))
    result = _gate(pr)
    assert result["approved"] is False and result["reason"] == "unauthorized_approval"


def test_comment_without_an_author_is_never_authorized():
    pr = _pr({"id": "x", "body": APPROVAL, "createdAt": "2026-10-09T01:05:00Z"},
             {"id": "y", "body": APPROVAL, "createdAt": "2026-10-09T01:06:00Z", "author": None})
    assert _gate(pr, approvers=["coord"], trusted_associations=("OWNER",))["approved"] is False


def test_unknown_association_name_is_rejected_up_front():
    with pytest.raises(ValueError):
        _gate(_pr(), trusted_associations=("ADMIN",))


@pytest.mark.parametrize("login", ["w", "e", "s", "wesley"])
def test_approvers_given_as_a_plain_string_is_one_login_not_its_characters(login):
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login=login))
    assert squads.squad_gate(pr, approvers="wesleysimplicio")["approved"] is False


def test_approvers_given_as_a_plain_string_matches_that_whole_login():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="WesleySimplicio"))
    assert squads.squad_gate(pr, approvers="wesleysimplicio")["approved"] is True


@pytest.mark.parametrize("approvers", [[None], [123], [b"coord"], [("coord",)]])
def test_non_string_approver_entries_never_authorize(approvers):
    for login in ("none", "123", "coord"):
        pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login=login))
        assert squads.squad_gate(pr, approvers=approvers)["approved"] is False


def test_unicode_case_folds_do_not_collide_with_ascii_logins():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="Kevin"))
    assert squads.squad_gate(pr, approvers=["kevin"])["approved"] is False


def test_association_must_be_the_exact_github_value():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="maintainer", association="member"))
    assert _gate(pr, approvers=(), trusted_associations=("MEMBER",))["approved"] is False


def test_trusted_association_as_a_plain_string_is_one_value_and_none_is_empty():
    pr = _pr(_comment(APPROVAL, "2026-10-09T01:05:00Z", login="maintainer", association="OWNER"))
    assert _gate(pr, approvers=(), trusted_associations="OWNER")["approved"] is True
    assert _gate(pr, approvers=(), trusted_associations=None)["approved"] is False
