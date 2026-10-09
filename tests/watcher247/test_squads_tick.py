"""The 24/7 watcher in squads (#1505): plan, workers, squad review, opt-in batch merge, role receipt."""
from __future__ import annotations

import json

import pytest

from simplicio_loop import model_roles
from simplicio_loop.watcher247 import config, squad_flow

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = "simplicio-a"
NUMBERS = range(1, 7)


def _view(number, *, approved_after_commit=True):
    commit, approval = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    if not approved_after_commit:
        commit, approval = approval, commit
    return {
        "files": [{"path": f"src/m{number}/app.py"}], "headRefOid": f"oid{number}",
        "commits": [{"oid": f"oid{number}", "committedDate": commit, "messageHeadline": "loop: x"}],
        "comments": [{"id": number, "createdAt": approval, "body": "APROVADO PELO SQUAD\n"}],
    }


@pytest.fixture
def six(env, monkeypatch):
    """Six admitted issues of one repo, a clone with a detectable test command, six PRs 101..106."""
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "6")
    monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
    clone = config.WORK / REPO
    (clone / ".git").mkdir(parents=True)
    (clone / "pytest.ini").write_text("[pytest]\n")

    def make(**kwargs):
        rows = [issue(n, f"Task {n}", body=f"Ajustar `src/m{n}/app.py` para o fluxo do watcher seguir o contrato descrito abaixo.",
                      **({"labels": ("loop:auto", "security")} if n == 3 else {})) for n in NUMBERS]
        fake = env(FakeRun({REPO: rows}, verify_pass=True, distinct_prs=True,
                           pr_views={100 + n: _view(n) for n in NUMBERS}, **kwargs))
        baseline()
        return fake
    return make


def _squads():
    return read_json(config.STATUS)["squads"][REPO]


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
    assert posted, "the squad coordinator posts APROVADO PELO SQUAD on the PR"


def test_review_rejects_a_pr_whose_verify_did_not_measure_tests(env, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
    fake = env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))  # no clone tests: UNVERIFIED
    baseline()
    run_tick()
    assert _squads()["approved"] == [] and list(_squads()["rejected"]) == ["101"]
    assert not [w for w in fake.api_writes if w[1].endswith("/issues/101/comments")]


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
        assert argv[argv.index("--match-head-commit") + 1] == f"oid{number - 100}"


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
    fake = env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))  # _view already carries an approval; no verified tests
    baseline()
    run_tick()
    assert fake.merges == [] and _squads()["approved"] == [] and _squads()["merge"] == "disabled"
