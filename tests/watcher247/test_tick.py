"""Tick-level tests of the 24/7 watcher: every subprocess is answered by FakeRun."""
from __future__ import annotations

import asyncio
import io
import json
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import config, proc, state, subscription, tick
from simplicio_loop.watcher247.__main__ import main as watcher_main

FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)
PR_URL = "https://github.com/simpletibr/simplicio-a/pull/9"


class FakeRun:
    """Answers gh, git and turbo by argv and records what ran concurrently."""

    def __init__(self, issues, *, turbo_ok=True, diff=True, delay=0.0, files=None, verify=None):
        self.issues = issues  # repo name -> list of issue dicts
        self.turbo_ok = turbo_ok
        self.diff = diff
        self.delay = delay
        self.files = files or {}  # written into the clone: what the target repo looks like
        self.verify = verify  # turbo's "verify" report; None means turbo reports no verify at all
        self.calls = []
        self.comments = []
        self.turbo_active = 0
        self.max_turbo = 0
        self.turbo_argv = []
        self.turbo_timeouts = []
        self.repo_active = {}
        self.max_repo_active = 0

    def ran(self, *prefix):
        return [a for a in self.calls if a[: len(prefix)] == list(prefix)]

    def _enter(self, repo):
        self.repo_active[repo] = self.repo_active.get(repo, 0) + 1
        self.max_repo_active = max(self.max_repo_active, self.repo_active[repo])

    async def __call__(self, argv, timeout=120, cwd=None):
        argv = list(argv)
        self.calls.append(argv)
        repo = Path(cwd).name if cwd else ""
        head = argv[:3]
        if head == ["gh", "repo", "list"]:
            rows = [{"name": n, "isArchived": False, "defaultBranchRef": {"name": "main"}} for n in self.issues]
            return proc.Result(0, json.dumps(rows))
        if head == ["gh", "issue", "list"]:
            name = argv[argv.index("--repo") + 1].split("/")[1]
            return proc.Result(0, json.dumps(self.issues[name]))
        if head == ["gh", "issue", "comment"]:
            name = argv[argv.index("--repo") + 1].split("/")[1]
            self.comments.append((name, int(argv[3]), argv[argv.index("--body") + 1]))
            return proc.Result(0)
        if head == ["gh", "repo", "clone"]:
            (Path(argv[4]) / ".git").mkdir(parents=True)
            for name, text in self.files.items():
                (Path(argv[4]) / name).write_text(text)
            return proc.Result(0)
        if head == ["gh", "pr", "create"]:
            return proc.Result(0, PR_URL + "\n")
        if argv[0] == "simplicio-loop" and argv[1] == "turbo":
            self.turbo_argv.append(argv)
            self.turbo_timeouts.append(timeout)
            self.turbo_active += 1
            self.max_turbo = max(self.max_turbo, self.turbo_active)
            await asyncio.sleep(self.delay)
            self.turbo_active -= 1
            doc = {"schema": "simplicio.turbo/v1", "status": "ok"} if self.turbo_ok else {"status": "failed", "detail": "boom"}
            if self.verify is not None:
                command = argv[argv.index("--verify") + 1] if "--verify" in argv else None
                doc["verify"] = {"command": command, **self.verify}
                if not self.verify["passed"]:
                    doc["status"] = "failed"
            return proc.Result(0 if doc["status"] == "ok" else 1, json.dumps(doc))
        if argv[0] == "git":
            return self._git(argv, repo)
        raise AssertionError(f"unexpected argv {argv}")

    def _git(self, argv, repo):
        sub = argv[1]
        if sub == "config" and argv[2:] == ["user.email"]:
            return proc.Result(1)
        if sub == "checkout":
            self._enter(repo)  # from checkout until the diff check, the working tree is in use
            return proc.Result(0)
        if sub == "status":
            if not self.diff:
                self.repo_active[repo] -= 1
            return proc.Result(0, " M app.py\n?? .simplicio/x\n" if self.diff else "")
        if sub == "diff":
            return proc.Result(0, "app.py\n")
        return proc.Result(0)  # config, fetch, add, reset, commit, push


def issue(number, title="Fix thing", labels=()):
    return {"number": number, "title": title, "body": "body", "labels": [{"name": n} for n in labels]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    original = config.STATE_DIR
    config.set_state_dir(tmp_path)
    monkeypatch.setattr(state, "now", lambda: FIXED)
    monkeypatch.delenv("SIMPLICIO_247_CONCURRENCY", raising=False)

    async def active():
        return {"active": True, "reason": "ok"}

    monkeypatch.setattr(subscription, "mcp_subscription", active)

    def install(fake):
        monkeypatch.setattr(proc, "run", fake)
        return fake

    yield install
    config.set_state_dir(original)


def run_tick(**kwargs):
    asyncio.run(tick.tick(**kwargs))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def read_json(path):
    return json.loads(path.read_text())


def baseline(*idents):
    write_json(config.BASELINE, {"created_at": "x", "issues": list(idents)})


def test_first_tick_writes_baseline_only(env):
    fake = env(FakeRun({"simplicio-a": [issue(1), issue(2)]}))
    run_tick()
    assert read_json(config.BASELINE)["issues"] == ["simplicio-a#1", "simplicio-a#2"]
    assert fake.ran("simplicio-loop") == []
    assert fake.comments == []
    assert read_json(config.STATUS)["phase"] == "baselined"
    assert not config.CLAIMS.exists()


def test_baselined_issue_is_never_processed(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline("simplicio-a#1")
    run_tick()
    assert fake.ran("simplicio-loop") == []
    assert read_json(config.STATUS)["phase"] == "idle"


def test_exactly_one_due_issue_at_concurrency_one(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)], "simplicio-b": [issue(2)], "simplicio-c": [issue(3)]}, diff=False))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 1
    claims = read_json(config.CLAIMS)
    assert list(claims) == ["simplicio-a#1"]
    status = read_json(config.STATUS)
    assert status["phase"] == "processed" and status["last"] == "simplicio-a#1"


def test_turbo_ok_commits_opens_pr_and_comments_url(env):
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--repo") + 1] == str(config.WORK / "simplicio-a")
    assert argv[argv.index("--provider") + 1] == "openrouter"
    task = argv[argv.index("--task") + 1]
    assert "Issue #7: Add x" in task and "Protocolo Simplicio-Loop, nesta ordem" in task and "50 pontos" not in task
    assert fake.turbo_timeouts == [900]
    commit = fake.ran("git", "commit")[0]
    assert commit[3] == "loop: Add x\n\nCloses #7\n"
    assert fake.ran("git", "add", "-A") and fake.ran("git", "reset", "-q", "--", ".simplicio-loop", ".simplicio")
    assert fake.ran("git", "push", "-u", "origin", "loop/issue-7")
    pr = fake.ran("gh", "pr", "create")[0]
    assert pr[pr.index("--base") + 1] == "main" and pr[pr.index("--head") + 1] == "loop/issue-7"
    assert any(PR_URL in body for _, number, body in fake.comments if number == 7)
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["pr"] == PR_URL and claim["turbo_status"] == "ok"
    assert (config.LOGS / "simplicio-a-7-1.log").exists()


def test_turbo_ok_without_diff_is_done_no_diff(env):
    fake = env(FakeRun({"simplicio-a": [issue(4)]}, diff=False))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("git", "commit") == []
    claim = read_json(config.CLAIMS)["simplicio-a#4"]
    assert claim["status"] == "done_no_diff" and claim["pr"] is None
    assert any("sem diff" in body for _, _, body in fake.comments)


def test_first_failure_schedules_retry_in_six_hours(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["attempts"] == 1 and claim["error"] == "boom"
    assert claim["next_try_at"] == state.iso(FIXED + timedelta(hours=6))
    assert not any("parou" in body for _, _, body in fake.comments)


def test_retry_is_not_due_before_six_hours(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED + timedelta(hours=6))}})
    run_tick()
    assert fake.turbo_argv == []


def test_second_failure_is_dead_with_stop_comment(env):
    fake = env(FakeRun({"simplicio-a": [issue(5)]}, turbo_ok=False))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED)}})
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "dead" and claim["attempts"] == 2
    assert any("parou" in body and number == 5 for _, number, body in fake.comments)
    run_tick()  # dead is final
    assert len(fake.turbo_argv) == 1


def test_no_subscription_processes_nothing(env, monkeypatch):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()

    async def inactive():
        return {"active": False, "reason": "subscription_required"}

    monkeypatch.setattr(subscription, "mcp_subscription", inactive)
    run_tick()
    assert fake.calls == []
    status = read_json(config.STATUS)
    assert status["phase"] == "subscription_required"
    assert status["subscription"]["reason"] == "subscription_required"


def test_stop_file_idles(env):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    config.STOP.write_text("")
    run_tick()
    assert fake.calls == []
    status = read_json(config.STATUS)
    assert status["phase"] == "stopped" and status["stopped"] is True


def test_skip_labels_are_never_processed(env):
    fake = env(FakeRun({"simplicio-a": [issue(1, labels=["wontfix"]), issue(2, labels=["simplicio-loop:skip"])]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert read_json(config.CLAIMS) == {"simplicio-a#1": {"status": "skipped"}, "simplicio-a#2": {"status": "skipped"}}


def test_in_flight_equals_concurrency(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    names = ["simplicio-a", "simplicio-b", "simplicio-c", "simplicio-d"]
    fake = env(FakeRun({n: [issue(i)] for i, n in enumerate(names, 1)}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert fake.max_turbo == 2
    assert len(fake.turbo_argv) == 2
    assert read_json(config.STATUS)["processed"] == ["simplicio-a#1", "simplicio-b#2"]


def test_same_repo_issues_never_overlap(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1), issue(2)]}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 2
    assert fake.max_turbo == 1
    assert fake.max_repo_active == 1
    assert set(read_json(config.CLAIMS)) == {"simplicio-a#1", "simplicio-a#2"}


def test_different_repos_do_overlap(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1)], "simplicio-b": [issue(2)]}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert fake.max_turbo == 2


def test_dry_run_reads_but_writes_nothing(env, tmp_path):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    before = sorted(p.name for p in tmp_path.iterdir())
    asyncio.run(watcher_main(once=True, dry_run=True))
    assert fake.turbo_argv == [] and fake.comments == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_tick_error_is_recorded_in_status(env, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("gh exploded")

    env(FakeRun({}))
    monkeypatch.setattr(tick.github, "repos", boom)
    assert asyncio.run(watcher_main(once=True)) == 0
    status = read_json(config.STATUS)
    assert status["phase"] == "error" and "gh exploded" in status["error"]


# --- dirty() -----------------------------------------------------------------


@pytest.mark.parametrize("porcelain,expected", [
    ("", False),
    ("?? .simplicio-loop/state.json\n?? .simplicio/x\n", False),
    (" M .gitignore\n", False),
    (" M src/app.py\n", True),
    ("?? .simplicio/x\n M src/app.py\n", True),
])
def test_dirty(env, porcelain, expected):
    async def fake(argv, timeout=120, cwd=None):
        return proc.Result(0, porcelain)

    env(fake)
    assert asyncio.run(tick.dirty(Path("/x"))) is expected


def test_parse_turbo_variants():
    assert tick.parse_turbo("") == {}
    assert tick.parse_turbo('{"status": "ok"}') == {"status": "ok"}
    assert tick.parse_turbo('noise\n{"schema": "s", "status": "ok"}') == {"schema": "s", "status": "ok"}
    assert tick.parse_turbo("plain failure")["status"] == "failed"


def test_run_kills_process_on_timeout():
    with pytest.raises(TimeoutError):
        asyncio.run(proc.run(["sleep", "30"], timeout=0.3))


def test_run_returns_output():
    result = asyncio.run(proc.run(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10))
    assert (result.returncode, result.stdout, result.stderr) == (3, "out\n", "err\n")


# --- mcp_subscription reason codes ----------------------------------------------


def http_error(code=401):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"denied"))


@pytest.fixture
def login(tmp_path, monkeypatch):
    path = tmp_path / "login.json"
    monkeypatch.setattr(config, "LOGIN", path)
    return path


def entitlement(**over):
    ent = {"active": True, "status": "active", "source": "stripe", "tier": "pro", "plan": "p"}
    return {"active": True, "entitlement": {**ent, **over}}


def set_http(monkeypatch, handler):
    async def fake(method, url, payload=None, headers=None):
        return handler(method, url, payload, headers)

    monkeypatch.setattr(subscription, "http_json", fake)


def reason():
    return asyncio.run(subscription.mcp_subscription())


def test_subscription_login_missing(login):
    assert reason()["reason"] == "login_missing"


def test_subscription_login_without_tokens(login):
    write_json(login, {})
    assert reason()["reason"] == "login_missing"


def test_subscription_ok(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    seen = {}

    def handler(method, url, payload, headers):
        seen.update(method=method, url=url, auth=headers["Authorization"])
        return entitlement()

    set_http(monkeypatch, handler)
    result = reason()
    assert result["active"] is True and result["reason"] == "ok" and result["tier"] == "pro"
    assert seen == {"method": "GET", "url": config.VALIDATE_URL, "auth": "Bearer a"}


@pytest.mark.parametrize("over", [
    {"tier": "free"}, {"status": "canceled"}, {"source": "trial"}, {"active": False},
])
def test_subscription_required(login, monkeypatch, over):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})
    set_http(monkeypatch, lambda *a: entitlement(**over))
    assert reason()["reason"] == "subscription_required"


def test_paid_sources():
    assert config.PAID_SOURCES == {"subscription", "stripe", "admin"}


def test_login_path_follows_env_then_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "svc"))
    monkeypatch.delenv("SIMPLICIO_247_LOGIN", raising=False)
    assert config.default_login() == tmp_path / "svc" / ".simplicio" / "login.json"
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(tmp_path / "custom.json"))
    assert config.default_login() == tmp_path / "custom.json"
    assert "/root" not in str(config.default_login())


def test_subscription_entitlement_required_on_http_error(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})

    def handler(*a):
        raise http_error()

    set_http(monkeypatch, handler)
    result = reason()
    assert result["reason"] == "entitlement_required" and result["detail"] == "denied"


def test_subscription_validate_unreachable(login, monkeypatch):
    write_json(login, {"access_token": "a", "access_expires_at": 4102444800})

    def handler(*a):
        raise OSError("down")

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "validate_unreachable"


def test_subscription_refresh_failed(login, monkeypatch):
    write_json(login, {"access_token": "old", "refresh_token": "r", "access_expires_at": 0})

    def handler(*a):
        raise http_error(400)

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "refresh_failed"


def test_subscription_refresh_stores_tokens_then_validates(login, monkeypatch):
    write_json(login, {"access_token": "old", "refresh_token": "r", "access_expires_at": 0})

    def handler(method, url, payload, headers):
        if method == "POST":
            assert payload["grant_type"] == "refresh_token" and payload["refresh_token"] == "r"
            return {"access_token": "new", "refresh_token": "r2", "expires_in": 3600}
        assert headers["Authorization"] == "Bearer new"
        return entitlement()

    set_http(monkeypatch, handler)
    assert reason()["reason"] == "ok"
    stored = read_json(login)
    assert stored["access_token"] == "new" and stored["refresh_token"] == "r2"
    assert oct(login.stat().st_mode & 0o777) == "0o600"


PYTEST_CMD = "python3 -m pytest -q"
PYPROJECT = {"pyproject.toml": "[project]\nname = 'a'\n"}


def test_turbo_gets_verify_when_test_command_detected(env):
    fake = env(FakeRun({"simplicio-a": [issue(8)]}, files=PYPROJECT, verify={"passed": True, "output_tail": "3 passed"}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert argv[argv.index("--verify") + 1] == PYTEST_CMD
    body = fake.ran("gh", "pr", "create")[0]
    body = body[body.index("--body") + 1]
    assert "MEASURED|verify_passed" in body and "UNVERIFIED" not in body
    assert read_json(config.CLAIMS)["simplicio-a#8"]["status"] == "done"


def test_verify_failure_opens_no_pr_and_schedules_retry_with_excerpt(env):
    fake = env(FakeRun({"simplicio-a": [issue(9)]}, files=PYPROJECT,
                       verify={"passed": False, "output_tail": "FAILED tests/test_x.py::test_y - AssertionError"}))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("git", "push") == []
    claim = read_json(config.CLAIMS)["simplicio-a#9"]
    assert claim["status"] == "retry" and claim["attempts"] == 1
    assert "FAILED tests/test_x.py::test_y" in claim["error"]
    assert claim["next_try_at"] == state.iso(FIXED + timedelta(hours=6))
    assert any("FAILED tests/test_x.py::test_y" in body for _, number, body in fake.comments if number == 9)


def test_verify_not_reported_fails_closed(env):
    fake = env(FakeRun({"simplicio-a": [issue(12)]}, files=PYPROJECT, verify=None))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == []
    assert read_json(config.CLAIMS)["simplicio-a#12"]["status"] == "retry"


def test_no_test_command_opens_pr_labelled_unverified(env):
    fake = env(FakeRun({"simplicio-a": [issue(10)]}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert "--verify" not in argv
    body = fake.ran("gh", "pr", "create")[0]
    body = body[body.index("--body") + 1]
    assert "UNVERIFIED|no_test_command" in body and "MEASURED" not in body
    assert any("UNVERIFIED|no_test_command" in text for _, number, text in fake.comments if number == 10)
    assert read_json(config.CLAIMS)["simplicio-a#10"]["status"] == "done"
