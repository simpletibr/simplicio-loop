"""Mandatory pre-dispatch Hookwall guard for every Stage ABI mutation route."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Mapping, Sequence
from .mutation_lifecycle import MUTABLE_ENTRYPOINTS
from .mutation_worker import MutationBlocked, validate

READ_ONLY = {"status","claims","inspect","doctor","versions","file","detect","runtime","fast"}

def route_name(argv: Sequence[str]) -> str:
    if not argv: return ""
    for length in range(min(3,len(argv)),0,-1):
        candidate=".".join(argv[:length])
        if candidate in MUTABLE_ENTRYPOINTS:
            return candidate
    return argv[0]

def guard_mutable_dispatch(argv: Sequence[str], environ: Mapping[str,str]|None=None) -> None:
    env=dict(os.environ if environ is None else environ)
    route=route_name(argv)
    if route in READ_ONLY or route not in MUTABLE_ENTRYPOINTS:
        return
    if env.get("SIMPLICIO_STAGE_ABI") != "1":
        return  # compatibility lane; never presented as Stage ABI
    path=env.get("SIMPLICIO_MECHANICAL_PLAN","")
    if not path: raise MutationBlocked("MECHANICAL_PLAN_REQUIRED")
    plan_path=Path(path)
    try: plan=json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc: raise MutationBlocked("MECHANICAL_PLAN_INVALID") from exc
    root=Path(env.get("SIMPLICIO_WORKSPACE",".")).resolve()
    sealed=validate(plan,root)
    expected=env.get("SIMPLICIO_IDEMPOTENCY_KEY")
    if not expected or sealed["idempotency_key"] != expected:
        raise MutationBlocked("IDEMPOTENCY_KEY_REQUIRED")
