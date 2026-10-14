"""The watcher runs turbo with --verify and opens a PR only when verify passes (#1463)."""
import json

from simplicio_loop.watcher247 import config, proc

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = "simplicio-a"


class VerifyingRun(FakeRun):
    """FakeRun whose turbo answers with the given JSON document."""

    def __init__(self, issues, document, **kwargs):
        super().__init__(issues, **kwargs)
        self.document = document

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        if list(argv[:2]) == ["simplicio-loop", "turbo"]:
            await super().__call__(argv, timeout, cwd, stdin, env)
            return proc.Result(0, json.dumps(self.document))
        return await super().__call__(argv, timeout, cwd, stdin, env)


def report(passed, tail=""):
    return {"schema": "simplicio.turbo/v1", "status": "ok", "verify": {"passed": passed, "output_tail": tail}}


def pr_body(fake):
    created = fake.ran("gh", "pr", "create")[0]
    return created[created.index("--body") + 1]


def canonical_body(fake, number):
    return fake.marker_comments(number)[-1]["body"]


def test_verify_pass_opens_the_pr_with_the_measured_line(env):
    fake = env(VerifyingRun({REPO: [issue(1)]}, report(True)))
    baseline()
    run_tick()
    assert "MEASURED|verify_passed: `python3 -m pytest -q`" in pr_body(fake)
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "done"


def test_verify_failure_opens_no_pr_and_retries(env):
    fake = env(VerifyingRun({REPO: [issue(1)]}, report(False, "FAILED test_x - assert 0")))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == []
    assert fake.ran("git", "push") == []
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "retry"
    assert "FAILED test_x" in canonical_body(fake, 1)


def test_missing_verify_report_opens_no_pr(env):
    fake = env(VerifyingRun({REPO: [issue(1)]}, {"schema": "simplicio.turbo/v1", "status": "ok"}))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create") == []
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "retry"
