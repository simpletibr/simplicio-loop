"""Entry point of the 24/7 watcher: `python -m simplicio_loop.watcher247` or `simplicio-loop watch247`."""
from __future__ import annotations

import argparse
import asyncio

from . import config, state, tick


async def main(once: bool = False, dry_run: bool = False) -> int:
    if not dry_run:
        await asyncio.to_thread(config.WORK.mkdir, parents=True, exist_ok=True)
    while True:
        try:
            await tick.tick(dry_run=dry_run)
        except Exception as exc:
            state.log(f"tick error: {exc}")
            if not dry_run:
                await state.write_status(phase="error", error=str(exc)[:500])
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
