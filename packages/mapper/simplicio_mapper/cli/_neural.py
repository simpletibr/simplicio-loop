"""CLI: simplicio-mapper neural init|absorb|status|seed"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from ..store.neural import (
    NeuralBankError,
    absorb_runtime_neural,
    bootstrap_neural,
    neural_status,
    seed_neural,
)

VERBS = {"init", "absorb", "status", "seed"}

_HELP = """usage: simplicio-mapper neural <verb> [options]

Centralize Runtime neural bank under Mapper data root (SIMPLICIO_DATA_DIR).

Verbs:
  status                 show Mapper-owned neural DB status
  init [--seed]          create DB + apply packaged migrations (+ optional seeds)
  absorb [--source PATH] copy Runtime ~/.simplicio/memory/simplicio-memory.sqlite into Mapper root
  seed                   load packaged seeds.sql into existing Mapper neural DB

Options:
  --data-dir PATH   override store root (default SIMPLICIO_DATA_DIR or ~/data)
  --json            machine-readable receipt
"""


def _emit(payload: dict, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        status = payload.get("status", "ok")
        db = payload.get("database") or payload.get("destination")
        items = payload.get("memory_items")
        print(f"neural {status}: {db} items={items}")
    return 0 if payload.get("status") not in {"corrupt", "missing"} or payload.get("schema") else 0


def run_neural_cli(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(_HELP, end="")
        return 0 if argv and argv[0] in {"-h", "--help"} else 2
    verb = argv[0]
    if verb not in VERBS:
        return 2
    json_mode = "--json" in argv
    data_dir = None
    source = None
    apply_seed_flag = "--seed" in argv
    i = 1
    while i < len(argv):
        opt = argv[i]
        if opt == "--json":
            i += 1
            continue
        if opt == "--seed":
            i += 1
            continue
        if opt == "--data-dir" and i + 1 < len(argv):
            data_dir = argv[i + 1]
            i += 2
            continue
        if opt == "--source" and i + 1 < len(argv):
            source = argv[i + 1]
            i += 2
            continue
        return 1
    try:
        if verb == "status":
            payload = neural_status(data_dir=data_dir)
        elif verb == "init":
            payload = bootstrap_neural(data_dir=data_dir, apply_seeds=apply_seed_flag)
        elif verb == "absorb":
            payload = absorb_runtime_neural(source=source, data_dir=data_dir)
        else:  # seed
            status = neural_status(data_dir=data_dir)
            if not status.get("exists"):
                payload = bootstrap_neural(data_dir=data_dir, apply_seeds=True)
            else:
                db = Path(str(status["database"]))
                with closing(sqlite3.connect(db)) as conn:
                    report = seed_neural(conn)
                    conn.commit()
                payload = {**status, "status": "seeded", "seeds": report}
    except NeuralBankError as error:
        err = {
            "schema": "simplicio.mapper-store.error/v1",
            "ok": False,
            "reason_code": error.reason_code,
            "reason": str(error),
        }
        print(json.dumps(err, sort_keys=True) if json_mode else str(error), file=sys.stderr)
        return 1
    return _emit(payload, json_mode)


__all__ = ["VERBS", "run_neural_cli"]
