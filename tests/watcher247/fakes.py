"""Fakes for the watcher's only subprocess boundary, proc.run.

FakeRun answers gh JSON (repo/issue/pr lists), gh api (contents, lifecycle comments,
review comments), git and simplicio-loop turbo by argv. Nothing else is faked, so the real
github_lifecycle, pr_patrol and intake_gate code runs on top of it.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from simplicio_loop.github_lifecycle import LIFECYCLE_COMMENT_MARKER
from simplicio_loop.watcher247 import config, proc, tick

PR_URL = "https://github.com/simpletibr/simplicio-a/pull/9"
LOOP_TOML = 'enabled = true\nverify = "python3 -m pytest -q"\n'  # the opt-in and the one verify command (the merge train argv)
CONCRETE_BODY = "Ajustar `app.py` para o fluxo do watcher seguir o contrato descrito abaixo."
MARKER = LIFECYCLE_COMMENT_MARKER


def issue(number, title="Fix thing", labels=("loop:auto",), body=CONCRETE_BODY, author="owner",
          association="OWNER"):
    """An issue row shaped like `gh api repos/<org>/<repo>/issues` (REST)."""
    return {
        "number": number, "title": title, "body": body, "created_at": "2026-10-01T00:00:00Z",
        "labels": [{"name": name} for name in labels],
        "user": {"login": author}, "author_association": association,
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
                 broken_gate=(), prs=(), pr_views=None, claimed_by=None, distinct_prs=False,
                 train_ok=True, login="squad-bot", loop_toml=None, meet=0):
        self.issues = issues  # repo name -> list of issue rows
        self.turbo_ok = turbo_ok
        self.diff = diff
        self.delay = delay
        self.meet = meet  # a turbo waits until `meet` turbos run together: overlap is proven by a rendezvous, not by a short sleep
        self._met = asyncio.Event()
        self.opted_in = set(issues) if opted_in is None else set(opted_in)
        self.loop_toml = loop_toml or {}  # repo name -> the .simplicio-loop/loop.toml text of its default branch (default LOOP_TOML)
        self.broken_gate = set(broken_gate)
        self.prs = list(prs)
        self.pr_views = pr_views or {}
        self.claimed_by = claimed_by  # owner already named on the canonical comment
        self.distinct_prs = distinct_prs  # `gh pr create` answers pull/<100+issue> instead of one fixed url
        self.train_ok = train_ok  # the merge train's cumulative test run
        self.login = login  # `gh api user`: the account the watcher posts and merges as (None = the lookup fails)
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
        self.worktrees = {}  # path of every live `git worktree add` -> its branch
        self.max_worktrees = 0
        self.worktree_log = []  # ("add" | "remove", path) in order
        self.turbo_cwds = []  # where each turbo ran: it must be the item's own worktree
        self.turbo_spans = []  # (start, end) of every turbo run, time.monotonic()
        self.on_turbo = None  # async hook(cwd) awaited inside a turbo run, before its delay
        self.push_cwds = []
        self.moved_head = None  # when set, `git symbolic-ref HEAD` answers this ref (the author rewrote the HEAD of the admin dir)
        self.fetched_refs = {}  # hermetic: map of ref name -> sha, populated by `git fetch` calls

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
            # Hermetic: merge posted comments with pr_views so squad_gate sees them
            pr_num = int(argv[3])
            view = dict(self.pr_views.get(pr_num, {}))
            # Extract issue number from pr_num (assuming distinct_prs: pr = 100 + issue)
            if self.distinct_prs and pr_num >= 100:
                issue_num = pr_num - 100
                # Add posted comments to the view
                if issue_num in self.comments:
                    existing_comments = view.get("comments", [])
                    # Merge comments: keep existing ones and add posted ones
                    posted = self.comments[issue_num]
                    # Include both existing and newly posted comments
                    view["comments"] = existing_comments + [c for c in posted if c["id"] >= 5000]
            return proc.Result(0, json.dumps(view))
        if argv[:3] == ["gh", "api", "user"]:
            return proc.Result(0, self.login + "\n") if self.login else proc.Result(1, "", "gh: HTTP 401")
        if argv[:2] == ["gh", "api"]:
            return self._api(argv, stdin)
        if argv[0] == "simplicio-loop" and argv[1] == "turbo":
            self.turbo_argv.append(argv)
            self.turbo_cwds.append(Path(cwd) if cwd else None)
            self.turbo_timeouts.append(timeout)
            self.turbo_active += 1
            self.max_turbo = max(self.max_turbo, self.turbo_active)
            if self.meet:
                if self.turbo_active >= self.meet:
                    self._met.set()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._met.wait(), 10)  # only a run that never overlaps waits this long, and its test fails
            began = time.monotonic()
            if self.on_turbo is not None:
                await self.on_turbo(Path(cwd))
            await asyncio.sleep(self.delay)
            self.turbo_spans.append((began, time.monotonic()))
            self.turbo_active -= 1
            if self.turbo_ok:
                document = {"schema": "simplicio.turbo/v1", "status": "ok"}
                if "--verify" in argv:  # turbo reports the verify it was asked for (the squad review needs MEASURED tests)
                    document["verify"] = {"passed": True}
                return proc.Result(0, json.dumps(document))
            return proc.Result(1, json.dumps({"status": "failed", "detail": "boom"}))
        if argv[0] == "git":
            return self._git(argv, cwd)
        if argv[:3] == ["python3", "-m", "pytest"]:  # the merge train's cumulative test
            self.tests_run += 1
            return proc.Result(0 if self.train_ok else 1)
        raise AssertionError(f"unexpected argv {argv}")

    def _api(self, argv, stdin):
        args = argv[2:]
        route = next(a for a in args if a.startswith("repos/")).partition("?")[0]
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        contents = re.fullmatch(r"repos/[^/]+/([^/]+)/contents/\.simplicio-loop/loop\.toml", route)
        if contents:
            name = contents.group(1)
            if name in self.broken_gate:
                return proc.Result(1, "", "gh: HTTP 500 (server error)")
            if name not in self.opted_in:
                return proc.Result(1, "", "gh: Not Found (HTTP 404)")
            text = self.loop_toml.get(name, LOOP_TOML)
            return proc.Result(0, base64.b64encode(text.encode()).decode() + "\n")
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
        # GET /repos/{org}/{repo}/issues (open_issues)
        found = re.fullmatch(r"repos/([^/]+)/([^/]+)/issues(?:\?.*)?$", route)
        if found and method == "GET":
            org, name = found.groups()
            if name in self.issues:
                return proc.Result(0, json.dumps(self.issues[name]))
            return proc.Result(0, json.dumps([]))
        raise AssertionError(f"unexpected gh api call {argv}")

    def _git(self, argv, cwd):
        sub = argv[1]
        if sub == "config" and argv[2:] == ["user.email"]:
            return proc.Result(1)
        if sub == "symbolic-ref":
            branch = self.worktrees.get(Path(cwd))
            if branch is None:
                return proc.Result(128, "", "fatal: not a worktree")
            return proc.Result(0, (self.moved_head or f"refs/heads/{branch}") + "\n")
        if sub == "fetch":
            # Hermetic: track which refs are fetched so rev-parse can return them
            # Parse refs from args like: fetch --depth 200 origin +refs/heads/main:refs/remotes/origin/main
            for i, arg in enumerate(argv):
                if arg.startswith("+") or (i > 0 and argv[i-1] not in ["-", "--"] and ":" in arg):
                    parts = arg.lstrip("+").split(":")
                    if len(parts) == 2:
                        local_ref = parts[1]
                        # Extract the number from refs like "refs/remotes/origin/loop/issue-1"
                        match = re.search(r"issue-(\d+)", local_ref)
                        if match:
                            issue_num = int(match.group(1))
                            # Map issue number to PR: if distinct_prs, PR = 100 + issue; else PR = some fixed value
                            pr_num = 100 + issue_num if self.distinct_prs else None
                            view = self.pr_views.get(pr_num) if pr_num else None
                            if view:
                                sha = view.get("headRefOid")
                                if sha:
                                    self.fetched_refs[local_ref] = sha
                        elif "main" in local_ref:
                            self.fetched_refs[local_ref] = "0" * 40  # full SHA for main
            return proc.Result(0)
        if sub == "rev-parse":
            # Hermetic: return the SHA of a fetched ref, or from pr_views
            # argv is like: ["git", "rev-parse", "--verify", "refs/remotes/origin/loop/issue-1^{commit}"]
            ref_query = argv[-1] if len(argv) > 2 else ""
            if not ref_query.startswith("refs/remotes/"):
                return proc.Result(1)  # the item's local branch (refs/heads/...) does not exist yet
            # Strip ^{commit} suffix for lookup
            ref_name = ref_query.rstrip("}").rpartition("^{")[0] if "^{" in ref_query else ref_query
            if ref_name in self.fetched_refs:
                return proc.Result(0, self.fetched_refs[ref_name] + "\n")
            # If ref not found but we know about it from pr_views, return it
            match = re.search(r"issue-(\d+)", ref_name)
            if match:
                issue_num = int(match.group(1))
                # Map issue number to PR
                pr_num = 100 + issue_num if self.distinct_prs else None
                view = self.pr_views.get(pr_num) if pr_num else None
                if view:
                    sha = view.get("headRefOid")
                    if sha:
                        return proc.Result(0, sha + "\n")
            # Fallback: return a synthetic full SHA
            return proc.Result(0, "0" * 40 + "\n")
        if sub == "worktree" and argv[2] == "add":
            path = Path(argv[argv.index("-B") + 2])
            path.mkdir(parents=True)
            (path / ".git").write_text("gitdir: fake\n")
            self.worktrees[path] = argv[argv.index("-B") + 1]
            self.max_worktrees = max(self.max_worktrees, len(self.worktrees))
            self.worktree_log.append(("add", path))
            return proc.Result(0)
        if sub == "worktree" and argv[2] == "remove":
            path = Path(argv[-1])
            self.worktrees.pop(path)
            self.worktree_log.append(("remove", path))
            shutil.rmtree(path)  # what git does for the worktree it removes
            return proc.Result(0)
        if sub == "push":
            self.push_cwds.append(Path(cwd))
            return proc.Result(0)
        if sub == "status":
            return proc.Result(0, " M app.py\n?? .simplicio-loop/x\n" if self.diff else "")
        if sub == "diff":
            # Hermetic: return files that match pr_views (all issues and PRs)
            files = set()
            for pr_num, view in self.pr_views.items():
                for f in view.get("files", []):
                    files.add(f["path"])
            if files:
                return proc.Result(0, "".join(p + "\n" for p in sorted(files)))
            # Fallback: return app.py for compatibility
            return proc.Result(0, "app.py\n")
        return proc.Result(0)  # config, fetch, add, reset, commit, push


__all__ = ["FakeRun", "issue", "pr_row", "PR_URL", "CONCRETE_BODY", "MARKER"]


FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run_tick(**kwargs):
    asyncio.run(tick.tick(**kwargs))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    path.chmod(0o600)  # the login store refuses a file that group or others can read
    path.parent.chmod(0o700)  # ... and a folder that group or others can write


def read_json(path):
    return json.loads(path.read_text())


def baseline(*idents):
    write_json(config.BASELINE, {"created_at": "x", "issues": list(idents)})


def tasks(fake):
    """The --task text of every turbo run, in order."""
    return [argv[argv.index("--task") + 1] for argv in fake.turbo_argv]
