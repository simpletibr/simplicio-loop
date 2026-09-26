from __future__ import annotations

import hashlib
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.task_batch import build_task_batch


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _json_cli(args: list[str]) -> tuple[int, dict]:
    output = StringIO()
    with redirect_stdout(output):
        code = main(args)
    return code, json.loads(output.getvalue())


def test_task_batch_preserves_ids_dependencies_and_metadata(tmp_path: Path) -> None:
    project_map = {
        "files": [
            {"path": "site/checkers.html", "roles": ["frontend"]},
            {"path": "tests/checkers.test.js", "roles": ["test"]},
        ]
    }
    raw_tasks = {
        "tasks": [
            {
                "id": "TASK-CHECKERS-001",
                "task": "Create the checkers game in site/checkers.html",
                "metadata": {
                    "target": "site/checkers.html",
                    "type": "creation",
                    "source": "fixture",
                },
            },
            {
                "id": "TASK-CHECKERS-002",
                "depends_on": ["TASK-CHECKERS-001"],
                "task": "Edit site/checkers.html to add score and reset",
                "metadata": {
                    "target": "site/checkers.html",
                    "type": "edition",
                    "source": "fixture",
                },
            },
        ]
    }

    batch = build_task_batch(str(tmp_path), raw_tasks, project_map)
    by_id = {task["id"]: task for task in batch["tasks"]}

    assert batch["order"] == ["TASK-CHECKERS-001", "TASK-CHECKERS-002"]
    assert by_id["TASK-CHECKERS-002"]["depends_on"] == ["TASK-CHECKERS-001"]
    assert by_id["TASK-CHECKERS-001"]["metadata"] == raw_tasks["tasks"][0]["metadata"]
    assert by_id["TASK-CHECKERS-002"]["metadata"] == raw_tasks["tasks"][1]["metadata"]


def test_handoff_persists_mapper_receipts_and_reports_context_cache_hit_separately(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", json.dumps({"name": "checkers-handoff-regression"}))
    _write(tmp_path, "src/checkers.js", "export function start() { return true; }\n")
    task_file = _write(
        tmp_path,
        "requirements/tasks.json",
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "TASK-CHECKERS-001",
                        "task": "Create the checkers game in src/checkers.js",
                        "metadata": {"type": "creation", "fixture": "checkers"},
                    },
                    {
                        "id": "TASK-CHECKERS-002",
                        "depends_on": ["TASK-CHECKERS-001"],
                        "task": "Edit src/checkers.js to add reset behavior",
                        "metadata": {"type": "edition", "fixture": "checkers"},
                    },
                ]
            }
        ),
    )

    assert main(["map", "--root", str(tmp_path), "--silent"]) == 0
    assert main(["inspect", str(tmp_path), "--await", "--json"]) == 0
    inspection_path = tmp_path / ".simplicio-loop" / "map-inspection.json"
    assert inspection_path.is_file()
    inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
    assert inspection["schema"] == "simplicio.map-inspection/v1"

    snapshot_code, snapshot_stdout = _json_cli(["snapshot", "build", "--root", str(tmp_path), "--json"])
    assert snapshot_code == 0
    assert snapshot_stdout["schema"] == "simplicio.context-snapshot/v1"
    snapshot_path = tmp_path / ".simplicio-loop" / "context-snapshot.json"
    assert snapshot_path.is_file()
    persisted_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert persisted_snapshot["snapshot_id"] == snapshot_stdout["snapshot_id"]

    handoff_args = [
        "handoff",
        str(tmp_path),
        "--task-batch-file",
        str(task_file),
        "--execution-context",
        "--await",
        "--json",
    ]
    first_code, first = _json_cli(handoff_args)
    second_code, second = _json_cli(handoff_args)
    assert first_code == second_code == 0
    # The snapshot command and task-aware handoff are separate observations;
    # each may carry a different task-query/revision projection. Persistence
    # is proven by the on-disk artifact above, while the handoff must expose
    # its own valid snapshot identity.
    assert first["context_snapshot"]["schema"] == "simplicio.context-snapshot/v1"
    assert len(first["context_snapshot"]["snapshot_id"]) == 64
    assert (
        first["context_pack"]["source_snapshot"]["source_digest"]
        == hashlib.sha256(
            json.dumps(
                first["context_snapshot"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert (
        second["context_pack"]["source_snapshot"]["source_digest"]
        == hashlib.sha256(
            json.dumps(
                second["context_snapshot"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert [task["id"] for task in first["task_batch"]["tasks"]] == [
        "TASK-CHECKERS-001",
        "TASK-CHECKERS-002",
    ]
    assert first["task_batch"]["tasks"][1]["depends_on"] == ["TASK-CHECKERS-001"]
    assert first["task_batch"]["tasks"][0]["metadata"] == {
        "type": "creation",
        "fixture": "checkers",
    }
    assert first["cache"]["pack_cached"] is False
    assert first["cache"]["pack_cache_receipt"]["outcome"] == "miss"
    assert first["cache"]["pack_cache_receipt"]["produced"] is True
    assert second["cache"]["pack_cached"] is True
    assert second["cache"]["pack_cache_receipt"]["outcome"] == "hit"
    assert second["cache"]["pack_cache_receipt"]["consumed"] is True
    assert second["cache"]["pack_diagnostics"]["present"] is True
    assert second["cache"]["pack_diagnostics"]["layer"] == "rendered-pack"
