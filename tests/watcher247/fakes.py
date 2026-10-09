"""Fakes for the watcher's only subprocess boundary, proc.run.

FakeRun answers gh JSON (repo/issue/pr lists), gh api (contents, lifecycle comments,
review comments), git and simplicio-loop turbo by argv. Nothing else is faked, so the real
github_lifecycle, pr_patrol and intake_gate code runs on top of it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from simplicio_loop.github_lifecycle import LIFECYCLE_COMMENT_MARKER
from simplicio_loop.watcher247 import config, proc, tick

PR_URL = "https://github.com/simpletibr/simplicio-a/pull/9"
LOOP_TOML = base64.b64encode(b"enabled = true\n").decode()
CONCRETE_BODY = "Ajustar `app.py` para o fluxo do watcher seguir o contrato descrito abaixo."
MARKER = LIFECYCLE_COMMENT_MARKER


def issue(number, title="Fix thing", labels=("loop:auto",), body=CONCRETE_BODY, author="owner",
          association="OWNER"):
    """An issue row shaped like `gh issue list --json number,title,body,createdAt,labels,author,authorAssociation`."""
    return {
        "number": number, "title": title, "body": body, "createdAt": "2026-10-01T00:00:00Z",
        "labels": [{"name": name} for name in labels],
        "author": {"login": author}, "authorAssociation": association,
    }


def pr_row(number, head, review="", checks=()):
    return {
        "number": number, "url": f"https://github.com/simpletibr/simplicio-a/pull/{number}",
        "headRefName": head, "baseRefName": "main", "isDraft": False, "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED", "reviewDecision": review, "statusCheckRollup": list(checks),
    }


class FakeRun:
    """Answers every proc.run call by argv and records what ran."""

    def __init__(self, issues, *, turbo_ok=True, diff=True, delay=0.0, opted_in=None,
                 broken_gate=(), prs=(), pr_views=None, claimed_by=None, verify_pass=False, distinct_prs=False,
                 train_ok=True):
        self.issues = issues  # repo name -> list of issue rows
        self.turbo_ok = turbo_ok
        self.diff = diff
        self.delay = delay
        self.opted_in = set(issues) if opted_in is None else set(opted_in)
        self.broken_gate = set(broken_gate)
        self.prs = list(prs)
        self.pr_views = pr_views or {}
        self.claimed_by = claimed_by  # owner already named on the canonical comment
        self.verify_pass = verify_pass  # turbo reports a passed verify (the squad review needs MEASURED tests)
        self.distinct_prs = distinct_prs  # `gh pr create` answers pull/<100+issue> instead of one fixed url
        self.train_ok = train_ok  # the merge train's cumulative test run
        self.merges = []  # PR numbers of every `gh pr merge`
        self.tests_run = 0
        self.calls = []
        self.comments = {}  # issue number -> [{"id", "body"}]
        self.api_writes = []  # (method, route) of every non-GET gh api call
        self.next_id = 5000
        self.turbo_argv = []
        self.turbo_timeouts = []
        self.turbo_active = 0
        self.max_turbo = 0
        self.repo_active = {}
        self.max_repo_active = 0

    def ran(self, *prefix):
        return [a for a in self.calls if a[: len(prefix)] == list(prefix)]

    def marker_comments(self, number):
        return [c for c in self.comments.get(int(number), []) if MARKER in c["body"]]

    def canonical_state(self, number):
        body = self.marker_comments(number)[-1]["body"]
        return re.search(r"^\| Estado \| (\S+) \|$", body, re.MULTILINE).group(1)

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
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
        if head == ["gh", "repo", "clone"]:
            (Path(argv[4]) / ".git").mkdir(parents=True)
            return proc.Result(0)
        if head == ["gh", "pr", "create"]:
            if self.distinct_prs:
                number = 100 + int(argv[argv.index("--head") + 1].rpartition("-")[2])
                return proc.Result(0, f"https://github.com/simpletibr/simplicio-a/pull/{number}\n")
            return proc.Result(0, PR_URL + "\n")
        if head == ["gh", "pr", "merge"]:
            self.merges.append(int(argv[3]))
            return proc.Result(0)
        if head == ["gh", "pr", "list"]:
            return proc.Result(0, json.dumps(self.prs))
        if argv[:2] == ["gh", "pr"] and argv[2] == "view":
            return proc.Result(0, json.dumps(self.pr_views[int(argv[3])]))
        if argv[:2] == ["gh", "api"]:
            return self._api(argv, stdin)
        if argv[0] == "simplicio-loop" and argv[1] == "turbo":
            self.turbo_argv.append(argv)
            self.turbo_timeouts.append(timeout)
            self.turbo_active += 1
            self.max_turbo = max(self.max_turbo, self.turbo_active)
            await asyncio.sleep(self.delay)
            self.turbo_active -= 1
            if self.turbo_ok:
                document = {"schema": "simplicio.turbo/v1", "status": "ok"}
                if self.verify_pass:
                    document["verify"] = {"passed": True}
                return proc.Result(0, json.dumps(document))
            return proc.Result(1, json.dumps({"status": "failed", "detail": "boom"}))
        if argv[0] == "git":
            return self._git(argv, repo)
        if argv[:3] == ["python3", "-m", "pytest"]:  # the merge train's cumulative test
            self.tests_run += 1
            return proc.Result(0 if self.train_ok else 1)
        raise AssertionError(f"unexpected argv {argv}")

    def _api(self, argv, stdin):
        args = argv[2:]
        route = next(a for a in args if a.startswith("repos/")).partition("?")[0]
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        contents = re.fullmatch(r"repos/[^/]+/([^/]+)/contents/\.simplicio/loop\.toml", route)
        if contents:
            name = contents.group(1)
            if name in self.broken_gate:
                return proc.Result(1, "", "gh: HTTP 500 (server error)")
            if name not in self.opted_in:
                return proc.Result(1, "", "gh: Not Found (HTTP 404)")
            return proc.Result(0, LOOP_TOML + "\n")
        if method != "GET":
            self.api_writes.append((method, route))
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)/comments", route)
        if found:
            number = int(found.group(1))
            comments = self.comments.setdefault(number, [])
            if method == "POST":
                comment = {"id": self.next_id, "body": json.loads(stdin)["body"]}
                self.next_id += 1
                comments.append(comment)
                return proc.Result(0, json.dumps(comment))
            return proc.Result(0, json.dumps(comments))
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/comments/(\d+)", route)
        if found:
            wanted = int(found.group(1))
            comment = next(c for cs in self.comments.values() for c in cs if c["id"] == wanted)
            if method == "PATCH":
                comment["body"] = json.loads(stdin)["body"]
            return proc.Result(0, json.dumps(comment))
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)", route)
        if found:
            number = int(found.group(1))
            return proc.Result(0, json.dumps({
                "number": number, "title": "an issue", "body": CONCRETE_BODY, "state": "open",
                "html_url": f"https://github.com/simpletibr/simplicio-a/issues/{number}",
                "labels": [], "assignees": [], "user": {"login": "owner"},
                "author_association": "OWNER",
                "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z",
            }))
        if re.fullmatch(r"repos/[^/]+/[^/]+/pulls/\d+/comments", route):
            return proc.Result(0, "[]")
        raise AssertionError(f"unexpected gh api call {argv}")

    def _git(self, argv, repo):
        sub = argv[1]
        if sub == "config" and argv[2:] == ["user.email"]:
            return proc.Result(1)
        if sub == "checkout":
            self.repo_active[repo] = self.repo_active.get(repo, 0) + 1  # tree in use until the diff check
            self.max_repo_active = max(self.max_repo_active, self.repo_active[repo])
            return proc.Result(0)
        if sub == "status":
            if not self.diff:
                self.repo_active[repo] -= 1
            return proc.Result(0, " M app.py\n?? .simplicio/x\n" if self.diff else "")
        if sub == "diff":
            return proc.Result(0, "app.py\n")
        return proc.Result(0)  # config, fetch, add, reset, commit, push


__all__ = ["FakeRun", "issue", "pr_row", "PR_URL", "CONCRETE_BODY", "MARKER"]


FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run_tick(**kwargs):
    asyncio.run(tick.tick(**kwargs))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def read_json(path):
    return json.loads(path.read_text())


def baseline(*idents):
    write_json(config.BASELINE, {"created_at": "x", "issues": list(idents)})


def tasks(fake):
    """The --task text of every turbo run, in order."""
    return [argv[argv.index("--task") + 1] for argv in fake.turbo_argv]
