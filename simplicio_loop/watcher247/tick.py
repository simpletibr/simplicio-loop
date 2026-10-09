"""One watcher tick: gate repos and issues, patrol loop PRs, process the due work items."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from .. import escalation, intake_gate, watcher_github
from ..claim_lease import ClaimStore
from . import budget, config, github, host_mode, points, proc, prompt_guard, sandbox, secret_scan, squad_flow, state, subscription, verify

_STATE_DIRS = (".simplicio-loop/", ".simplicio/")


class Gate:
    """One lock per repo; the tick itself caps the batch at SIMPLICIO_247_CONCURRENCY issues."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def repo_lock(self, repo: str) -> asyncio.Lock:
        return self._locks.setdefault(repo, asyncio.Lock())


@dataclass
class Work:
    """One item for process(): a new issue, or a review fix for the issue's open loop PR."""
    repo: str
    branch: str
    issue: dict
    fix: str = ""
    pr: int = 0
    role: str = ""  # the role a squad worker starts at (squad_routing.route); "" keeps the host-mode default


async def _intake_run(*args: str) -> tuple[int, bytes, bytes]:
    """intake_gate's `gh` runner, routed through proc.run like every other gh call."""
    result = await proc.run(["gh", *args])
    return result.returncode, result.stdout.encode(), result.stderr.encode()


def _fail(result: proc.Result, what: str) -> RuntimeError:
    return RuntimeError((result.stderr or result.stdout or what)[:500])


def gh_runner(loop: asyncio.AbstractEventLoop):
    """A subprocess.run-shaped gh runner over proc.run, for the sync helpers of
    github_lifecycle and pr_patrol that run in worker threads (never call it on the loop thread)."""
    def runner(argv, *, timeout=120, input=None, **_ignored):
        future = asyncio.run_coroutine_threadsafe(proc.run(list(argv), timeout=timeout, stdin=input), loop)
        result = future.result(timeout + 5)
        return subprocess.CompletedProcess(list(argv), result.returncode, result.stdout, result.stderr)
    return runner


async def ensure_clone(repo: str, branch: str) -> Path:
    dest = config.WORK / repo
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = await proc.run(
            ["gh", "repo", "clone", f"{config.ORG}/{repo}", str(dest), "--", "--depth", "1"], timeout=300)
        if result.returncode != 0:
            raise _fail(result, "clone failed")
    await proc.run(["git", "config", "user.name", "simplicio-loop"], cwd=dest)
    email = await proc.run(["git", "config", "user.email"], cwd=dest)
    if email.returncode != 0 or not email.stdout.strip():
        await proc.run(["git", "config", "user.email", "wesleysimplicio@users.noreply.github.com"], cwd=dest)
    fetch = await proc.run(["git", "fetch", "--depth", "1", "origin", branch], cwd=dest, timeout=180)
    if fetch.returncode != 0:
        raise RuntimeError((fetch.stderr or "fetch failed")[:500])
    return dest


async def reset_branch(dest: Path, branch: str, number: int, fix: bool = False) -> str:
    """Check out loop/issue-N from the base branch, or from its open PR head when fixing it."""
    head = f"loop/issue-{number}"
    base = branch
    if fix:
        base = head
        fetch = await proc.run(["git", "fetch", "--depth", "1", "origin", head], cwd=dest, timeout=180)
        if fetch.returncode != 0:
            raise _fail(fetch, "fetch of the PR head failed")
    result = await proc.run(["git", "checkout", "-B", head, f"origin/{base}"], cwd=dest, timeout=60)
    if result.returncode != 0:
        raise _fail(result, "checkout failed")
    return head


def task_text(repo: str, issue: dict, fix: str = "", retry: str = "") -> str:
    body = (issue.get("body") or "").strip()
    if len(body) > config.BODY_CAP:
        body = body[:config.BODY_CAP] + "\n..."
    text = (
        "Para ter o Simplicio-Loop a assinatura do Simplicio MCP precisa estar ativa. "
        "Protocolo Simplicio-Loop, nesta ordem: orientar o repositorio, "
        "planejar uma mudanca atomica, aplicar patch cirurgico "
        "(nao reescrever arquivo inteiro), validar, entregar so o que o teste sustenta.\n"
        f"Repositorio: {config.ORG}/{repo}\n"
        + prompt_guard.untrusted(f"Issue #{issue['number']}: {issue.get('title') or ''}\n{body}")
    )
    if fix:
        text += "\nFeedback de review a corrigir no PR existente (mesma branch):\n" + prompt_guard.untrusted(fix)
    if retry:
        text += "\nA tentativa anterior foi bloqueada por um ponto de extensao; corrija estes motivos:\n" + prompt_guard.untrusted(retry)
    return text


async def dirty(dest: Path) -> bool:
    """True when the worktree has changes beyond the loop state dirs and .gitignore."""
    result = await proc.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=dest)
    for line in result.stdout.splitlines():
        path = line[3:] if len(line) > 3 else line
        if path.startswith(_STATE_DIRS) or path == ".gitignore":
            continue
        return True
    return False


async def commit_and_pr(dest: Path, repo: str, branch: str, head: str, issue: dict, pr: int = 0, label: str = "",
                        executor: str = "exec") -> str | None:
    """Commit the turbo result and push. A fix pushes to its open PR; otherwise a PR is opened. None when there is no diff."""
    if not await dirty(dest):
        return None
    await proc.run(["git", "add", "-A"], cwd=dest)
    await proc.run(["git", "reset", "-q", "--", ".simplicio-loop", ".simplicio"], cwd=dest)  # unstage loop state
    staged = await proc.run(["git", "diff", "--cached", "--name-only"], cwd=dest)
    if not staged.stdout.strip():
        return None
    await secret_scan.check_staged(dest)  # raises SecretDetected: nothing is committed or pushed
    title = f"loop: {issue.get('title') or issue['number']}"
    commit = await proc.run(["git", "commit", "-m", f"{title}\n\nCloses #{issue['number']}\n"], cwd=dest, timeout=60)
    if commit.returncode != 0:
        raise _fail(commit, "commit failed")
    push = await proc.run(["git", "push", "-u", "origin", head], cwd=dest, timeout=180)
    if push.returncode != 0:
        raise _fail(push, "push failed")
    if pr:
        return f"https://github.com/{config.ORG}/{repo}/pull/{pr}"
    body = (
        f"Processamento automatico do Simplicio-Loop 24h (executor {executor}) da issue #{issue['number']}.\n\n"
        f"{label}\n\n"
        f"Closes #{issue['number']}\n"
    )
    created = await proc.run([
        "gh", "pr", "create", "--repo", f"{config.ORG}/{repo}",
        "--base", branch, "--head", head,
        "--title", title[:70], "--body", body,
    ], cwd=dest, timeout=60)
    if created.returncode != 0:
        if "already exists" not in (created.stderr or "").lower():  # the PR may already exist
            raise _fail(created, "pr create failed")
        found = re.search(r"https://\S+", created.stderr)
        return found.group(0) if found else (created.stderr or "").strip()[:200]
    return (created.stdout or "").strip()


async def _run_turbo(dest: Path, repo: str, issue: dict, attempts: int, fix: str,
                     executor: host_mode.Executor, task: str | None = None, role: str = "") -> dict:
    """Run the item with the selected executor; return the claim fields, raise when it did not finish ok.

    exec (the default): an exec CLI plans, turbo --apply - applies (host_mode). openrouter: the opt-in headless turbo.
    """
    test_cmd = await asyncio.to_thread(verify.detect_test_command, dest)
    task = task or task_text(repo, issue, fix)
    if executor.mode == "exec":
        return await host_mode.run_exec(dest, repo, issue, task, test_cmd, executor,
                                        attempts, fix=bool(fix), role=role)
    await budget.record("model_calls")
    argv = sandbox.wrap(verify.turbo_argv(dest, task, test_cmd),
                        clone=dest, state_dir=config.ROOT)
    env = sandbox.scrubbed_env(os.environ, home=Path.home(), keep=("OPENROUTER_API_KEY",))
    result = await proc.run(argv, timeout=config.TURBO_TIMEOUT_S, cwd=dest, env=env)
    log_path = config.LOGS / f"{repo}-{issue['number']}-{attempts}.log"
    await asyncio.to_thread(log_path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        log_path.write_text, (result.stdout or "") + "\n--- stderr ---\n" + (result.stderr or ""))
    document = verify.parse_turbo(result.stdout or "")
    status = document.get("status") or ("ok" if result.returncode == 0 else "failed")
    decision = verify.decide({**document, "status": status}, test_cmd, attempts, config.MAX_ATTEMPTS)
    if decision.action != "pr":
        raise RuntimeError(decision.reason)
    return {"turbo_status": status, "exit_code": result.returncode, "verify": decision.label}


async def _heartbeat(store: ClaimStore, key: str, token: str) -> None:
    """Extend the lease every HEARTBEAT_S while turbo runs; stop when the lease is lost."""
    while True:
        await asyncio.sleep(config.HEARTBEAT_S)
        if not await store.heartbeat(key, token, config.LEASE_TTL_S, now=state.now().timestamp()):
            state.log(f"lease lost {key}")
            return


async def _phase(runner, repo: str, number: int, phase: str, detail: str = "", reason_code: str = "") -> None:
    """Move the issue's ONE status comment to `phase`. A refused or failed update is logged, never raised."""
    try:
        receipt = await watcher_github.post_status(
            repo=f"{config.ORG}/{repo}", issue=str(number), state=phase, detail=detail,
            reason_code=reason_code, runner=runner)
    except Exception as exc:
        state.log(f"status {phase} failed {repo}#{number}: {exc}")
        return
    if not receipt.get("verified"):
        state.log(f"status {phase} not verified {repo}#{number}: {receipt.get('reason_code') or 'unverified'}")


_HINT_POINTS = {"recall": "matches", "reuse_precedent": "reuse"}  # point name -> the evidence key the planner reads
_HINTS_CAP = 2000


def plan_hints(results: list[points.PointResult]) -> str:
    """The memory points' findings (recall, reuse_precedent) as an untrusted-data block for the planner; '' if none."""
    found = {r.name: r.evidence[_HINT_POINTS[r.name]] for r in results
             if r.status == "ok" and r.name in _HINT_POINTS and r.evidence.get(_HINT_POINTS[r.name])}
    if not found:
        return ""
    return "\nPrecedentes anteriores do loop (memoria):\n" + prompt_guard.untrusted(
        json.dumps(found, ensure_ascii=False)[:_HINTS_CAP])


def _note_failed_attempt(ctx: points.PointContext, number: int, reasons: str) -> None:
    """The escalation ladder counts a blocked attempt as a failed one (its ceilings). Fail-open."""
    try:
        ladder = escalation.load_escalation_state(ctx.clone, number, ctx.family, **host_mode.ceilings())
        ladder.record_attempt("failed", error=reasons)
    except Exception as exc:
        state.log(f"escalation note failed {ctx.repo}#{number}: {exc}")


async def process(store: ClaimStore, runner, gate: Gate, work: Work, clock: float,
                  executor: host_mode.Executor) -> squad_flow.Outcome | None:
    name = work.repo
    number = int(work.issue["number"])
    ident = state.key_of(name, number)
    full = f"{config.ORG}/{name}"
    token = await store.acquire(ident, config.OWNER, config.LEASE_TTL_S, now=clock, reopen=bool(work.fix))
    if token is None:
        state.log(f"lease held or final {ident}")
        return
    await budget.record("issues")
    verdict = None if work.fix else intake_gate.triage(work.issue)
    ctx = None
    try:
        claim = await watcher_github.claim_on_github(repo=full, issue=str(number), owner=config.OWNER, runner=runner)
        if not claim.verified:
            await store.release(ident, token, "claimed_elsewhere", now=clock, reason_code=claim.reason)
            state.log(f"claimed elsewhere {ident}: {claim.reason}")
            return
        if verdict is not None and verdict.verdict == "needs_human":
            await _phase(runner, name, number, "BLOCKED", detail=verdict.clarifying_question)
            await store.release(ident, token, "needs_human", now=clock, reason_code=verdict.reason_code)
            state.log(f"needs human {ident}: {verdict.reason_code}")
            return
        await _phase(runner, name, number, "PLANNED", reason_code="REVIEW_REOPENED" if work.fix else "",
                     detail="fix de review na branch do PR" if work.fix else "task montada para o turbo")
        await _phase(runner, name, number, "IN_PROGRESS", detail=f"turbo em execucao (executor {executor.mode})")
        claim_row = await store.get_claim(ident)
        attempts, retry = claim_row.attempts, claim_row.data.get("blocked_by") or ""
        state.log(f"start {ident} attempt {attempts}")
        beat = asyncio.ensure_future(_heartbeat(store, ident, token))
        try:
            async with gate.repo_lock(name):  # one working tree per repo: clone to push is exclusive
                dest = await ensure_clone(name, work.branch)
                head = await reset_branch(dest, work.branch, number, fix=bool(work.fix))
                ctx = points.PointContext(
                    repo=name, issue=work.issue, clone=dest, state_dir=config.ROOT, family=(executor.families or (None,))[0],
                    run_dir=dest / ".simplicio-loop" / "orchestrator" / "points" / f"{name}-{number}")
                await points.run("intake", ctx)
                ctx = replace(ctx, task_text=task_text(name, work.issue, work.fix, retry))
                task = ctx.task_text + plan_hints(await points.run("plan", ctx))  # one text: retry reasons + hints
                turbo = await _run_turbo(dest, name, work.issue, attempts, work.fix, executor, task=task, role=work.role)
                ctx = replace(ctx, turbo_json=turbo, verify=turbo["verify"])
                await points.run("apply", ctx)
                await _phase(runner, name, number, "VERIFYING", detail="turbo ok; publicando o diff")
                await points.run("verify", ctx)
                points.raise_if_blocked("pr", await points.run("pr", ctx))  # a blocked result stops the PR
                url = await commit_and_pr(dest, name, work.branch, head, work.issue, pr=work.pr,
                                          label=turbo["verify"], executor=executor.mode)
                if url:
                    await budget.record("prs")
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        if url:
            await _phase(runner, name, number, "PR_OPEN", detail=f"PR: {url}\n{turbo['verify']}")
            await store.release(ident, token, "done", now=clock, pr=url, **turbo)
        else:
            await _phase(runner, name, number, "BLOCKED", detail="o loop terminou sem diff para abrir PR")
            await store.release(ident, token, "done_no_diff", now=clock, pr=None, **turbo)
        await points.run("done", replace(ctx, pr_url=url))
        state.log(f"done {ident} pr={url}")
        return squad_flow.Outcome(url, turbo["verify"], turbo.get("steps") or []) if url else None
    except points.PointDeferred as exc:  # transient: the attempt is given back and the issue is due on the next tick
        attempts = (await store.get_claim(ident)).attempts
        await _phase(runner, name, number, "BLOCKED", detail=f"deferred: {exc.reason_code}")
        await store.release(ident, token, "retry", now=clock, attempts=max(attempts - 1, 0), reason_code=exc.reason_code)
        state.log(f"point deferred {ident}: {exc}")
    except points.PointBlocked as exc:  # a failed attempt, like a verify failure: retry with the reasons, dead at the limit
        attempts = (await store.get_claim(ident)).attempts
        final = verify.retry_or_dead(attempts, config.MAX_ATTEMPTS)
        reasons = exc.reasons()
        if ctx is not None and executor.mode == "exec":
            _note_failed_attempt(ctx, number, reasons)
        detail = (f"etapa {exc.stage} bloqueada ({reasons}); parou depois de {config.MAX_ATTEMPTS} tentativas; "
                  "fica na fila morta ate reabrir" if final == "dead"
                  else f"tentativa {attempts}: etapa {exc.stage} bloqueada ({reasons})")
        await _phase(runner, name, number, "BLOCKED", detail=detail)
        await store.release(ident, token, final, now=clock, reason_code=exc.reason_code, error=str(exc)[:500],
                            blocked_by=reasons, next_try_at=state.iso(state.now() + config.RETRY_AFTER))
        state.log(f"point blocked {ident} {final}: {exc}")
    except secret_scan.SecretDetected as exc:  # the secret itself is never echoed, only the file names
        await _phase(runner, name, number, "BLOCKED",
                     detail=f"push bloqueado ({exc.reason_code}): segredo detectado em " + ", ".join(exc.files))
        await store.release(ident, token, "dead", now=clock, reason_code=exc.reason_code, error=str(exc)[:500])
        state.log(f"secret blocked {ident}: {', '.join(exc.files)}")
    except Exception as exc:
        attempts = (await store.get_claim(ident)).attempts
        final = verify.retry_or_dead(attempts, config.MAX_ATTEMPTS)
        error = str(exc)[:500]
        detail = (f"parou depois de {config.MAX_ATTEMPTS} tentativas; fica na fila morta ate reabrir"
                  if final == "dead" else f"tentativa {attempts} falhou: {error}")
        await _phase(runner, name, number, "BLOCKED", detail=detail)
        await store.release(ident, token, final, now=clock, reason_code="turbo_failed", error=error, blocked_by="",
                            next_try_at=state.iso(state.now() + config.RETRY_AFTER))
        state.log(f"fail {ident} {final}: {error}")


async def _enqueue_fixes(runner, name: str, fixes: dict) -> None:
    """Queue each new review or CI fix task of the repo's open loop PRs for its issue.

    A task is queued once per text (fingerprint in `seen`), so a review already handled is never
    queued again. A patrol failure is logged; the next tick tries again.
    """
    try:
        found = await watcher_github.patrol_open_prs(repo=f"{config.ORG}/{name}", runner=runner)
    except Exception as exc:
        state.log(f"patrol failed {name}: {exc}")
        return
    for task in found:
        match = re.fullmatch(r"loop/issue-(\d+)", task.head)
        if not match:
            continue
        ident = state.key_of(name, int(match.group(1)))
        fingerprint = hashlib.sha256(f"{ident}\n{task.text}".encode()).hexdigest()[:16]
        if fingerprint in fixes["seen"]:
            continue
        fixes["seen"].append(fingerprint)
        entry = fixes["queued"].setdefault(ident, {"pr": task.pr, "texts": []})
        entry["texts"].append(task.text)


async def tick(dry_run: bool = False) -> None:
    """One pass. dry_run reads GitHub and logs what it would do; it writes no baseline, claims, fixes or status (only the issues-disabled cache) and skips the subscription refresh."""
    persist = not dry_run

    async def status(**extra) -> None:
        if persist:
            await state.write_status(**extra)

    if config.STOP.exists():
        await status(phase="stopped")
        state.log("STOP present")
        return
    if blocked := sandbox.refusal():
        await status(phase="blocked", reason_code=blocked)
        state.log(f"blocked: {blocked}")
        return
    if capped := await budget.reached():
        await status(phase="daily_cap_reached", reason_code="daily_cap_reached", cap=capped,
                     budget=await budget.snapshot())
        state.log(f"daily cap reached: {capped}")
        return
    executor = await host_mode.choose()  # exec by default; preflight of the CLI logins, openrouter only if asked
    if executor.blocked:
        await status(phase="blocked", reason_code=executor.blocked, executor=executor.mode, detail=executor.detail)
        state.log(f"blocked: {executor.blocked}")
        return
    sub = None
    if dry_run:
        state.log("[dry-run] subscription check skipped")
    else:
        sub = await subscription.mcp_subscription()
        if not sub.get("active"):
            await status(phase="subscription_required", subscription=sub)
            state.log("subscription required: " + str(sub.get("reason")))
            return
    clock = state.now().timestamp()
    store = ClaimStore(config.CLAIMS)
    runner = gh_runner(asyncio.get_running_loop())
    if persist:
        for key, claim in (await store.reap_expired(now=clock)).items():
            state.log(f"lease expired {key}: {claim['status']}")
    found = await github.repos()
    baseline = await state.load(config.BASELINE, None)
    fixes = await state.load(config.FIXES, {"queued": {}, "seen": []})
    limit = min(config.concurrency(), await budget.issues_left())
    gate_cache: dict = {}
    seen: list[str] = []
    batch: list[Work] = []
    skipped_repos: dict[str, str] = {}
    skipped_issues: dict[str, str] = {}
    for repo in found:
        if len(batch) >= limit:
            break
        name = repo["name"]
        if name in await state.issues_disabled():
            continue
        try:
            opted = await intake_gate.repo_opted_in(f"{config.ORG}/{name}", cache=gate_cache, run=_intake_run)
        except intake_gate.IntakeGateError as exc:
            skipped_repos[name] = exc.reason_code
            continue
        if not opted:
            skipped_repos[name] = "not_opted_in"
            continue
        if baseline is not None and persist:
            await _enqueue_fixes(runner, name, fixes)
        try:
            issues = await github.open_issues(name)
        except Exception as exc:
            state.log(f"list failed {name}: {exc}")
            continue
        baselined = set(baseline["issues"]) if baseline is not None else set()
        for issue in issues:
            ident = state.key_of(name, int(issue["number"]))
            seen.append(ident)
            if baseline is None:
                continue
            if ident in fixes["queued"]:
                entry = fixes["queued"].pop(ident)
                batch.append(Work(name, repo["branch"], issue, fix="\n".join(entry["texts"]), pr=entry["pr"]))
            elif ident in baselined:
                continue
            elif github.skipped(issue):
                skipped_issues[ident] = "skip_label"
                continue
            elif not intake_gate.issue_admitted(issue):
                skipped_issues[ident] = intake_gate.admission_reason(issue)
                continue
            else:
                batch.append(Work(name, repo["branch"], issue))
            if len(batch) >= limit:
                break
    if persist and baseline is not None:
        await state.save(config.FIXES, fixes)
    if batch:
        idents = [state.key_of(w.repo, int(w.issue["number"])) for w in batch]
        if dry_run:
            for ident in idents:
                state.log(f"[dry-run] would process {ident}")
            return
        gate = Gate()
        plans = squad_flow.form(batch, (executor.families or ("claude",))[0])  # the general coordinator
        outcomes = await asyncio.gather(*(process(store, runner, gate, w, clock, executor) for w in batch))
        squad_status = await squad_flow.finish(plans, batch, outcomes, runner, gate)
        await status(phase="processed", last=idents[-1], processed=idents,
                     repos=len(found), open_seen=len(seen), subscription=sub,
                     skipped_repos=skipped_repos, skipped_issues=skipped_issues, squads=squad_status)
        return
    if baseline is None:
        if persist:
            await state.save(config.BASELINE, {"created_at": state.iso(state.now()), "issues": seen})
        state.log(f"baseline {len(seen)} open issues across {len(found)} repos")
        await status(phase="baselined", repos=len(found), open_seen=len(seen), subscription=sub,
                     skipped_repos=skipped_repos, skipped_issues=skipped_issues)
        return
    await status(phase="idle", repos=len(found), open_seen=len(seen), subscription=sub,
                 skipped_repos=skipped_repos, skipped_issues=skipped_issues)
    state.log(f"idle repos={len(found)} open={len(seen)}")
