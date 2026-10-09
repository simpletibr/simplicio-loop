"""The 24/7 watcher in squads (#1505): the same pattern as the /simplicio-loop skill.

* general coordinator (planning): `squads.plan_squads` over the tick's admitted issues of a repo, up to 4 workers per squad;
* workers: `process()` per issue, started at the role `squad_routing.route` picks (the escalation ladder is unchanged);
* squad coordinator (coordination): reviews the squad's PRs (measured tests, file ownership) and posts APROVADO PELO SQUAD
  with `pr_evidence.publish_comment`;
* merge: only with SIMPLICIO_247_AUTO_MERGE=1 (#1434): `squads.squad_gate`, then `merge_train` (cumulative test, bisect).

Concurrency is the tick's (daily budget, SIMPLICIO_247_CONCURRENCY) and the repo lock; the merge train holds that lock.
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import execution_report, merge_train, model_roles, pr_evidence, squad_routing, squads
from . import config, proc, sandbox, state, verify

AUTO_MERGE_ENV = "SIMPLICIO_247_AUTO_MERGE"
APPROVAL_MARKER = "<!-- simplicio-loop:squad-approval:{oid} -->"  # one comment per head commit, so createdAt stays fresh
_PATH = re.compile(r"`([\w./-]+\.\w{1,6})`")
_PR_NUMBER = re.compile(r"/pull/(\d+)")
TRAIN_FETCH_DEPTH = "100"  # the clone is shallow: enough history for the train's merges


def auto_merge_enabled(environ: dict[str, str] | None = None) -> bool:
    """Off unless the operator sets SIMPLICIO_247_AUTO_MERGE=1 (#1434): the watcher never merges on its own."""
    return (os.environ if environ is None else environ).get(AUTO_MERGE_ENV) == "1"


@dataclass
class Outcome:
    """What process() hands back for a finished worker."""
    pr: str
    verify: str
    steps: list[dict[str, str]] = field(default_factory=list)


@dataclass
class RepoPlan:
    repo: str
    plan: squads.SquadPlan
    routed: dict[int, str]  # issue number -> the role the worker starts at


def _safe_path(path: str) -> bool:
    """A path named in an issue body is only an ownership pattern, but it must still be repo-relative and stay inside the clone."""
    return not path.startswith(("/", "~")) and ".." not in path.split("/")


def _issue_row(issue: dict) -> dict[str, Any]:
    body = issue.get("body") or ""
    return {"number": issue["number"], "title": issue.get("title") or "", "body": body, "labels": issue.get("labels") or [],
            "paths": sorted({p for p in _PATH.findall(body) if _safe_path(p)})}


def plan_repo(repo: str, issues: list[dict], family: str) -> RepoPlan:
    """The general coordinator: squads for the issues, and the starting role of each worker (squad_routing.route)."""
    rows = [_issue_row(i) for i in issues]
    try:
        plan = squads.plan_squads(rows, family=family)
    except squads.SquadCycleError as exc:  # a declared "depende de" cycle must not wedge the tick: plan without the declared order
        state.log(f"squad plan {repo}: {exc}; planning without declared dependencies")
        plan = squads.plan_squads([{**row, "body": ""} for row in rows], family=family)
    workers = {w.issues[0]: w for s in plan.squads for w in s.workers}
    routed = {}
    for row in rows:
        worker = workers[row["number"]]
        shared = bool(set(row["paths"]) - set(worker.owned_paths))
        routed[row["number"]] = squad_routing.route(
            {"files": row["paths"], "touches_shared": shared, "labels": [l.get("name") if isinstance(l, dict) else l
                                                                         for l in row["labels"]]}).role
    return RepoPlan(repo, plan, routed)


def form(batch: list, family: str) -> list[RepoPlan]:
    """Plan the squads of the new issues in `batch` (review fixes stay outside) and set each Work's starting role."""
    by_repo: dict[str, list] = {}
    for work in batch:
        if not work.fix:
            by_repo.setdefault(work.repo, []).append(work)
    out = []
    for repo, works in by_repo.items():
        repo_plan = plan_repo(repo, [w.issue for w in works], family)
        for work in works:
            work.role = repo_plan.routed[int(work.issue["number"])]
        out.append(repo_plan)
    return out


def _pr_number(url: str | None) -> int | None:
    found = _PR_NUMBER.search(url or "")
    return int(found.group(1)) if found else None


async def _review(repo: str, repo_plan: RepoPlan, squad: squads.Squad, issue: int, outcome: Outcome, runner) -> dict:
    """The squad coordinator's review of one PR: tests measured by the worker's verify, and file ownership."""
    number = _pr_number(outcome.pr)
    if not outcome.verify.startswith("MEASURED|verify_passed"):
        return {"pr": number, "issue": issue, "approved": False, "reasons": ["tests not measured green"]}
    reasons: list[str] = []
    full = f"{config.ORG}/{repo}"
    view = await proc.run(["gh", "pr", "view", str(number), "--repo", full, "--json", "files,headRefOid,commits,comments"])
    if view.returncode != 0:
        return {"pr": number, "issue": issue, "approved": False, "reasons": ["pr view failed"]}
    try:
        data = json.loads(view.stdout)
    except ValueError:
        return {"pr": number, "issue": issue, "approved": False, "reasons": ["pr view returned invalid json"]}
    head = data.get("headRefOid")
    if not head:
        return {"pr": number, "issue": issue, "approved": False, "reasons": ["pr head unknown"]}
    foreign = [p for p in (f["path"] for f in data.get("files") or [])
               if any(fnmatch.fnmatchcase(p, g) for g in repo_plan.plan.shared_files)
               or any(fnmatch.fnmatchcase(p, g) for other in repo_plan.plan.squads if other.id != squad.id
                      for g in other.owned_paths)]
    if foreign:
        reasons.append("files owned elsewhere: " + ", ".join(sorted(foreign)[:5]))
    if reasons:
        return {"pr": number, "issue": issue, "approved": False, "reasons": reasons}
    body = (f"{squads.APPROVAL_PHRASE}\n\nSquad {squad.id} ({squad.coordinator.role}, {squad.coordinator.model}, "
            f"{squad.coordinator.effort}) revisou o PR da issue #{issue}.\n- testes: {outcome.verify}\n- posse de arquivos: ok")
    try:
        await asyncio.to_thread(pr_evidence.publish_comment, config.ORG, repo, number, body,
                                marker=APPROVAL_MARKER.format(oid=head), runner=runner)
    except pr_evidence.PublishError:  # an approval that was not posted is not an approval
        return {"pr": number, "issue": issue, "approved": False, "reasons": ["approval comment not posted"]}
    return {"pr": number, "issue": issue, "approved": True, "reasons": [], "head": head}


async def _train_test(dest: Path, test_cmd: str | None, issues: list[int]) -> bool:
    """Integrate the PR branches on a temporary branch off main and run the repo's tests once."""
    if test_cmd is None:
        return False
    env = sandbox.scrubbed_env(os.environ, home=Path.home())
    git = lambda *args: proc.run(["git", *args], cwd=dest, timeout=180)  # noqa: E731
    if (await git("fetch", "--depth", TRAIN_FETCH_DEPTH, "origin", "main")).returncode != 0:
        return False
    if (await git("checkout", "-q", "-B", "loop/merge-train", "origin/main")).returncode != 0:
        return False
    for issue in issues:
        fetched = await git("fetch", "--depth", TRAIN_FETCH_DEPTH, "origin", f"loop/issue-{issue}")
        if fetched.returncode != 0 or (await git("merge", "--no-edit", "FETCH_HEAD")).returncode != 0:
            await git("merge", "--abort")
            return False
    argv = sandbox.wrap(shlex.split(test_cmd), clone=dest, state_dir=config.ROOT)
    return (await proc.run(argv, timeout=config.TURBO_TIMEOUT_S, cwd=dest, env=env)).returncode == 0


async def _merge(repo: str, repo_plan: RepoPlan, approved: dict[int, int], heads: dict[int, str], runner, gate) -> dict:
    """Gate each approved PR with squads.squad_gate, then merge the rest in squad order through merge_train."""
    full = f"{config.ORG}/{repo}"
    passed, blocked = [], []
    for issue, pr in approved.items():
        try:
            verdict = await squads.squad_gate_for_pr(full, pr, runner=runner)
        except squads.SquadGateError:  # fail closed: no gate verdict, no merge
            verdict = {"approved": False}
        (passed if verdict["approved"] else blocked).append(issue)
    result = {"merged": [], "failed": [], "gate_blocked": sorted(approved[i] for i in blocked)}
    merged_prs: list[int] = []

    async def merge_one(issue: int) -> None:
        done = await proc.run(["gh", "pr", "merge", str(approved[issue]), "--repo", full, "--squash",
                                "--match-head-commit", heads[approved[issue]]], timeout=120)  # only the head that was reviewed and tested
        if done.returncode == 0:
            merged_prs.append(approved[issue])
        else:
            result["failed"].append(approved[issue])

    order = [step.issue for step in repo_plan.plan.merge_order]
    async with gate.repo_lock(repo):  # writes are serialized: the train owns the working tree
        dest = config.WORK / repo
        test_cmd = await asyncio.to_thread(verify.detect_test_command, dest)
        for batch in merge_train.plan_train(passed, order):
            report = await merge_train.run_train(batch, lambda items: _train_test(dest, test_cmd, items), merge_one)
            result["failed"].extend(approved[i] for i in report.failed)
    result["merged"], result["failed"] = merged_prs, sorted(result["failed"])
    return result


async def finish(plans: list[RepoPlan], batch: list, outcomes: list, runner, gate) -> dict:
    """After the workers: squad review per PR, then the opt-in batch merge. Returns the status block per repo."""
    done = {(w.repo, int(w.issue["number"])): o for w, o in zip(batch, outcomes) if isinstance(o, Outcome)}
    summary: dict[str, Any] = {}
    reviews: dict[tuple[str, int], dict] = {}
    for repo_plan in plans:
        approved: dict[int, int] = {}
        heads: dict[int, str] = {}
        rejected: dict[str, list[str]] = {}
        for squad in repo_plan.plan.squads:
            for issue in squad.issues:
                outcome = done.get((repo_plan.repo, issue))
                if outcome is None or _pr_number(outcome.pr) is None:
                    continue
                review = await _review(repo_plan.repo, repo_plan, squad, issue, outcome, runner)
                reviews[(repo_plan.repo, issue)] = review
                if review["approved"]:
                    approved[issue] = review["pr"]
                    heads[review["pr"]] = review["head"]
                else:
                    rejected[str(review["pr"])] = review["reasons"]
        entry: dict[str, Any] = {
            "squads": [{"id": s.id, "coordinator": s.coordinator.id, "workers": [w.id for w in s.workers],
                        "issues": list(s.issues)} for s in repo_plan.plan.squads],
            "approved": sorted(approved.values()), "rejected": rejected, "merge": "disabled"}
        if approved and auto_merge_enabled():
            entry["merge"] = "enabled"
            entry.update(await _merge(repo_plan.repo, repo_plan, approved, heads, runner, gate))
        summary[repo_plan.repo] = entry
    await asyncio.to_thread(write_report, plans, done, reviews)
    return summary


def _agent(agent: squads.Agent, family: str, role: str | None = None) -> dict[str, str]:
    """{role, model, effort} of a planned agent, or of the role the router started it at."""
    if role is None or role == agent.role:
        return {"role": agent.role, "model": agent.model, "effort": agent.effort}
    return {"role": role, **model_roles.resolve(family, role)}


def write_report(plans: list[RepoPlan], done: dict, reviews: dict) -> Path:
    """One execution-report per tick: a task per agent with its role, model and effort (the worker's last step when it ran)."""
    started = time.monotonic()
    report = execution_report.new_report(config.ROOT)
    report["run_id"] = f"squads-{int(time.time())}-{report['run_id'].rsplit('-', 1)[1]}"
    for repo_plan in plans:
        family = repo_plan.plan.family
        general = repo_plan.plan.general_coordinator
        execution_report.record_task(
            report, task_id=f"{repo_plan.repo}/{general.id}", title=f"squad plan {repo_plan.repo}: {len(repo_plan.plan.squads)} squads",
            outcome="COMPLETE", operators=["squads"], agent=_agent(general, family))
        for squad in repo_plan.plan.squads:
            seen = [reviews[(repo_plan.repo, i)] for i in squad.issues if (repo_plan.repo, i) in reviews]
            outcome = "SKIP" if not seen else ("COMPLETE" if all(r["approved"] for r in seen) else "FAIL")
            execution_report.record_task(
                report, task_id=f"{repo_plan.repo}/{squad.coordinator.id}", title=f"squad review {squad.id}",
                outcome=outcome, operators=["squads"], agent=_agent(squad.coordinator, family))
            for worker in squad.workers:
                issue = worker.issues[0]
                result = done.get((repo_plan.repo, issue))
                last = (result.steps or [None])[-1] if result else None
                role = (last or {}).get("role") or repo_plan.routed[issue]
                agent = {k: last[k] for k in ("role", "model", "effort")} if last else _agent(worker, family, role)
                execution_report.record_task(
                    report, task_id=f"{repo_plan.repo}/{worker.id}", title=f"squad worker issue #{issue}",
                    issue=f"{repo_plan.repo}#{issue}", outcome="COMPLETE" if result else "FAIL",
                    operators=["dev-cli"], agent=agent)
    report["status"] = "COMPLETE"
    report["_started_monotonic"] = started
    return execution_report.write_report(config.ROOT / "squads", report)
