"""``python -m simplicio_loop.langfuse_export`` — run one export cycle for a repo.

The operator passes the loop.toml they want honoured (the watcher passes the default branch's copy);
nothing here reads a clone's loop.toml on its own.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

from .config import load_config
from .exporter import export_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m simplicio_loop.langfuse_export",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="repo whose execution report is exported",
    )
    parser.add_argument(
        "--loop-toml",
        required=True,
        type=Path,
        help="loop.toml to honour (default branch copy)",
    )
    parser.add_argument(
        "--run-dir", type=Path, default=None, help="run directory holding events.jsonl"
    )
    parser.add_argument(
        "--force", action="store_true", help="flush now, ignoring the batch window"
    )
    args = parser.parse_args(argv)
    table = tomllib.loads(args.loop_toml.read_text(encoding="utf-8"))
    config = load_config(table, env=os.environ)
    result = export_once(
        args.repo, config=config, run_dir=args.run_dir, force=args.force
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") in ("ok", "disabled") else 1


if __name__ == "__main__":
    sys.exit(main())
