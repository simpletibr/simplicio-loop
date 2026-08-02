"""Read-only final MapperStore conformance gate tests (#481)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.mapper_store_conformance import build_conformance
from simplicio_mapper.contract import validate_instance

ROOT = Path(__file__).parents[2]


def _repo(root: Path, name: str, content: str = "") -> Path:
    path = root / name
    path.mkdir()
    (path / "src.py").write_text(content, encoding="utf-8")
    return path


def test_conformance_is_deterministic_and_reports_legacy_writers(tmp_path: Path) -> None:
    repos = [
        ("mapper", _repo(tmp_path, "mapper", "from simplicio_mapper.store import StoreConnection\n")),
        (
            "loop",
            _repo(
                tmp_path, "loop", "import sqlite3\nconnection.execute('CREATE TABLE legacy (id INTEGER)')\n"
            ),
        ),
        ("dev-cli", _repo(tmp_path, "dev-cli", "import sqlite3\n")),
        ("runtime", _repo(tmp_path, "runtime", "use sqlite3\n")),
    ]
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY)")
    first = build_conformance(repos, [("loop", database, "legacy.sqlite")], deterministic=True)
    second = build_conformance(repos, [("loop", database, "legacy.sqlite")], deterministic=True)
    schema = json.loads((ROOT / "contracts/mapper-store/v1/schemas/conformance.schema.json").read_text())
    assert validate_instance(first, schema) == []
    assert first["evidence_hash"] == second["evidence_hash"]
    assert first["status"] == "fail"
    assert (
        next(item for item in first["checks"] if item["id"] == "external_legacy_writers_removed")["status"]
        == "fail"
    )
    assert all(item["status"] == "unverified" for item in first["scenarios"])


def test_conformance_never_claims_external_smoke_from_mapper_checkout(tmp_path: Path) -> None:
    repos = [(name, _repo(tmp_path, name)) for name in ("mapper", "loop", "dev-cli", "runtime")]
    report = build_conformance(repos, [], deterministic=True, run_external_smoke=True)
    assert report["read_only"] is True
    assert all("not executable" in item["reason"] for item in report["scenarios"])
    assert report["checks"]
