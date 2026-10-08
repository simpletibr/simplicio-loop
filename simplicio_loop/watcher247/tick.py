"""Issue processing logic."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from . import config, github, state


async def ensure_clone(repo: str, branch: str) -> Path:
    """Clone or update repo."""
    dest = config.WORK / repo
    if not (dest / '.git').exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            'gh', 'repo', 'clone', f'{config.ORG}/{repo}', str(dest), '--', '--depth', '1',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            raise RuntimeError('clone failed')
    proc = await asyncio.create_subprocess_exec(
        'git', 'fetch', '--depth', '1', 'origin', branch,
        cwd=str(dest), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    if proc.returncode != 0:
        raise RuntimeError('fetch failed')
    return dest


async def reset_branch(dest: Path, branch: str, number: int) -> str:
    """Create and checkout topic branch."""
    head = f'loop/issue-{number}'
    proc = await asyncio.create_subprocess_exec(
        'git', 'checkout', '-B', head, f'origin/{branch}',
        cwd=str(dest), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError('checkout failed')
    return head


def task_text(repo: str, issue: dict) -> str:
    """Build task for turbo."""
    body = (issue.get('body') or '').strip()
    if len(body) > config.BODY_CAP:
        body = body[:config.BODY_CAP] + '...'
    return (
        'Protocolo Simplicio-Loop, 50 pontos: '
        f'Repositorio: {config.ORG}/{repo}. '
        f'Issue #{issue.get("number")}: {issue.get("title", "")}. '
        f'{body}'
    )


async def commit_and_pr(dest: Path, repo: str, branch: str, head: str, issue: dict) -> str | None:
    """Commit and open PR."""
    proc = await asyncio.create_subprocess_exec(
        'git', 'add', '-A',
        cwd=str(dest), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), timeout=30)
    
    proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', f'loop: {issue.get("title", issue["number"])}',
        cwd=str(dest), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        return None
    
    proc = await asyncio.create_subprocess_exec(
        'git', 'push', '-u', 'origin', head,
        cwd=str(dest), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    if proc.returncode != 0:
        raise RuntimeError('push failed')
    
    return 'PR created'


async def process(repo: dict, issue: dict, claims: dict, log_fn) -> None:
    """Process one issue."""
    name = repo['name']
    number = int(issue['number'])
    ident = state.key_of(name, number)
    claim = claims.get(ident) or {'attempts': 0}
    claim['attempts'] = int(claim.get('attempts') or 0) + 1
    claim['status'] = 'running'
    claim['started_at'] = state.iso(state.now())
    claims[ident] = claim
    await state.save(config.CLAIMS, claims)
    log_fn(f'start {ident}')
    
    try:
        dest = await ensure_clone(name, repo['branch'])
        head = await reset_branch(dest, repo['branch'], number)
        log_fn(f'done {ident}')
        claim['status'] = 'done'
        claim['finished_at'] = state.iso(state.now())
    except Exception as exc:
        claim['status'] = 'dead' if claim['attempts'] >= config.MAX_ATTEMPTS else 'retry'
        claim['error'] = str(exc)[:500]
        claim['next_try_at'] = state.iso(state.now() + config.RETRY_AFTER)
        claim['finished_at'] = state.iso(state.now())
        log_fn(f'fail {ident}: {exc}')
    
    claims[ident] = claim
    await state.save(config.CLAIMS, claims)
