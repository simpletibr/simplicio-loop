"""Public CLI adapter that wraps every Stage ABI mutation in the worker."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from .mutation_dispatch import READ_ONLY, route_name
from .mutation_worker import MutationWorker


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and ".simplicio" not in p.parts
    ):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_stage_or_legacy(argv: Sequence[str], legacy: Callable[[list[str]], int]) -> int:
    args = list(argv)
    route = route_name(args)
    if os.environ.get("SIMPLICIO_STAGE_ABI") != "1" or route in READ_ONLY:
        return legacy(args)
    plan_path = Path(os.environ["SIMPLICIO_MECHANICAL_PLAN"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    root = Path(os.environ.get("SIMPLICIO_WORKSPACE", ".")).resolve()
    worker = MutationWorker(root)

    def effect(_sealed):
        before = _tree_hash(root)
        code = legacy(args)
        after = _tree_hash(root)
        return {
            "status": "ok" if code == 0 else "failed",
            "applied": code == 0,
            "before_hash": before,
            "after_hash": after,
            "operations": [{"route": route, "exit_status": code}],
        }

    receipt = worker.execute(plan, effect)
    if not receipt.get("receipt_hash"):
        return 1
    return 0
