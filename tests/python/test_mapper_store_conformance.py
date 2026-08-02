"""Read-only final MapperStore conformance gate tests (#481)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.mapper_store_conformance import (
    _checkout_matches_default,
    _valid_runtime_single_authority_evidence,
    build_conformance,
)
from simplicio_mapper.contract import validate_instance


ROOT = Path(__file__).parents[2]


def test_clean_detached_checkout_at_default_sha_is_accepted() -> None:
    assert _checkout_matches_default({
        "branch": "main",
        "checked_out_branch": None,
        "sha": "abc123",
        "checked_out_sha": "abc123",
        "working_tree_clean": True,
    })
    assert not _checkout_matches_default({
        "branch": "main",
        "checked_out_branch": None,
        "sha": "abc123",
        "checked_out_sha": "def456",
        "working_tree_clean": True,
    })
    assert not _checkout_matches_default({
        "branch": "main",
        "checked_out_branch": None,
        "sha": "abc123",
        "checked_out_sha": "abc123",
        "working_tree_clean": False,
    })


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


def test_fast_isolation_passes_only_when_fast_was_scanned(tmp_path: Path) -> None:
    repos = [(name, _repo(tmp_path, name)) for name in ("mapper", "loop", "dev-cli", "runtime")]
    repos.append(("fast", _repo(tmp_path, "fast", "migration documentation\n")))
    report = build_conformance(repos, [], deterministic=True)
    check = next(item for item in report["checks"] if item["id"] == "fast_isolation")
    assert check["status"] == "pass"

    repos[-1] = ("fast", _repo(tmp_path, "fast-sqlite", "import sqlite3\n"))
    report = build_conformance(repos, [], deterministic=True)
    check = next(item for item in report["checks"] if item["id"] == "fast_isolation")
    assert check["status"] == "fail"


def test_installed_loop_evidence_is_validated_before_passing(tmp_path: Path) -> None:
    repos = [(name, _repo(tmp_path, name)) for name in ("mapper", "loop", "dev-cli", "runtime")]
    evidence = {
        "schema": "simplicio.install-smoke/v1",
        "ok": True,
        "module_from_repo_checkout": False,
        "observed_version": "3.38.28",
        "artifact": {"sha256": "a" * 64},
        "module_file": "/tmp/venv/lib/python/site-packages/simplicio_loop/__init__.py",
        "probe": {"returncode": 0},
    }
    report = build_conformance(repos, [], deterministic=True, external_evidence={"loop_standalone": evidence})
    check = next(item for item in report["checks"] if item["id"] == "loop_standalone")
    assert check["status"] == "pass"
    evidence["module_from_repo_checkout"] = True
    report = build_conformance(repos, [], deterministic=True, external_evidence={"loop_standalone": evidence})
    check = next(item for item in report["checks"] if item["id"] == "loop_standalone")
    assert check["status"] == "unverified"


REVISION = "a" * 40


def runtime_receipt(**overrides):
    value = {
        "schema": "simplicio.runtime-mapper-store-installed-smoke/v1",
        "ok": True,
        "runtime_revision": REVISION,
        "installed_binary": "/tmp/runtime-installed/bin/simplicio",
        "source_checkout": "/tmp/runtime-source",
        "binary_sha256": "b" * 64,
        "version": "3.5.7",
        "mapper_store_capabilities": {
            "status": "ready",
            "store_schema": "simplicio.mapper-store.operations/v1",
            "effect_ledger": True,
            "fencing": True,
            "operations_write": True,
        },
    }
    value.update(overrides)
    return value


def test_runtime_installed_receipt_requires_matching_revision_and_capabilities() -> None:
    assert _valid_runtime_single_authority_evidence(runtime_receipt(), REVISION)
    assert not _valid_runtime_single_authority_evidence(
        runtime_receipt(runtime_revision="c" * 40), REVISION
    )
    assert not _valid_runtime_single_authority_evidence(
        runtime_receipt(mapper_store_capabilities={"status": "ready"}), REVISION
    )


def test_runtime_installed_receipt_rejects_source_checkout_as_installed_binary() -> None:
    assert not _valid_runtime_single_authority_evidence(
        runtime_receipt(installed_binary="/tmp/runtime-source"), REVISION
    )
