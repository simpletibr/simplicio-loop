"""Read-only final MapperStore conformance gate tests (#481)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import mapper_store_conformance as conformance
from scripts.mapper_store_conformance import (
    _canonical_evidence_hash,
    _checkout_matches_default,
    _evidence_file_args,
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


def _external_receipt(key: str, *, status: str = "pass", ok: bool = True) -> dict:
    check = "scenario" if key.startswith("scenario:") else key
    receipt = {
        "schema": "simplicio.mapper-store-conformance-evidence/v1",
        "check": check,
        "status": status,
        "ok": ok,
        "sandbox": {"disposable": True, "working_tree_clean": True},
        "repositories": {
            "mapper": {"revision": "a" * 40},
            "loop": {"revision": "b" * 40},
            "dev-cli": {"revision": "c" * 40},
            "runtime": {"revision": "d" * 40},
        },
        "writer_authority": "mapper-store",
        "legacy_ddl_matches": 0,
    }
    if check == "scenario":
        receipt["scenario_id"] = key.removeprefix("scenario:")
    elif check == "runtime_single_authority":
        receipt["runtime_store_subprocesses"] = 0
    receipt["evidence_hash"] = _canonical_evidence_hash(receipt)
    return receipt


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
    schema = json.loads((ROOT / "simplicio_mapper/contracts/mapper-store/v1/schemas/conformance.schema.json").read_text())
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
    assert all("read-only here" in item["reason"] for item in report["scenarios"])
    assert report["checks"]


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


def test_external_receipts_resolve_runtime_and_scenario_gates(tmp_path: Path) -> None:
    repos = [(name, _repo(tmp_path, name)) for name in ("mapper", "loop", "dev-cli", "runtime")]
    runtime = _external_receipt("runtime_single_authority")
    scenario = _external_receipt("scenario:Windows")
    report = build_conformance(
        repos,
        [],
        deterministic=True,
        external_evidence={
            "runtime_single_authority": runtime,
            "scenario:Windows": scenario,
        },
    )
    checks = {item["id"]: item for item in report["checks"]}
    scenarios = {item["id"]: item for item in report["scenarios"]}
    schema = json.loads(
        (ROOT / "simplicio_mapper/contracts/mapper-store/v1/schemas/conformance-evidence.schema.json").read_text()
    )
    assert validate_instance(runtime, schema) == []
    assert validate_instance(scenario, schema) == []
    assert checks["runtime_single_authority"]["status"] == "pass"
    assert scenarios["scenario:Windows"]["status"] == "pass"
    assert "scenario:Windows" not in {item["id"] for item in report["residual_unverified"]}


def test_external_receipt_hash_and_revision_are_fail_closed(tmp_path: Path) -> None:
    repos = [(name, _repo(tmp_path, name)) for name in ("mapper", "loop", "dev-cli", "runtime")]
    evidence = _external_receipt("runtime_single_authority")
    evidence["writer_authority"] = "runtime"
    report = build_conformance(
        repos,
        [],
        deterministic=True,
        external_evidence={"runtime_single_authority": evidence},
    )
    check = next(item for item in report["checks"] if item["id"] == "runtime_single_authority")
    assert check["status"] == "unverified"
    assert "hash" in check["reason"]


REVISION = "a" * 40


def _legacy_runtime_receipt(**overrides: object) -> dict:
    value: dict[str, object] = {
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


def test_legacy_runtime_receipt_validator_remains_compatible() -> None:
    assert _valid_runtime_single_authority_evidence(_legacy_runtime_receipt(), REVISION)
    assert not _valid_runtime_single_authority_evidence(
        _legacy_runtime_receipt(runtime_revision="c" * 40), REVISION
    )
    assert not _valid_runtime_single_authority_evidence(
        _legacy_runtime_receipt(mapper_store_capabilities={"status": "ready"}), REVISION
    )
    assert not _valid_runtime_single_authority_evidence(
        _legacy_runtime_receipt(installed_binary="/tmp/runtime-source"), REVISION
    )


def test_evidence_file_accepts_loop_install_smoke_receipt(tmp_path: Path) -> None:
    path = tmp_path / "loop-install.json"
    path.write_text(
        json.dumps(
            {
                "schema": "simplicio.install-smoke/v1",
                "ok": True,
                "module_from_repo_checkout": False,
                "observed_version": "3.38.28",
                "artifact": {"sha256": "a" * 64},
                "module_file": "/tmp/venv/lib/python/site-packages/simplicio_loop/__init__.py",
                "probe": {"returncode": 0},
            }
        ),
        encoding="utf-8",
    )
    assert _evidence_file_args([str(path)], tmp_path)["loop_standalone"]["ok"] is True


def test_gate_fails_closed_for_unverified_status(tmp_path: Path, monkeypatch, capsys) -> None:
    repos = []
    for name in ("mapper", "loop", "dev-cli", "runtime"):
        path = tmp_path / name
        path.mkdir()
        repos.append(f"{name}={path}")

    monkeypatch.setattr(
        conformance,
        "build_conformance",
        lambda *args, **kwargs: {"status": "unverified", "residual_unverified": [{"id": "external"}]},
    )

    arguments = ["--deterministic"]
    for value in repos:
        arguments.extend(["--repo", value])
    assert conformance.main(arguments) == 1
    assert '"status": "unverified"' in capsys.readouterr().out
