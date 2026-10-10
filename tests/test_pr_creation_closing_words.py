"""Every `gh pr create` / `gh pr edit` built in `simplicio_loop/` goes through `closing_words.sanitize` (#1644).

Places that build a PR title or body, and who covers them:
  * `watcher247/tick.py` (`pr_title` + `sanitize` on the body)      -> tests/watcher247/test_pr_text_guard.py
  * `merge_executor.MergeExecutor.ensure_pr` (--title/--body)        -> the `merge_executor` tests below
  * `delivery_agent.GitHubDeliveryAdapter.create_or_update_pr`
    (--title, --body-file; both `pr create` and `pr edit`)           -> the `delivery_agent` tests below
  * `runner_core` delivery step                                      -> reaches `ensure_pr`, same door
The other `gh` calls with --body (`issue create`, `issue comment`, `pr comment`) are not a PR title or body.
"""
import json
import os
import subprocess
import sys

from simplicio_loop.delivery_agent import GitHubDeliveryAdapter
from simplicio_loop.merge_executor import MergeExecutor
from simplicio_loop.watcher247.closing_words import has_closing

HOSTILE_TITLE = "Fixes #99 and closes o/r#98"
HOSTILE_BODY = "Resolved #97\n\nthen Fixes #99, closes o/r#98.\n"


class _Runner:
    def __init__(self, existing=False):
        self.calls = []
        self.existing = existing
        self.body = ""

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[1:3] == ["pr", "list"]:
            rows = [{"number": 77, "url": "https://example.test/pull/77", "state": "OPEN"}] if self.existing else []
            return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")
        if argv[1:3] in (["pr", "create"], ["pr", "edit"]) and "--body-file" in argv:
            with open(argv[argv.index("--body-file") + 1], encoding="utf-8", newline="") as handle:
                self.body = handle.read()
            self.calls[-1] = argv + ["<body-file:%s>" % self.body]
        if argv[1:3] == ["pr", "create"]:
            return subprocess.CompletedProcess(argv, 0, "https://example.test/pull/77\n", "")
        if argv[1:3] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                "number": 77, "url": "https://example.test/pull/77", "state": "OPEN",
                "body": self.body, "bodyHTML": "<p>rendered</p>",
            }), "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _call(runner, verb):
    return next(c for c in runner.calls if c[1:3] == ["pr", verb])


def test_merge_executor_ensure_pr_title_and_body_have_no_closing_word():
    runner = _Runner()
    MergeExecutor(repo="o/r", runner=runner).ensure_pr(
        branch="b", base="main", title=HOSTILE_TITLE, body=HOSTILE_BODY)
    argv = _call(runner, "create")
    title, body = argv[argv.index("--title") + 1], argv[argv.index("--body") + 1]
    assert not has_closing(title) and not has_closing(body)
    assert "Parte de #99" in title and "Parte de o/r#98" in title
    assert "Parte de #97" in body


def test_delivery_agent_create_has_no_closing_word_in_title_or_body_file():
    runner = _Runner()
    GitHubDeliveryAdapter(repo="o/r", runner=runner).create_or_update_pr(
        branch="b", base="main", title=HOSTILE_TITLE, body=HOSTILE_BODY)
    argv = _call(runner, "create")
    assert not has_closing(argv[argv.index("--title") + 1])
    assert "Parte de #99" in argv[argv.index("--title") + 1]
    assert not has_closing(runner.body) and "Parte de #97" in runner.body


def test_delivery_agent_edit_has_no_closing_word_in_body_file():
    runner = _Runner(existing=True)
    GitHubDeliveryAdapter(repo="o/r", runner=runner).create_or_update_pr(
        branch="b", base="main", title=HOSTILE_TITLE, body=HOSTILE_BODY)
    _call(runner, "edit")
    assert not has_closing(runner.body) and "Parte de #97" in runner.body


def test_pr_evidence_build_writes_a_body_and_title_without_closing_words(tmp_path):
    """`scripts/pr_evidence.py build` is the body the loop skill tells a model to publish: goal, summary and ACs are hostile here."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({
        "item": "7", "goal": "Fixes #7 do thing",
        "criteria": [{"id": "AC1", "text": "Closes #5 after merge", "status": "open"}],
    }), encoding="utf-8")
    out = tmp_path / "body.md"
    result = subprocess.run(
        [sys.executable, os.path.join(repo, "scripts", "pr_evidence.py"), "build", "--anchor", str(anchor),
         "--summary", "resolves #9", "--out", str(out), "--shots-dir", str(tmp_path / "none"),
         "--video-dir", str(tmp_path / "none")],
        capture_output=True, text=True, cwd=repo, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stdout + result.stderr
    body = out.read_text(encoding="utf-8")
    assert not has_closing(body), body
    assert not has_closing(body.splitlines()[0])
    for number in ("#7", "#5", "#9"):
        assert "Parte de " + number in body, body
