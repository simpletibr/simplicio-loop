"""The 24/7 watcher in squads (#1505): plan, workers, squad review, opt-in batch merge, role receipt."""
from __future__ import annotations

import asyncio
import json

import pytest

from simplicio_loop import model_roles
from simplicio_loop.watcher247 import config, squad_flow, verify

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = "simplicio-a"
NUMBERS = range(1, 7)


def _view(number, *, approved_after_commit=True, author="squad-bot"):
    commit, approval = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    reviewed = oid(number) if approved_after_commit else "f" * 40  # a stale approval is one made for another head (M4, #1649)
    return {
        "files": [{"path": f"src/m{number}/app.py"}], "headRefOid": oid(number),
        "commits": [{"oid": oid(number), "committedDate": commit, "messageHeadline": "loop: x"}],
        "comments": [{"id": number, "createdAt": approval, "author": {"login": author}, "authorAssociation": "MEMBER",
                      "body": f"REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n\n<!-- simplicio-loop:squad-approval:{reviewed} -->"}],
    }


def oid(number):
    return f"{number:040x}"


@pytest.fixture
def six(env, monkeypatch):
    """Six admitted issues of one repo, a pre-cloned repo, six PRs 101..106."""
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "6")
    monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
    clone = config.WORK / REPO
    (clone / ".git").mkdir(parents=True)

    def make(**kwargs):
        rows = [issue(n, f"Task {n}", body=f"Ajustar `src/m{n}/app.py` para o fluxo do watcher seguir o contrato descrito abaixo.",
                      **({"labels": ("loop:auto", "security")} if n == 3 else {})) for n in NUMBERS]
        fake = env(FakeRun({REPO: rows}, distinct_prs=True,
                           pr_views={100 + n: _view(n) for n in NUMBERS}, **kwargs))
        baseline()
        return fake
    return make


def _squads():
    return read_json(config.STATUS)["squads"][REPO]


def _opens_unverified(*args, **kwargs):
    """A worker that opened its PR without a measured pass: the tick never does it now (no verify, no work); the review still refuses it."""
    return verify.Decision("pr", verify.UNVERIFIED)


def test_six_issues_form_two_squads_of_up_to_four_workers_and_one_coordinator(six):
    six()
    run_tick()
    squads = _squads()["squads"]
    assert [len(s["workers"]) for s in squads] == [4, 2]
    assert all(s["coordinator"].endswith("-coord") for s in squads)
    assert sorted(i for s in squads for i in s["issues"]) == list(NUMBERS)


def test_without_auto_merge_squad_approves_but_nothing_merges(six):
    fake = six()
    run_tick()
    assert _squads()["approved"] == [101, 102, 103, 104, 105, 106]
    assert _squads()["merge"] == "disabled"
    assert fake.merges == [] and fake.tests_run == 0
    assert fake.ran("git", "merge") == []
    posted = [w for w in fake.api_writes if w[0] == "POST" and w[1].endswith("/issues/101/comments")]
    assert posted, "the squad coordinator posts REVISÃO AUTOMÁTICA: APROVADA (nível 1) on the PR"


def test_review_rejects_a_pr_whose_verify_did_not_measure_tests():
    outcome = squad_flow.Outcome("https://github.com/simpletibr/simplicio-a/pull/101", "UNVERIFIED|no_test_command", [])
    review = asyncio.run(squad_flow._review(REPO, None, None, 1, outcome, None, None))  # it answers before any gh call
    assert review == {"pr": 101, "issue": 1, "approved": False, "reasons": ["tests not measured green"]}


def test_auto_merge_merges_in_batches_and_respects_the_squad_gate(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six()
    fake.pr_views[103] = _view(3, approved_after_commit=False)  # approval older than the last commit: gate says no
    run_tick()
    assert fake.merges == [101, 102, 104, 105, 106]
    assert fake.tests_run == 2  # one cumulative test per batch of up to four
    assert _squads()["merged"] == [101, 102, 104, 105, 106]
    assert _squads()["gate_blocked"] == [103]


def test_red_batch_is_bisected_and_nothing_red_is_merged(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six(train_ok=False)
    run_tick()
    assert fake.merges == []
    assert sorted(_squads()["failed"]) == [101, 102, 103, 104, 105, 106]


def test_execution_report_carries_role_model_and_effort_of_each_agent(six):
    six()
    run_tick()
    path = config.ROOT / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json"
    report = json.loads(path.read_text())
    agents = [t["agent"] for t in report["tasks"] if t.get("agent")]
    assert report["consolidated"]["tasks_by_role"] == {"coordination": 3, "execution": 5, "planning": 1}
    for agent in agents:
        assert agent == {"role": agent["role"], **model_roles.resolve("claude", agent["role"])}
    by_issue = {t["issue"]: t["agent"]["role"] for t in report["tasks"] if t.get("agent") and t["issue"]}
    assert by_issue[f"{REPO}#3"] == "coordination"  # the security issue is routed to coordination
    assert all(by_issue[f"{REPO}#{n}"] == "execution" for n in (1, 2, 4, 5, 6))


def test_review_rejects_a_pr_that_touches_a_shared_file(six):
    fake = six()
    fake.pr_views[102]["files"].append({"path": "pyproject.toml"})
    run_tick()
    assert 102 not in _squads()["approved"] and "pyproject.toml" in _squads()["rejected"]["102"][0]


def test_auto_merge_pins_each_merge_to_the_reviewed_head_commit(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six()
    run_tick()
    merges = {int(argv[3]): argv for argv in fake.ran("gh", "pr", "merge")}
    assert sorted(merges) == [101, 102, 103, 104, 105, 106]
    for number, argv in merges.items():
        assert argv[argv.index("--match-head-commit") + 1] == oid(number - 100)


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "1 ", "garbage"])
def test_auto_merge_is_off_unless_exactly_one(value):
    assert squad_flow.auto_merge_enabled({} if value is None else {squad_flow.AUTO_MERGE_ENV: value}) is False
    assert squad_flow.auto_merge_enabled({squad_flow.AUTO_MERGE_ENV: "1"}) is True


def test_a_dependency_cycle_between_issues_does_not_stop_the_plan():
    rows = [{"number": 1, "title": "a", "body": "depende de #2 `src/a/x.py`"},
            {"number": 2, "title": "b", "body": "depends on #1 `src/b/x.py`"}]
    plan = squad_flow.plan_repo(REPO, rows, "claude")
    assert sorted(i for s in plan.plan.squads for i in s.issues) == [1, 2]


def test_paths_from_an_issue_body_stay_inside_the_clone():
    body = "`src/ok.py` `../../etc/passwd.py` `/etc/shadow.py` `~/x.py` `a/../../b.py`"
    assert squad_flow._issue_row({"number": 1, "body": body})["paths"] == ["src/ok.py"]


def test_a_forged_approval_comment_cannot_merge_a_pr_the_squad_did_not_review_green(env, monkeypatch):
    """squad_gate checks the phrase, not the author; the merge candidates come only from the watcher's own review."""
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setattr(verify, "decide", _opens_unverified)
    fake = env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))  # _view already carries an approval; no verified tests
    baseline()
    run_tick()
    assert fake.merges == [] and _squads()["approved"] == [] and _squads()["merge"] == "disabled"


def test_auto_merge_never_merges_an_approval_written_by_an_outsider(six, monkeypatch):
    """#1534: the gate checks who wrote the approval; the outsider's phrase is not the squad coordinator's."""
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six()
    fake.pr_views[103] = _view(3, author="outsider")
    run_tick()
    assert 103 not in fake.merges and fake.merges == [101, 102, 104, 105, 106]
    assert _squads()["gate_blocked"] == [103]


def test_auto_merge_with_every_approval_from_an_outsider_merges_nothing(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six()
    fake.pr_views = {pr: _view(pr - 100, author="outsider") for pr in fake.pr_views}
    run_tick()
    assert fake.merges == [] and fake.tests_run == 0
    assert _squads()["gate_blocked"] == [101, 102, 103, 104, 105, 106]


def test_auto_merge_fails_closed_when_the_watcher_login_is_unknown(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six(login=None)
    run_tick()
    assert fake.merges == [] and _squads()["gate_blocked"] == [101, 102, 103, 104, 105, 106]


def test_the_watcher_login_is_looked_up_once_per_tick_and_only_when_merging(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    fake = six()
    run_tick()
    assert len(fake.ran("gh", "api", "user")) == 1
    monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE")
    fake = six()
    run_tick()
    assert fake.ran("gh", "api", "user") == []


@pytest.mark.parametrize("failure", [TimeoutError("gh api user timed out"), FileNotFoundError("gh")])
def test_own_login_is_empty_when_gh_hangs_or_is_missing(monkeypatch, failure):
    """#1534: a failed lookup only blocks the merge (empty login = fail closed); it must not abort the tick."""
    async def boom(*args, **kwargs):
        raise failure
    monkeypatch.setattr(squad_flow.proc, "run", boom)
    assert asyncio.run(squad_flow.own_login()) == ""


# --- #1565: SIMPLICIO_247_SQUADS_BASELINE=1 turns the squads-v2 rules off, for the "before" run of the #1549 comparison ---

BASELINE = squad_flow.BASELINE_ENV


def _report():
    path = config.ROOT / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json"
    return json.loads(path.read_text())


def _starting_roles():
    return {t["issue"]: t["agent"]["role"] for t in _report()["tasks"] if t.get("agent") and t.get("issue")}


def _cross_squad_rows():
    return [{"number": 1, "title": "a", "body": "`src/a/x.py`", "labels": [{"name": "area:a"}]},
            {"number": 2, "title": "b", "body": "depende de #1 `src/b/x.py`", "labels": [{"name": "area:b"}]}]


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "1 ", " 1", "garbage", "2", "on"])
def test_baseline_is_off_unless_exactly_one(value):
    assert squad_flow.baseline_enabled({} if value is None else {BASELINE: value}) is False
    assert squad_flow.baseline_enabled({BASELINE: "1"}) is True


def test_the_default_mode_is_v2_in_the_plan_the_status_and_the_report(six):
    six()
    run_tick()
    assert _squads()["mode"] == "v2" and _report()["mode"] == "v2"
    assert squad_flow.plan_repo(REPO, [{"number": 1, "title": "a", "body": ""}], "claude").mode == "v2"


def test_baseline_mode_is_recorded_in_the_status_and_in_the_report(six, monkeypatch):
    monkeypatch.setenv(BASELINE, "1")
    six()
    run_tick()
    assert _squads()["mode"] == "baseline" and _report()["mode"] == "baseline"


def test_a_value_other_than_exactly_one_stays_v2(six, monkeypatch):
    monkeypatch.setenv(BASELINE, "true")
    six()
    run_tick()
    assert _squads()["mode"] == "v2" and _starting_roles()[f"{REPO}#3"] == "coordination"


def test_baseline_turns_routing_off_every_worker_starts_at_execution(six, monkeypatch):
    monkeypatch.setenv(BASELINE, "1")
    six()
    run_tick()
    assert _starting_roles() == {f"{REPO}#{n}": "execution" for n in NUMBERS}  # #3 is a security issue: v2 would start it at coordination


def test_baseline_routing_off_in_the_plan_itself_and_on_by_default():
    rows = [{"number": 3, "title": "sec", "body": "`src/m3/app.py`", "labels": [{"name": "security"}]}]
    assert squad_flow.plan_repo(REPO, rows, "claude").routed == {3: "coordination"}
    assert squad_flow.plan_repo(REPO, rows, "claude", mode="baseline").routed == {3: "execution"}


def test_baseline_turns_the_merge_batch_off_one_pr_per_train_through_the_same_code_path(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv(BASELINE, "1")
    seen = []
    real = squad_flow.merge_train.plan_train
    monkeypatch.setattr(squad_flow.merge_train, "plan_train", lambda *a, **k: seen.append(k.get("max_batch")) or real(*a, **k))
    fake = six()
    run_tick()
    assert fake.merges == [101, 102, 103, 104, 105, 106]  # the same PRs in the same order as v2
    assert fake.tests_run == 6  # v2: 2 (one per batch of up to four); baseline: one cumulative test per PR
    assert seen == [1] and _squads()["merged"] == [101, 102, 103, 104, 105, 106]


def test_v2_keeps_the_batch_of_four(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    seen = []
    real = squad_flow.merge_train.plan_train
    monkeypatch.setattr(squad_flow.merge_train, "plan_train", lambda *a, **k: seen.append(k.get("max_batch")) or real(*a, **k))
    fake = six()
    run_tick()
    assert fake.tests_run == 2 and seen == [squad_flow.merge_train.DEFAULT_MAX_BATCH]


def test_baseline_turns_the_cross_squad_contracts_off():
    v2 = squad_flow.plan_repo(REPO, _cross_squad_rows(), "claude")
    assert len(v2.plan.squads) == 2 and len(v2.plan.contracts) == 1  # the edge between two squads has a contract
    base = squad_flow.plan_repo(REPO, _cross_squad_rows(), "claude", mode="baseline")
    assert len(base.plan.squads) == 2 and base.plan.contracts == ()
    assert [step.issue for step in base.plan.merge_order] == [1, 2] and base.deps == {1: (), 2: (1,)}  # the declared order stays


def test_baseline_keeps_the_squads_the_ownership_and_the_dependency_order():
    v2 = squad_flow.plan_repo(REPO, _cross_squad_rows(), "claude")
    base = squad_flow.plan_repo(REPO, _cross_squad_rows(), "claude", mode="baseline")
    assert [(s.id, s.issues, s.owned_paths) for s in base.plan.squads] == [(s.id, s.issues, s.owned_paths) for s in v2.plan.squads]
    assert base.plan.shared_files == v2.plan.shared_files and base.plan.merge_order == v2.plan.merge_order


# The switch can only turn v2 rules off. It never enables a merge and never loosens an approval rule.


@pytest.mark.parametrize("auto_merge", [None, "", "0", "true", "yes", "garbage"])
def test_baseline_never_merges_without_exactly_one_in_auto_merge(six, monkeypatch, auto_merge):
    monkeypatch.setenv(BASELINE, "1")
    if auto_merge is None:
        monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
    else:
        monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", auto_merge)
    fake = six()
    run_tick()
    assert fake.merges == [] and fake.tests_run == 0 and fake.ran("git", "merge") == []
    assert _squads()["merge"] == "disabled" and _squads()["mode"] == "baseline" and fake.ran("gh", "api", "user") == []


def test_the_baseline_switch_does_not_turn_auto_merge_on():
    assert squad_flow.auto_merge_enabled({BASELINE: "1"}) is False
    assert squad_flow.auto_merge_enabled({BASELINE: "1", squad_flow.AUTO_MERGE_ENV: "true"}) is False
    assert squad_flow.auto_merge_enabled({squad_flow.AUTO_MERGE_ENV: "1"}) is True


def test_baseline_merges_an_approval_only_from_the_watcher_own_login(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv(BASELINE, "1")
    fake = six()
    fake.pr_views = {pr: _view(pr - 100, author="outsider") for pr in fake.pr_views}
    run_tick()
    assert fake.merges == [] and fake.tests_run == 0
    assert _squads()["gate_blocked"] == [101, 102, 103, 104, 105, 106] and _squads()["merged"] == []


def test_baseline_with_an_unknown_login_fails_closed(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv(BASELINE, "1")
    fake = six(login=None)
    run_tick()
    assert fake.merges == [] and _squads()["gate_blocked"] == [101, 102, 103, 104, 105, 106]


def test_baseline_keeps_the_gate_the_review_and_the_head_pin(six, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv(BASELINE, "1")
    fake = six()
    fake.pr_views[103] = _view(3, approved_after_commit=False)  # the approval is older than the last commit
    fake.pr_views[102]["files"].append({"path": "pyproject.toml"})  # a shared file
    run_tick()
    assert fake.merges == [101, 104, 105, 106]
    assert _squads()["gate_blocked"] == [103] and 102 not in _squads()["approved"] and "102" in _squads()["rejected"]
    for argv in fake.ran("gh", "pr", "merge"):
        assert argv[argv.index("--match-head-commit") + 1] == oid(int(argv[3]) - 100)


def test_baseline_without_measured_tests_approves_nothing(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv(BASELINE, "1")
    monkeypatch.setattr(verify, "decide", _opens_unverified)
    fake = env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))  # no verified tests
    baseline()
    run_tick()
    assert fake.merges == [] and _squads()["approved"] == [] and _squads()["merge"] == "disabled"


@pytest.mark.parametrize("mode", ["v2", "baseline"])
def test_baseline_merges_exactly_the_prs_v2_merges_for_the_same_approvals(six, monkeypatch, mode):
    """Only the grouping into trains differs: both modes give the same merged and blocked PRs (the same literal, so equal)."""
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    if mode == "baseline":
        monkeypatch.setenv(BASELINE, "1")
    else:
        monkeypatch.delenv(BASELINE, raising=False)
    fake = six()
    fake.pr_views[103] = _view(3, approved_after_commit=False)
    fake.pr_views[105] = _view(5, author="outsider")
    run_tick()
    assert _squads()["mode"] == mode
    assert (fake.merges, _squads()["approved"], _squads()["gate_blocked"], _squads()["rejected"]) == (
        [101, 102, 104, 106], [101, 102, 103, 104, 105, 106], [103, 105], {})


def test_no_merge_or_approval_function_reads_the_baseline_switch():
    """A tripwire, beside the behavior tests above: the approval, the gate and the merge rule do not mention the mode."""
    import inspect
    import re
    mode = re.compile(r"baseline|\.mode\b|current_mode", re.IGNORECASE)
    for fn in (squad_flow._review, squad_flow.auto_merge_enabled, squad_flow.own_login, squad_flow._train_test, squad_flow._merge):
        assert not mode.search(inspect.getsource(fn)), fn.__name__  # `_merge` only takes the batch size, from the plan
