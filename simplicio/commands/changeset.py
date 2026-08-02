"""CLI adapter for Fast changeset v2."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._shared import read_binary_source

MAPPER_FAST_HANDOFF_SCHEMA = "simplicio.mapper-fast-handoff/v1"
MAPPER_FAST_RECEIPT_SCHEMA = "simplicio.mapper-fast-handoff-receipt/v1"
MAPPER_REFRESH_TIMEOUT_SECONDS = 800


def _mapper_refresh_producer(root: Path, paths: tuple[str, ...]) -> dict[str, Any]:
    """Refresh Mapper once for all committed paths, without a JSON temp file."""

    executable = shutil.which("simplicio-mapper")
    if executable is None:
        raise RuntimeError("simplicio-mapper executable not found")

    selected = tuple(dict.fromkeys(path.replace("\\", "/") for path in paths if path))
    if not selected:
        return {
            "producer": "simplicio-mapper",
            "subprocesses": 0,
            "status": "parsed",
            "changed_paths": [],
            "reason": "no_changed_paths",
        }

    command = [executable, "fast-handoff", str(root)]
    for path in selected:
        command.extend(("--changed-path", path))
    command.extend(("--expect-schema", MAPPER_FAST_HANDOFF_SCHEMA))
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=MAPPER_REFRESH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Mapper refresh process failed: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Mapper refresh exited with status {completed.returncode}")
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Mapper refresh returned invalid JSON") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("Mapper refresh returned a non-object envelope")

    handoff = envelope.get("handoff")
    receipt = envelope.get("receipt")
    if not isinstance(handoff, dict) or handoff.get("schema") != MAPPER_FAST_HANDOFF_SCHEMA:
        raise RuntimeError("Mapper refresh returned an unsupported handoff schema")
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != MAPPER_FAST_RECEIPT_SCHEMA
        or receipt.get("status") not in {"parsed", "reused"}
    ):
        raise RuntimeError("Mapper refresh did not return a parsed receipt")
    delta = handoff.get("delta")
    changed_paths = delta.get("changed_paths") if isinstance(delta, dict) else None
    normalized_changed = (
        tuple(path.replace("\\", "/") for path in changed_paths)
        if isinstance(changed_paths, list) and all(isinstance(path, str) for path in changed_paths)
        else ()
    )
    if set(normalized_changed) != set(selected):
        raise RuntimeError("Mapper refresh changed-path set does not match the committed changeset")
    generation = receipt.get("generation")
    if not isinstance(generation, str) or not generation:
        raise RuntimeError("Mapper refresh receipt has no generation")

    counters = receipt.get("counters")
    return {
        "producer": "simplicio-mapper",
        "subprocesses": 1,
        "schema": MAPPER_FAST_RECEIPT_SCHEMA,
        "status": receipt["status"],
        "generation": generation,
        "revision": handoff.get("revision"),
        "changed_paths": list(selected),
        "counters": dict(counters) if isinstance(counters, dict) else {},
    }


def run(args) -> int:
    from simplicio.changeset_v2 import BINARY_MAGIC, execute_changeset_bytes, execute_changeset_json

    requested_mode = getattr(args, "mode", None) or "standalone"
    if requested_mode == "integrated":
        receipt = {
            "schema": "simplicio.fast.changeset-receipt/v2",
            "status": "refused",
            "applied": False,
            "dry_run": not args.apply,
            "errors": [
                {
                    "code": "RUNTIME_AUTHORIZATION_REQUIRED",
                    "message": (
                        "changeset direct execution supports standalone/auto; "
                        "use task for runtime-backed effects"
                    ),
                }
            ],
            "execution_mode": {"requested": requested_mode, "effective": "blocked", "runtime_required": True},
        }
        if args.json:
            print(json.dumps(receipt, sort_keys=True))
        else:
            print(f"{receipt['status']}: applied=False dry_run={receipt['dry_run']}")
        return 1

    try:
        source = read_binary_source(args.plan)
    except OSError as exc:
        print(f"simplicio-py changeset: {exc}", file=sys.stderr)
        return 2
    if source.startswith(BINARY_MAGIC):
        receipt = execute_changeset_bytes(
            source,
            root=args.root,
            apply=args.apply,
            current_generation=args.current_generation,
            fast_engine=args.fast_engine,
            refresh_producer=_mapper_refresh_producer if getattr(args, "refresh_mapper", False) else None,
        )
    else:
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            receipt = execute_changeset_bytes(
                source,
                root=args.root,
                apply=args.apply,
                current_generation=args.current_generation,
                fast_engine=args.fast_engine,
                refresh_producer=_mapper_refresh_producer if getattr(args, "refresh_mapper", False) else None,
            )
        else:
            receipt = execute_changeset_json(
                text,
                root=args.root,
                apply=args.apply,
                current_generation=args.current_generation,
            )
    receipt["execution_mode"] = {
        "requested": requested_mode,
        "effective": "standalone",
        "runtime_required": False,
        "provider_calls": 0,
        "route": "standalone",
    }
    if args.json:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(f"{receipt['status']}: applied={receipt['applied']} dry_run={receipt['dry_run']}")
    if receipt["status"] != "ok":
        return 1
    refresh = receipt.get("refresh")
    if isinstance(refresh, dict) and refresh.get("status") == "REFRESH_PENDING":
        return 1
    return 0
