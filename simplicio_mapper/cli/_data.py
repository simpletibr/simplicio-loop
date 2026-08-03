"""CLI: simplicio-mapper data status|absorb|layout|init|unify"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..store.catalog import (
    absorb_all,
    absorb_bank,
    data_status,
    ensure_mapper_memory,
    layout_tree,
)
from ..store.fast_link import mapper_fast_status
from ..store.neural import bootstrap_neural
from ..store.unify import unify_memory, unify_status

VERBS = {"status", "absorb", "layout", "init", "unify"}

_HELP = """usage: simplicio-mapper data <verb> [options]

Ecosystem data hub — Mapper centralizes every durable bank under SIMPLICIO_DATA_DIR.

Canonical memory SoT (single SQLite): $SIMPLICIO_DATA_DIR/memory.sqlite
  MapperStore schema + FTS5. Runtime/MCP/agents must use this path.
Legacy neural (simplicio-memory.sqlite) is absorbed and bridged by `unify`.

Verbs:
  layout                 print canonical layout (all banks + paths)
  status                 inventory Mapper root vs legacy ~/.simplicio sources
  absorb [--bank ID]     copy legacy sources into Mapper root (default: all banks)
  unify                  ensure memory.sqlite schema + bridge neural data + FTS rebuild
  init                   ensure banks, absorb legacy, unify into single SoT

Mapper↔Fast (repo-scoped, always with global memory SoT):
  status --repo PATH     also reports fast-handoff / .sfast / project-map readiness
  init --repo PATH       same + unify memory so Fast/Runtime share loaded data

Options:
  --data-dir PATH   override SIMPLICIO_DATA_DIR
  --repo PATH       also scan repo .simplicio for agents.db / operations.sqlite / Fast
  --bank ID         absorb a single bank (repeatable via multiple invocations)
  --source PATH     explicit source for single --bank absorb
  --no-backup       skip backup of existing destination
  --json            machine-readable receipt
"""


def _emit(payload: dict, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    else:
        if payload.get("schema") and "banks" in payload and "layout" not in str(payload.get("schema")):
            root = payload.get("data_root")
            print(f"data root: {root} ({payload.get('root_source') or payload.get('status')})")
            for bank in payload.get("banks") or []:
                print(f"  [{bank['status']:16}] {bank['id']:24} → {bank['relative']}")
            if payload.get("summary"):
                s = payload["summary"]
                print(f"ready={s.get('banks_ready')}/{s.get('banks_total')} missing_required={s.get('required_missing')}")
        elif payload.get("banks") and payload.get("root_env"):
            print(f"SIMPLICIO_DATA_DIR layout ({payload.get('default_root')}):")
            for bank in payload["banks"]:
                req = "required" if bank.get("required") else "optional"
                print(f"  {bank['path']:40} {bank['id']:24} [{req}]")
        else:
            status = payload.get("status", "ok")
            root = payload.get("data_root") or payload.get("destination")
            print(f"data {status}: {root}")
            if payload.get("absorbed") is not None:
                print(
                    f"  absorbed={len(payload.get('absorbed') or [])} "
                    f"unchanged={len(payload.get('unchanged') or [])} "
                    f"skipped={len(payload.get('skipped') or [])}"
                )
            env = payload.get("env_hints") or {}
            for key, value in env.items():
                print(f"  export {key}={value}")
    return 0


def run_data_cli(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(_HELP, end="")
        return 0 if argv and argv[0] in {"-h", "--help"} else 2
    verb = argv[0]
    if verb not in VERBS:
        print(_HELP, end="", file=sys.stderr)
        return 2
    json_mode = "--json" in argv
    backup = "--no-backup" not in argv
    data_dir = None
    repo = None
    bank = None
    source = None
    i = 1
    while i < len(argv):
        opt = argv[i]
        if opt in {"--json", "--no-backup"}:
            i += 1
            continue
        if opt == "--data-dir" and i + 1 < len(argv):
            data_dir = argv[i + 1]
            i += 2
            continue
        if opt == "--repo" and i + 1 < len(argv):
            repo = argv[i + 1]
            i += 2
            continue
        if opt == "--bank" and i + 1 < len(argv):
            bank = argv[i + 1]
            i += 2
            continue
        if opt == "--source" and i + 1 < len(argv):
            source = argv[i + 1]
            i += 2
            continue
        print(f"unknown option: {opt}", file=sys.stderr)
        return 1
    try:
        if verb == "layout":
            payload = layout_tree()
        elif verb == "status":
            catalog = data_status(data_dir=data_dir)
            mem = unify_status(data_dir=data_dir)
            fast = mapper_fast_status(repo=repo, data_dir=data_dir)
            payload = {
                **catalog,
                "memory_unify": mem,
                "mapper_fast": fast,
                "env_hints": {**(mem.get("env_hints") or {}), **(fast.get("env_hints") or {})},
            }
        elif verb == "unify":
            payload = unify_memory(data_dir=data_dir, absorb_legacy_home=True, rebuild_fts=True)
            payload["mapper_fast"] = mapper_fast_status(repo=repo, data_dir=data_dir)
        elif verb == "absorb":
            if bank:
                payload = absorb_bank(
                    bank,
                    data_dir=data_dir,
                    source=source,
                    backup=backup,
                    repo_root=repo,
                )
            else:
                payload = absorb_all(
                    data_dir=data_dir,
                    backup=backup,
                    repo_root=repo,
                )
        else:  # init
            mem = ensure_mapper_memory(data_dir=data_dir)
            neural = bootstrap_neural(data_dir=data_dir, apply_seeds=False)
            absorbed = absorb_all(data_dir=data_dir, backup=backup, repo_root=repo)
            unified = unify_memory(
                data_dir=data_dir,
                absorb_legacy_home=True,
                rebuild_fts=True,
            )
            fast = mapper_fast_status(repo=repo, data_dir=data_dir)
            payload = {
                "schema": absorbed["schema"],
                "status": "initialized" if unified.get("status") == "ready" else "degraded",
                "data_root": absorbed["data_root"],
                "mapper_memory": mem,
                "neural": {
                    "database": neural.get("database"),
                    "migrations_present": neural.get("migrations_present"),
                    "memory_items": neural.get("memory_items"),
                    "role": "legacy_absorb_source",
                },
                "canonical_memory": unified.get("canonical_database"),
                "unify": {
                    "status": unified.get("status"),
                    "semantic_items": unified.get("semantic_items"),
                    "memory_entries": unified.get("memory_entries"),
                    "fts": unified.get("fts"),
                },
                "mapper_fast": fast,
                "absorb": absorbed,
                "env_hints": {
                    **(unified.get("env_hints") or absorbed.get("env_hints") or {}),
                    **(fast.get("env_hints") or {}),
                },
            }
    except Exception as error:  # noqa: BLE001
        err = {
            "schema": "simplicio.mapper-store.error/v1",
            "ok": False,
            "reason": str(error),
            "reason_code": type(error).__name__,
        }
        print(json.dumps(err, sort_keys=True) if json_mode else str(error), file=sys.stderr)
        return 1
    return _emit(payload, json_mode)


__all__ = ["VERBS", "run_data_cli"]
