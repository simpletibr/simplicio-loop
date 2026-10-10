"""The watcher's verify command comes from ONE place: `verify` in `.simplicio-loop/loop.toml` of the default branch.

No detection, no fallback to the whole suite. A repo without `verify` has all its issues skipped as `verify_not_configured`.
"""
import pytest

from simplicio_loop.watcher247 import config, verify

from .fakes import FakeRun, baseline, issue, pr_row, read_json, run_tick, tasks

REPO = "simplicio-a"
TARGETED = "python3 -m pytest -q tests/x.py"
WITH_VERIFY = f'enabled = true\nverify = "{TARGETED}"\n'
WITHOUT_VERIFY = "enabled = true\n"
REVIEW = {"author": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "body": "troque o retorno para dict"}


# --- configured_command ---

@pytest.mark.parametrize("config_table,expected", [
    ({"enabled": True, "verify": TARGETED}, TARGETED),
    ({"verify": "  pytest tests/y.py \n"}, "pytest tests/y.py"),
    ({"verify": ""}, None),
    ({"verify": "   \t\n"}, None),
    ({"verify": 5}, None),
    ({"verify": True}, None),
    ({"verify": None}, None),
    ({"verify": ["pytest", "-q"]}, None),
    ({"verify": {"cmd": "pytest"}}, None),
    ({"enabled": True}, None),
    ({}, None),
    (None, None),
    ("verify = 'pytest'", None),
    (["verify"], None),
])
def test_configured_command(config_table, expected):
    assert verify.configured_command(config_table) == expected


def test_there_is_no_detection_left():
    assert not hasattr(verify, "detect_test_command")


# --- the tick ---

def _skipped():
    return read_json(config.STATUS)["skipped_issues"]


def test_a_repo_without_verify_processes_no_issue(env, capsys):
    fake = env(FakeRun({REPO: [issue(1), issue(2)]}, loop_toml={REPO: WITHOUT_VERIFY}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("gh", "repo", "clone") == [] and fake.ran("git", "push") == []
    assert _skipped() == {f"{REPO}#1": "verify_not_configured", f"{REPO}#2": "verify_not_configured"}
    assert read_json(config.STATUS)["phase"] == "idle"
    assert not config.CLAIMS.exists() or read_json(config.CLAIMS) == {}
    out = capsys.readouterr().out
    assert REPO in out and "verify" in out


def test_a_blank_verify_counts_as_not_configured(env):
    fake = env(FakeRun({REPO: [issue(1)]}, loop_toml={REPO: 'enabled = true\nverify = "  "\n'}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert _skipped() == {f"{REPO}#1": "verify_not_configured"}


def test_only_the_repo_without_verify_is_skipped(env):
    fake = env(FakeRun({"simplicio-b": [issue(2)], REPO: [issue(1)]}, loop_toml={"simplicio-b": WITHOUT_VERIFY}))
    baseline()
    run_tick()
    assert len(tasks(fake)) == 1 and "Issue #1" in tasks(fake)[0]
    assert _skipped() == {"simplicio-b#2": "verify_not_configured"}


def test_the_configured_command_is_what_turbo_verifies(env):
    fake = env(FakeRun({REPO: [issue(1)]}, loop_toml={REPO: WITH_VERIFY}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert argv[argv.index("--verify") + 1] == TARGETED
    assert argv.count("--verify") == 1
    assert f"MEASURED|verify_passed: `{TARGETED}`" in fake.ran("gh", "pr", "create")[0][-1]


def test_the_verify_comes_from_the_default_branch_not_from_the_clone(env):
    fake = env(FakeRun({REPO: [issue(1)]}, loop_toml={REPO: WITH_VERIFY}))
    baseline()
    local = config.WORK / REPO / ".simplicio-loop"  # a plan on loop/issue-N may edit this file (#1567)
    local.mkdir(parents=True)
    (config.WORK / REPO / ".git").mkdir()
    (local / "loop.toml").write_text('enabled = true\nverify = "true"\n')
    run_tick()
    argv = fake.turbo_argv[0]
    assert argv[argv.index("--verify") + 1] == TARGETED


def test_a_verify_only_in_the_clone_does_not_enable_the_repo(env):
    fake = env(FakeRun({REPO: [issue(1)]}, loop_toml={REPO: WITHOUT_VERIFY}))
    baseline()
    local = config.WORK / REPO / ".simplicio-loop"
    local.mkdir(parents=True)
    (config.WORK / REPO / ".git").mkdir()
    (local / "loop.toml").write_text(WITH_VERIFY)
    run_tick()
    assert fake.turbo_argv == []
    assert _skipped() == {f"{REPO}#1": "verify_not_configured"}


def test_a_review_fix_is_skipped_without_verify_and_runs_once_it_is_configured(env):
    prs = dict(prs=[pr_row(9, "loop/issue-7", review="CHANGES_REQUESTED")],
               pr_views={9: {"reviews": [REVIEW], "files": [{"path": "app.py"}], "statusCheckRollup": []}})
    fake = env(FakeRun({REPO: [issue(7)]}, loop_toml={REPO: WITHOUT_VERIFY}, **prs))
    baseline(f"{REPO}#7")  # the issue is old, the review is the new work
    run_tick()
    assert fake.turbo_argv == []
    assert _skipped() == {f"{REPO}#7": "verify_not_configured"}
    assert f"{REPO}#7" in read_json(config.FIXES)["queued"]  # not lost: it waits for the repo to configure verify
    fake = env(FakeRun({REPO: [issue(7)]}, loop_toml={REPO: WITH_VERIFY}, **prs))
    run_tick()
    assert len(fake.turbo_argv) == 1 and "troque o retorno para dict" in tasks(fake)[0]
    argv = fake.turbo_argv[0]
    assert argv[argv.index("--verify") + 1] == TARGETED


# --- the merge train ---

def _view(number):
    commit, approval = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    # Hermetic: use proper 40-character SHAs for squad_gate
    oid = f"abc123def456789012345678901234567890{number:04d}"[:40]
    # Hermetic: include the OID marker in the approval comment so squad_gate can find it
    approval_body = f"REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n<!-- simplicio-loop:squad-approval:{oid} -->"
    return {
        "files": [{"path": f"src/m{number}/app.py"}], "headRefOid": oid,
        "commits": [{"oid": oid, "committedDate": commit, "messageHeadline": "loop: x"}],
        "comments": [{"id": number, "createdAt": approval, "body": approval_body,
                      "author": {"login": "squad-bot"}, "authorAssociation": "MEMBER"}],
    }


def test_the_merge_train_runs_the_verify_of_the_repo(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    rows = [issue(n, f"Task {n}", body=f"Ajustar `src/m{n}/app.py` para o fluxo do watcher seguir o contrato descrito abaixo.")
            for n in (1, 2)]
    fake = env(FakeRun({REPO: rows}, loop_toml={REPO: WITH_VERIFY}, distinct_prs=True,
                       pr_views={101: _view(1), 102: _view(2)}))
    baseline()
    run_tick()
    assert fake.merges == [101, 102]
    assert fake.ran("python3", "-m", "pytest") == [["python3", "-m", "pytest", "-q", "tests/x.py"]]
