"""Entry point for the 24/7 watcher."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
from . import config, github, state, tick


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def log(msg: str) -> None:
    dt = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'{dt} {msg}', flush=True)


async def main(once: bool = False, dry_run: bool = False) -> int:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.WORK.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            await tick_one(log, dry_run)
        except Exception as exc:
            log(f'tick error: {exc}')
            await state.save(config.STATUS, {'phase': 'error', 'error': str(exc)[:500], 'updated_at': iso(state.now())})
        
        if once or config.STOP.exists():
            break
        
        await asyncio.sleep(config.INTERVAL_S)
    
    return 0


async def tick_one(log_fn, dry_run: bool = False) -> None:
    if config.STOP.exists():
        await state.save(config.STATUS, {'phase': 'stopped', 'updated_at': iso(state.now())})
        log_fn('STOP present')
        return
    
    found = await github.repos()
    claims = await state.load(config.CLAIMS, {})
    baseline = await state.load(config.BASELINE, None)
    seen = []
    
    for repo in found:
        try:
            issues = await github.open_issues(repo['name'])
        except Exception as exc:
            log_fn(f'list failed {repo["name"]}: {exc}')
            continue
        
        for issue in issues:
            ident = state.key_of(repo['name'], int(issue['number']))
            seen.append(ident)
            if baseline is None:
                continue
            if github.skipped(issue):
                claims[ident] = {'status': 'skipped'}
                continue
            if ident not in baseline['issues'] and state.due(ident, claims):
                await state.save(config.CLAIMS, claims)
                if baseline is None:
                    break
                if not dry_run:
                    await tick.process(repo, issue, claims, log_fn)
                else:
                    log_fn(f'[dry-run] would process {ident}')
                await state.save(config.STATUS, {'phase': 'processed', 'last': ident, 'repos': len(found), 'open_seen': len(seen), 'updated_at': iso(state.now())})
                return
    
    if baseline is None:
        await state.save(config.BASELINE, {'created_at': iso(state.now()), 'issues': seen})
        log_fn(f'baseline {len(seen)} open issues across {len(found)} repos')
        await state.save(config.STATUS, {'phase': 'baselined', 'repos': len(found), 'open_seen': len(seen), 'updated_at': iso(state.now())})
        return
    
    await state.save(config.CLAIMS, claims)
    await state.save(config.STATUS, {'phase': 'idle', 'repos': len(found), 'open_seen': len(seen), 'updated_at': iso(state.now())})
    log_fn(f'idle repos={len(found)} open={len(seen)}')


if __name__ == '__main__':
    once = '--once' in sys.argv
    dry_run = '--dry-run' in sys.argv
    raise SystemExit(asyncio.run(main(once=once, dry_run=dry_run)))
