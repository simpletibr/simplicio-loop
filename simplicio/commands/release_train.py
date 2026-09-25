"""CLI adapter for the deterministic release-train contract."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..component_manifest import (
    declared_dependency_range,
    tested_dependency_version,
)
from ..release_train import (
    ReleaseTrainError,
    evaluate_release_event,
    release_train_doctor,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseTrainError(f"cannot read JSON {path}: {error}") from error


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _load_state(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"processed_event_ids": [], "last_processed_version": None}
    state = _read_json(path)
    if not isinstance(state, dict):
        raise ReleaseTrainError("release-train state must be an object")
    ids = state.get("processed_event_ids", [])
    last = state.get("last_processed_version")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ReleaseTrainError("state.processed_event_ids must be a list of strings")
    if last is not None and not isinstance(last, str):
        raise ReleaseTrainError("state.last_processed_version must be a string or null")
    return {"processed_event_ids": sorted(set(ids)), "last_processed_version": last}


def run(a: argparse.Namespace) -> int:
    if a.release_train_command == "doctor":
        print(json.dumps(release_train_doctor(a.root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        root = a.root
        declared = a.declared_range or declared_dependency_range("simplicio-mapper", root)
        tested = a.tested_against
        if tested is None:
            tested, _ = tested_dependency_version("simplicio-mapper", root)
        state_path = Path(a.state) if a.state else None
        state = _load_state(state_path)
        evidence = _read_json(Path(a.conformance)) if a.conformance else None
        decision = evaluate_release_event(
            _read_json(Path(a.event)),
            declared_range=declared,
            tested_against=tested,
            conformance=evidence,
            active_task=a.active_task,
            processed_event_ids=state["processed_event_ids"],
            last_processed_version=state["last_processed_version"],
        )
        if a.record and decision.status == "accepted" and state_path is not None:
            _write_json_atomic(state_path, decision.state)
        print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if decision.status in {"accepted", "duplicate"} else 2
    except (OSError, ReleaseTrainError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": "simplicio.dev-cli.release-train/v1",
                    "status": "blocked",
                    "reason_code": "invalid_input",
                    "reason": str(error),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
