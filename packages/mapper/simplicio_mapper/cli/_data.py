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
from ..store.project_scope import resolve_scoped_layout
from ..store.unify import unify_memory, unify_status

VERBS = {"status", "absorb", "layout", "init", "unify"}

_HELP = """usage: simplicio-mapper data <verb> [options]

Scoped data hub under .simplicio (no cross-project mixing):

  Core / Runtime:   ~/.simplicio/data/memory.sqlite
  Project:          <repo>/.simplicio/data/<slug>/memory.sqlite

  slug from: SIMPLICIO_PROJECT | git remote name | Codex/Cursor/Claude/Gemini
             workspace name | directory name

Verbs:
  layout                 print scoped layout (core + project)
  status                 inventory core (+ project when --repo)
  absorb [--bank ID]     copy legacy sources into the active data root
  unify                  ensure memory.sqlite + bridge neural + FTS (core and/or project)
  init                   ensure banks, absorb, unify for core (+ project with --repo)

Options:
  --data-dir PATH    override core data root
  --repo PATH        project root → isolates under PATH/.simplicio/data/<slug>
  --project SLUG     force project slug (overrides git/host inference)
  --bank ID          absorb a single bank
  --source PATH      explicit source for single --bank absorb
  --no-backup        skip backup of existing destination
  --json             machine-readable receipt
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
    project = None
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
        if opt == "--project" and i + 1 < len(argv):
            project = argv[i + 1]
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
        layout = resolve_scoped_layout(
            repo_root=repo,
            project=project,
            data_dir=data_dir,
            home=Path.home(),
            include_project=bool(repo or project),
        )
        if verb == "layout":
            payload = {**layout_tree(), "resolved": layout.as_dict()}
        elif verb == "status":
            # Core inventory always; project inventory when scoped.
            catalog = data_status(data_dir=str(layout.core.root))
            mem = unify_status(data_dir=str(layout.core.root))
            project_mem = None
            if layout.project is not None:
                project_mem = unify_status(data_dir=str(layout.project.root))
            fast = mapper_fast_status(repo=repo, data_dir=str(layout.core.root))
            payload = {
                **catalog,
                "scopes": layout.as_dict(),
                "memory_unify": mem,
                "project_memory_unify": project_mem,
                "mapper_fast": fast,
                "env_hints": {
                    **(mem.get("env_hints") or {}),
                    **(fast.get("env_hints") or {}),
                },
            }
        elif verb == "unify":
            # Unify core always; also project when --repo given.
            core = unify_memory(
                data_dir=str(layout.core.root),
                absorb_legacy_home=True,
                rebuild_fts=True,
            )
            project_u = None
            if layout.project is not None:
                layout.project.ensure_root()
                project_u = unify_memory(
                    data_dir=str(layout.project.root),
                    absorb_legacy_home=False,
                    rebuild_fts=True,
                )
            payload = {
                "schema": core.get("schema"),
                "status": core.get("status"),
                "scopes": layout.as_dict(),
                "core": core,
                "project": project_u,
                "mapper_fast": mapper_fast_status(repo=repo, data_dir=str(layout.core.root)),
                "env_hints": core.get("env_hints"),
            }
        elif verb == "absorb":
            target = str(layout.project.root) if layout.project is not None else str(layout.core.root)
            Path(target).mkdir(parents=True, exist_ok=True)
            if bank:
                payload = absorb_bank(
                    bank,
                    data_dir=target,
                    source=source,
                    backup=backup,
                    repo_root=repo,
                )
            else:
                payload = absorb_all(
                    data_dir=target,
                    backup=backup,
                    repo_root=repo,
                )
            payload["scopes"] = layout.as_dict()
        else:  # init
            layout.core.ensure_root()
            mem = ensure_mapper_memory(data_dir=str(layout.core.root))
            neural = bootstrap_neural(data_dir=str(layout.core.root), apply_seeds=False)
            absorbed = absorb_all(data_dir=str(layout.core.root), backup=backup, repo_root=repo)
            unified = unify_memory(
                data_dir=str(layout.core.root),
                absorb_legacy_home=True,
                rebuild_fts=True,
            )
            project_u = None
            if layout.project is not None:
                layout.project.ensure_root()
                project_u = unify_memory(
                    data_dir=str(layout.project.root),
                    absorb_legacy_home=False,
                    rebuild_fts=True,
                )
            fast = mapper_fast_status(repo=repo, data_dir=str(layout.core.root))
            payload = {
                "schema": absorbed["schema"],
                "status": "initialized" if unified.get("status") == "ready" else "degraded",
                "scopes": layout.as_dict(),
                "data_root": str(layout.core.root),
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
                "project_unify": project_u,
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
