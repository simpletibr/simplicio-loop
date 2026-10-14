"""Entry point of the 24/7 watcher: `python -m simplicio_loop.watcher247` or `simplicio-loop watch247`."""
from __future__ import annotations

import argparse
import asyncio

from ..claim_lease import ClaimStore
from ..error_truncation import truncate_error_with_cause
from . import author_executor, config, env_guard, state, tick, worktrees


async def main(once: bool = False, dry_run: bool = False) -> int:
    worktrees.cancel_on_sigterm()  # a stop cancels the tick, and every live item removes its own worktree first
    try:
        return await _serve(once, dry_run)
    except asyncio.CancelledError:
        state.log("SIGTERM: stopped")
        return worktrees.SIGTERM_EXIT


async def _serve(once: bool, dry_run: bool) -> int:
    if invalid := author_executor.refusal():  # a typo must not fall back to the plan flow in silence
        state.log(f"refusing to start: {invalid}")
        if not dry_run:
            await state.write_status(phase="blocked", reason_code=author_executor.INVALID, detail=invalid)
        return 1
    if not dry_run:
        await asyncio.to_thread(config.WORK.mkdir, parents=True, exist_ok=True)
        if refused := env_guard.refusal():
            state.log(f"refusing to start: {refused} ({env_guard.env_file()})")
            await state.write_status(phase="blocked", reason_code=refused)
            return 1
        # Before any lease exists, every legacy running claim (no owner_token) is an orphan of the old watcher.
        await ClaimStore(config.CLAIMS).migrate_legacy(ttl_s=0)
    while True:
        try:
            await tick.tick(dry_run=dry_run)
        except Exception as exc:
            state.log(f"tick error: {exc}")
            if not dry_run:
                await state.write_status(phase="error", error=truncate_error_with_cause(str(exc)))
        if once:
            return 0
        await asyncio.sleep(config.INTERVAL_S)  # STOP keeps the process alive and idle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="simplicio-loop-247")
    parser.add_argument("--once", action="store_true", help="run one tick and exit")
    parser.add_argument("--dry-run", action="store_true", help="read GitHub, log what would run, write nothing")
    parser.add_argument("--state-dir", help="override the state directory")
    args = parser.parse_args()
    if args.state_dir:
        config.set_state_dir(args.state_dir)
    raise SystemExit(asyncio.run(main(once=args.once, dry_run=args.dry_run)))
