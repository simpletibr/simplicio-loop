"""One watcher tick: gate, discover new issues, process the due ones."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from . import config, github, proc, state, subscription

_STATE_DIRS = (".simplicio-loop/", ".simplicio/")


class Gate:
    """One lock per repo; the tick itself caps the batch at SIMPLICIO_247_CONCURRENCY issues."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def repo_lock(self, repo: str) -> asyncio.Lock:
        return self._locks.setdefault(repo, asyncio.Lock())


def _fail(result: proc.Result, what: str) -> RuntimeError:
    return RuntimeError((result.stderr or result.stdout or what)[:500])


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


async def reset_branch(dest: Path, branch: str, number: int) -> str:
    head = f"loop/issue-{number}"
    result = await proc.run(["git", "checkout", "-B", head, f"origin/{branch}"], cwd=dest, timeout=60)
    if result.returncode != 0:
        raise _fail(result, "checkout failed")
    return head


def task_text(repo: str, issue: dict) -> str:
    body = (issue.get("body") or "").strip()
    if len(body) > config.BODY_CAP:
        body = body[:config.BODY_CAP] + "\n..."
    return (
        "Para ter o Simplicio-Loop a assinatura do Simplicio MCP precisa estar ativa. "
        "Protocolo Simplicio-Loop, nesta ordem: orientar o repositorio, "
        "planejar uma mudanca atomica, aplicar patch cirurgico "
        "(nao reescrever arquivo inteiro), validar, entregar so o que o teste sustenta.\n"
        f"Repositorio: {config.ORG}/{repo}\n"
        f"Issue #{issue['number']}: {issue.get('title') or ''}\n"
        f"{body}"
    )


def parse_turbo(stdout: str) -> dict:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.rfind('{"schema"')
        if start < 0:
            start = text.rfind("{")
        if start < 0:
            return {"status": "failed", "detail": text[-400:]}
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            return {"status": "failed", "detail": text[-400:]}


async def dirty(dest: Path) -> bool:
    """True when the worktree has changes beyond the loop state dirs and .gitignore."""
    result = await proc.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=dest)
    for line in result.stdout.splitlines():
        path = line[3:] if len(line) > 3 else line
        if path.startswith(_STATE_DIRS) or path == ".gitignore":
            continue
        return True
    return False


async def commit_and_pr(dest: Path, repo: str, branch: str, head: str, issue: dict) -> str | None:
    """Commit the turbo result, push and open the PR. None when there is no diff."""
    if not await dirty(dest):
        return None
    await proc.run(["git", "add", "-A"], cwd=dest)
    await proc.run(["git", "reset", "-q", "--", ".simplicio-loop", ".simplicio"], cwd=dest)  # unstage loop state
    staged = await proc.run(["git", "diff", "--cached", "--name-only"], cwd=dest)
    if not staged.stdout.strip():
        return None
    title = f"loop: {issue.get('title') or issue['number']}"
    commit = await proc.run(["git", "commit", "-m", f"{title}\n\nCloses #{issue['number']}\n"], cwd=dest, timeout=60)
    if commit.returncode != 0:
        raise _fail(commit, "commit failed")
    push = await proc.run(["git", "push", "-u", "origin", head], cwd=dest, timeout=180)
    if push.returncode != 0:
        raise _fail(push, "push failed")
    body = (
        f"Processamento automatico do Simplicio-Loop 24h (turbo, provider openrouter) da issue #{issue['number']}.\n\n"
        f"Closes #{issue['number']}\n"
    )
    pr = await proc.run([
        "gh", "pr", "create", "--repo", f"{config.ORG}/{repo}",
        "--base", branch, "--head", head,
        "--title", title[:70], "--body", body,
    ], cwd=dest, timeout=60)
    if pr.returncode != 0:
        if "already exists" not in (pr.stderr or "").lower():  # the PR may already exist
            raise _fail(pr, "pr create failed")
        found = re.search(r"https://\S+", pr.stderr)
        return found.group(0) if found else (pr.stderr or "").strip()[:200]
    return (pr.stdout or "").strip()


async def _run_turbo(dest: Path, repo: str, issue: dict, claim: dict, ident: str) -> str:
    """Run headless turbo; return its status, raise when it did not finish ok."""
    result = await proc.run([
        "simplicio-loop", "turbo",
        "--repo", str(dest),
        "--provider", "openrouter",
        "--task", task_text(repo, issue),
    ], timeout=config.TURBO_TIMEOUT_S)
    log_path = config.LOGS / f"{repo}-{issue['number']}-{claim['attempts']}.log"
    await asyncio.to_thread(log_path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        log_path.write_text, (result.stdout or "") + "\n--- stderr ---\n" + (result.stderr or ""))
    document = parse_turbo(result.stdout or "")
    status = document.get("status") or ("ok" if result.returncode == 0 else "failed")
    claim["turbo_status"] = status
    claim["exit_code"] = result.returncode
    if status != "ok":
        raise RuntimeError(document.get("detail") or document.get("reason_code") or status)
    return status


async def process(repo: dict, issue: dict, claims: dict, gate: Gate) -> None:
    name = repo["name"]
    number = int(issue["number"])
    ident = state.key_of(name, number)
    claim = claims.get(ident) or {"attempts": 0}
    claim["attempts"] = int(claim.get("attempts") or 0) + 1
    claim["status"] = "running"
    claim["started_at"] = state.iso(state.now())
    claims[ident] = claim
    await state.save(config.CLAIMS, claims)
    state.log(f"start {ident} attempt {claim['attempts']}")
    await github.comment(
        name, number,
        f"Simplicio-Loop 24h comecou o processamento na branch `loop/issue-{number}` "
        "(turbo, provider openrouter). A assinatura do Simplicio MCP esta ativa.")
    try:
        async with gate.repo_lock(name):  # one working tree per repo: clone to push is exclusive
            dest = await ensure_clone(name, repo["branch"])
            head = await reset_branch(dest, repo["branch"], number)
            await _run_turbo(dest, name, issue, claim, ident)
            url = await commit_and_pr(dest, name, repo["branch"], head, issue)
        claim["status"] = "done" if url else "done_no_diff"
        claim["pr"] = url
        claim["finished_at"] = state.iso(state.now())
        if url:
            await github.comment(name, number, f"Processamento concluido. PR: {url}")
        else:
            await github.comment(name, number, "O loop terminou sem diff para abrir PR.")
        state.log(f"done {ident} pr={url}")
    except Exception as exc:
        claim["status"] = "dead" if claim["attempts"] >= config.MAX_ATTEMPTS else "retry"
        claim["error"] = str(exc)[:500]
        claim["next_try_at"] = state.iso(state.now() + config.RETRY_AFTER)
        claim["finished_at"] = state.iso(state.now())
        state.log(f"fail {ident} {claim['status']}: {claim['error']}")
        if claim["status"] == "dead":
            await github.comment(
                name, number,
                f"Simplicio-Loop parou esta issue depois de {config.MAX_ATTEMPTS} tentativas. "
                "Ela fica na fila morta local ate alguem reabrir o processamento.")
    claims[ident] = claim
    await state.save(config.CLAIMS, claims)


async def tick(dry_run: bool = False) -> None:
    """One pass. dry_run reads GitHub and logs what it would do; it writes no baseline, claims or status (only the issues-disabled cache) and skips the subscription refresh."""
    persist = not dry_run

    async def status(**extra) -> None:
        if persist:
            await state.write_status(**extra)

    if config.STOP.exists():
        await status(phase="stopped")
        state.log("STOP present")
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
    found = await github.repos()
    claims = await state.load(config.CLAIMS, {})
    baseline = await state.load(config.BASELINE, None)
    limit = config.concurrency()
    seen: list[str] = []
    batch: list[tuple[dict, dict]] = []
    for repo in found:
        if len(batch) >= limit:
            break
        if repo["name"] in await state.issues_disabled():
            continue
        try:
            issues = await github.open_issues(repo["name"])
        except Exception as exc:
            state.log(f"list failed {repo['name']}: {exc}")
            continue
        for issue in issues:
            ident = state.key_of(repo["name"], int(issue["number"]))
            seen.append(ident)
            if baseline is None:
                continue
            if github.skipped(issue):
                claims[ident] = {"status": "skipped"}
                continue
            if ident not in baseline["issues"] and state.due(ident, claims):
                batch.append((repo, issue))
                if len(batch) >= limit:
                    break
    if batch:
        idents = [state.key_of(r["name"], int(i["number"])) for r, i in batch]
        if dry_run:
            for ident in idents:
                state.log(f"[dry-run] would process {ident}")
            return
        await state.save(config.CLAIMS, claims)
        gate = Gate()
        await asyncio.gather(*(process(r, i, claims, gate) for r, i in batch))
        await status(phase="processed", last=idents[-1], processed=idents,
                     repos=len(found), open_seen=len(seen), subscription=sub)
        return
    if baseline is None:
        if persist:
            await state.save(config.BASELINE, {"created_at": state.iso(state.now()), "issues": seen})
        state.log(f"baseline {len(seen)} open issues across {len(found)} repos")
        await status(phase="baselined", repos=len(found), open_seen=len(seen), subscription=sub)
        return
    if persist:
        await state.save(config.CLAIMS, claims)
    await status(phase="idle", repos=len(found), open_seen=len(seen), subscription=sub)
    state.log(f"idle repos={len(found)} open={len(seen)}")
