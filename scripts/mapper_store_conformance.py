#!/usr/bin/env python3
"""Read-only final MapperStore conformance and rollout evidence gate.

This command freezes repository identities and evaluates the final gate without
editing a checkout, importing consumer packages, or changing a database.  It
is intentionally honest about checks that require a clean installed package,
another operating system, or external rollout work.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.mapper-store-conformance/v1"
EXTERNAL_EVIDENCE_SCHEMA = "simplicio.mapper-store-conformance-evidence/v1"
INVENTORY_PATH = Path(__file__).with_name("mapper_store_inventory.py")
REQUIRED_REPOS = ("mapper", "loop", "dev-cli", "runtime")
SCENARIOS = (
    "fresh standalone",
    "upgrade standalone",
    "fresh runtime-backed",
    "upgrade runtime-backed",
    "sqlite-vec present",
    "sqlite-vec absent",
    "crash during migration",
    "legacy database corrupted",
    "Windows",
    "Linux",
    "macOS",
)


def _inventory_module():
    spec = importlib.util.spec_from_file_location("mapper_store_inventory", INVENTORY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("mapper_store_inventory module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result(check_id: str, status: str, reason: str, evidence: Any = None) -> dict[str, Any]:
    if status not in {"pass", "fail", "unverified"}:
        raise ValueError(f"invalid conformance status: {status}")
    return {"id": check_id, "status": status, "reason": reason, "evidence": evidence}


def _checkout_matches_default(reference: dict[str, Any]) -> bool:
    """Accept a clean detached worktree pinned exactly to the default SHA."""
    if not reference.get("working_tree_clean", False):
        return False
    if reference.get("checked_out_branch") == reference.get("branch"):
        return True
    return (
        reference.get("checked_out_branch") is None
        and reference.get("checked_out_sha")
        and reference.get("checked_out_sha") == reference.get("sha")
    )


def _repo_roots(values: list[str], base: Path) -> list[tuple[str, Path]]:
    roots: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"repo requires name=path: {value}")
        repo_id, raw_path = value.split("=", 1)
        if not repo_id or not raw_path:
            raise SystemExit(f"repo requires name=path: {value}")
        path = (base / raw_path).resolve() if not os.path.isabs(raw_path) else Path(raw_path).resolve()
        if not path.is_dir():
            raise SystemExit(f"repo does not exist: {path}")
        roots[repo_id] = path
    missing = [repo_id for repo_id in REQUIRED_REPOS if repo_id not in roots]
    if missing:
        raise SystemExit(f"missing required repos: {', '.join(missing)}")
    return sorted(roots.items())


def _evidence_args(values: list[str], base: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"evidence requires check=path: {value}")
        check_id, raw_path = value.split("=", 1)
        path = (base / raw_path).resolve() if not os.path.isabs(raw_path) else Path(raw_path).resolve()
        if not check_id or not path.is_file() or path.is_symlink():
            raise SystemExit(f"evidence must be an existing non-symlink file: {path}")
        try:
            evidence[check_id] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"evidence is not valid JSON: {path}") from error
    return evidence


def _valid_loop_standalone_evidence(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != "simplicio.install-smoke/v1":
        return False
    if value.get("ok") is not True or value.get("module_from_repo_checkout") is not False:
        return False
    if not isinstance(value.get("observed_version"), str) or not value["observed_version"].strip():
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("artifact", {}).get("sha256", ""))):
        return False
    probe = value.get("probe", {})
    return (
        isinstance(probe, dict)
        and probe.get("returncode") == 0
        and isinstance(value.get("module_file"), str)
        and "site-packages" in value["module_file"]
    )


def _valid_runtime_single_authority_evidence(value: Any, expected_revision: str) -> bool:
    """Validate the pre-v1 Runtime install receipt for compatibility tooling.

    The final gate below requires the stronger hash-bound cross-repo receipt.
    Keeping this narrow validator public preserves the Runtime package's
    existing installed-smoke harness while its producer migrates to v1.
    """
    if not isinstance(value, dict):
        return False
    if value.get("schema") != "simplicio.runtime-mapper-store-installed-smoke/v1":
        return False
    if value.get("ok") is not True or value.get("runtime_revision") != expected_revision:
        return False
    binary = value.get("installed_binary")
    source = value.get("source_checkout")
    if not isinstance(binary, str) or not binary.strip() or not isinstance(source, str) or not source.strip():
        return False
    if Path(binary).resolve() == Path(source).resolve():
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("binary_sha256", ""))):
        return False
    version = value.get("version")
    if not isinstance(version, str) or not version.strip():
        return False
    capabilities = value.get("mapper_store_capabilities")
    if not isinstance(capabilities, dict):
        return False
    return (
        capabilities.get("status") == "ready"
        and capabilities.get("store_schema") == "simplicio.mapper-store.operations/v1"
        and capabilities.get("effect_ledger") is True
        and capabilities.get("fencing") is True
        and capabilities.get("operations_write") is True
    )


def _canonical_evidence_hash(value: Mapping[str, Any]) -> str:
    return _sha({key: item for key, item in value.items() if key != "evidence_hash"})


def _external_evidence_key(value: Mapping[str, Any]) -> str | None:
    check = value.get("check")
    if check == "scenario":
        scenario_id = value.get("scenario_id")
        return f"scenario:{scenario_id}" if isinstance(scenario_id, str) else None
    return check if isinstance(check, str) else None


def _validate_external_evidence(
    key: str,
    value: Any,
    default_refs: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    """Validate a cross-repo receipt without executing its producer.

    External smoke is deliberately a separate process because this gate must
    remain read-only.  A receipt is useful only when it is self-hashable,
    produced in a disposable clean sandbox, pinned to the exact repository
    revisions being gated, and proves MapperStore writer ownership.
    """
    if not isinstance(value, dict):
        return "unverified", "external evidence must be a JSON object"
    if value.get("schema") != EXTERNAL_EVIDENCE_SCHEMA:
        return "unverified", "external evidence schema is missing or unsupported"
    if _external_evidence_key(value) != key:
        return "unverified", "external evidence check identifier does not match its input key"
    if value.get("evidence_hash") != _canonical_evidence_hash(value):
        return "unverified", "external evidence hash is missing or does not match its canonical payload"
    sandbox = value.get("sandbox")
    if not isinstance(sandbox, dict) or sandbox.get("disposable") is not True:
        return "unverified", "external evidence must identify a disposable sandbox"
    if sandbox.get("working_tree_clean") is not True:
        return "unverified", "external evidence requires clean producer checkouts"
    repositories = value.get("repositories")
    if not isinstance(repositories, dict):
        return "unverified", "external evidence must pin repository revisions"
    for repo_id in REQUIRED_REPOS:
        observed = repositories.get(repo_id)
        expected = default_refs.get(repo_id, {}).get("sha")
        if not isinstance(observed, dict) or not isinstance(observed.get("revision"), str):
            return "unverified", f"external evidence is missing revision for {repo_id}"
        if expected and observed["revision"] != expected:
            return "unverified", f"external evidence revision mismatch for {repo_id}"
    if value.get("writer_authority") != "mapper-store":
        return "unverified", "external evidence does not prove MapperStore writer authority"
    if value.get("legacy_ddl_matches") != 0:
        return "unverified", "external evidence still reports legacy DDL writers"
    if key == "runtime_single_authority" and value.get("runtime_store_subprocesses") != 0:
        return "unverified", "Runtime evidence must prove zero Python store subprocesses"
    status = value.get("status")
    if status == "pass" and value.get("ok") is True:
        return "pass", "validated external cross-repo evidence"
    if status == "fail" or value.get("ok") is False:
        return "fail", "external cross-repo evidence reports a failed scenario"
    return "unverified", "external cross-repo evidence is not a passing receipt"


def _database_args(values: list[str], base: Path) -> list[tuple[str, Path, str]]:
    result: list[tuple[str, Path, str]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"database requires repo-id=path: {value}")
        repo_id, raw_path = value.split("=", 1)
        path = (base / raw_path).resolve() if not os.path.isabs(raw_path) else Path(raw_path).resolve()
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"database must be an existing non-symlink file: {path}")
        result.append((repo_id, path, raw_path))
    return result


def _evidence_file_args(values: list[str], base: Path) -> dict[str, Any]:
    """Load one or more evidence bundles, including Runtime-compatible files.

    A bundle may be either ``{"check": ..., ...}`` for one receipt or a map
    from gate identifiers to receipt objects.  The file itself is never
    modified and symlinks are rejected before path resolution.
    """
    evidence: dict[str, Any] = {}
    for raw_value in values:
        raw_path = Path(raw_value)
        if raw_path.is_symlink():
            raise SystemExit(f"evidence file must not be a symlink: {raw_path}")
        path = (base / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        if not path.is_file():
            raise SystemExit(f"evidence file does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SystemExit(f"evidence file is not valid JSON: {path}") from error
        if isinstance(payload, dict) and payload.get("schema") == "simplicio.install-smoke/v1":
            evidence["loop_standalone"] = payload
            continue
        if isinstance(payload, dict) and "check" in payload:
            key = _external_evidence_key(payload)
            if key is None:
                raise SystemExit(f"evidence file has an invalid check identifier: {path}")
            evidence[key] = payload
            continue
        if not isinstance(payload, dict):
            raise SystemExit(f"evidence file must contain an object: {path}")
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise SystemExit(f"evidence bundle entries must be object receipts: {path}")
            evidence[key] = value
    return evidence


def build_conformance(
    repos: list[tuple[str, Path]],
    databases: list[tuple[str, Path, str]],
    *,
    deterministic: bool = False,
    run_external_smoke: bool = False,
    external_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inventory_module = _inventory_module()
    inventory = inventory_module.build_inventory(repos, databases, deterministic=deterministic)
    repo_by_id = {item["id"]: item for item in inventory["repos"]}
    checks: list[dict[str, Any]] = []

    default_refs = {
        repo_id: {
            "branch": repo_by_id[repo_id].get("default_branch"),
            "sha": repo_by_id[repo_id].get("default_revision"),
            "checked_out_branch": repo_by_id[repo_id].get("branch"),
            "checked_out_sha": repo_by_id[repo_id].get("revision"),
            "working_tree_clean": repo_by_id[repo_id].get("working_tree_clean", False),
        }
        for repo_id in REQUIRED_REPOS
    }
    missing_refs = [repo_id for repo_id, ref in default_refs.items() if not ref["sha"]]
    checks.append(
        _result(
            "default_refs_frozen",
            "fail" if missing_refs else "pass",
            "default remote refs are required for a reproducible gate"
            if missing_refs
            else "all default remote refs have exact SHAs",
            default_refs,
        )
    )

    policy = inventory["policy"]
    checks.append(
        _result(
            "mapper_ddl_allowlist",
            "pass" if policy["status"] == "pass" else "fail",
            "Mapper production DDL is outside the allowlist"
            if policy["status"] != "pass"
            else "Mapper DDL is within the MapperStore allowlist",
            {"violations": policy["violations"], "legacy_ddl_matches": policy.get("legacy_ddl_matches", 0)},
        )
    )
    external_ddl = int(policy.get("legacy_ddl_matches", 0))
    checks.append(
        _result(
            "external_legacy_writers_removed",
            "fail" if external_ddl else "pass",
            "consumer repositories still contain legacy SQLite/DDL evidence"
            if external_ddl
            else "no external legacy DDL evidence",
            {"legacy_ddl_matches": external_ddl},
        )
    )

    dirty_or_nondefault = {
        repo_id: ref for repo_id, ref in default_refs.items()
        if not _checkout_matches_default(ref)
    }
    checks.append(
        _result(
            "clean_default_checkout",
            "unverified" if dirty_or_nondefault else "pass",
            "clean default checkout is required for release evidence"
            if dirty_or_nondefault
            else "all repositories are on their default branches",
            dirty_or_nondefault,
        )
    )

    fast_matches = [
        item for item in inventory["matches"]
        if item["repo"] == "fast"
        and {"library", "dsn_or_path", "ddl", "command"}.intersection(item["kinds"])
    ]
    fast_supplied = any(repo_id == "fast" for repo_id, _ in repos)
    checks.append(
        _result(
            "fast_isolation",
            "fail" if fast_matches else "pass" if fast_supplied else "unverified",
            "Fast contains SQLite/FTS/vector store evidence"
            if fast_matches
            else "Fast was supplied and contains no SQLite/FTS/vector store evidence"
            if fast_supplied
            else "Fast was not supplied to this gate; isolation remains unverified",
            {"matches": fast_matches[:20]},
        )
    )
    supplied_evidence = dict(external_evidence or {})
    loop_evidence = supplied_evidence.get("loop_standalone")
    loop_evidence_valid = _valid_loop_standalone_evidence(loop_evidence)
    checks.append(
        _result(
            "loop_standalone",
            "pass" if loop_evidence_valid else "unverified",
            "clean-room installed Loop wheel smoke passed"
            if loop_evidence_valid
            else "standalone installed-package smoke must run outside this source checkout",
            loop_evidence if loop_evidence_valid else {"runtime_required": False},
        )
    )
    runtime_status, runtime_reason = _validate_external_evidence(
        "runtime_single_authority",
        supplied_evidence.get("runtime_single_authority"),
        default_refs,
    )
    checks.append(
        _result(
            "runtime_single_authority",
            runtime_status,
            runtime_reason
            if runtime_status != "unverified" or supplied_evidence.get("runtime_single_authority") is not None
            else "Runtime-backed cutover and Rust adapter smoke require a validated external receipt",
            supplied_evidence.get("runtime_single_authority")
            if runtime_status == "pass"
            else {"runtime_revision": default_refs["runtime"]["sha"]},
        )
    )

    readable = [item for item in inventory["databases"] if item["status"] == "readable"]
    unreadable = [item for item in inventory["databases"] if item["status"] != "readable"]
    checks.append(
        _result(
            "database_inventory_readable",
            "fail" if unreadable else "pass",
            "one or more supplied databases could not be inspected read-only"
            if unreadable
            else "all supplied databases were inspected read-only",
            {"readable": len(readable), "unreadable": unreadable},
        )
    )
    matrix_status, matrix_reason = _validate_external_evidence(
        "installed_package_matrix",
        supplied_evidence.get("installed_package_matrix"),
        default_refs,
    )
    checks.append(
        _result(
            "installed_package_matrix",
            matrix_status,
            matrix_reason
            if matrix_status != "unverified" or supplied_evidence.get("installed_package_matrix") is not None
            else "fresh/upgrade and Windows/Linux/macOS installed-package matrix requires a validated external receipt",
            supplied_evidence.get("installed_package_matrix")
            if matrix_status == "pass"
            else {"host": platform.platform(), "python": sys.version.split()[0]},
        )
    )

    scenario_results = []
    for scenario in SCENARIOS:
        scenario_id = f"scenario:{scenario}"
        evidence = supplied_evidence.get(scenario_id)
        status, reason = _validate_external_evidence(scenario_id, evidence, default_refs)
        scenario_results.append(
            _result(
                scenario_id,
                status,
                reason
                if status != "unverified" or evidence is not None
                else "scenario requires a validated external consumer-package receipt",
                evidence if status == "pass" else None,
            )
        )
    if run_external_smoke:
        # The flag is intentionally an evidence declaration: this Mapper-only
        # command never imports or mutates consumer packages.
        for result in scenario_results:
            if result["status"] == "unverified":
                result["reason"] = (
                    "external smoke is read-only here and not executable by the Mapper gate; "
                    "supply a hashed receipt from the clean sandbox"
                )

    residual = [
        {"id": result["id"], "reason": result["reason"]}
        for result in checks + scenario_results
        if result["status"] == "unverified"
    ]
    all_results = checks + scenario_results
    payload = {
        "schema": SCHEMA,
        "status": "fail"
        if any(item["status"] == "fail" for item in all_results)
        else "unverified"
        if residual
        else "pass",
        "read_only": True,
        "generated_at": None
        if deterministic
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "repositories": default_refs,
        "checks": checks,
        "scenarios": scenario_results,
        "inventory": inventory,
        "residual_unverified": residual,
        "release_order": [
            "publish mapper contracts",
            "validate installed packages and Rust bindings",
            "shadow rollout consumers",
            "collect zero unexplained mismatch",
            "explicit sandbox cutover",
            "fault injection and rollback",
            "promote MapperStore defaults",
            "keep legacy read-only during window",
            "remove legacy writers after verified backup",
        ],
    }
    payload["evidence_hash"] = _sha({key: value for key, value in payload.items() if key != "evidence_hash"})
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", action="append", default=[],
        help="name=path; required: mapper, loop, dev-cli, runtime; optional: fast"
    )
    parser.add_argument(
        "--database", action="append", default=[], help="repo-id=existing database path; repeatable"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--run-external-smoke", action="store_true")
    parser.add_argument(
        "--evidence", action="append", default=[],
        help="check=JSON receipt; repeatable for loop_standalone or cross-repo receipts",
    )
    parser.add_argument(
        "--evidence-file", action="append", default=[],
        help="JSON receipt or bundle produced by an external clean-room harness; repeatable",
    )
    args = parser.parse_args(argv)
    base = Path.cwd()
    repos = _repo_roots(
        args.repo
        or [
            "mapper=.",
            "loop=../simplicio-loop",
            "dev-cli=../simplicio-dev-cli",
            "runtime=../simplicio-runtime",
        ],
        base,
    )
    databases = _database_args(args.database, base)
    external_evidence = _evidence_args(args.evidence, base)
    external_evidence.update(_evidence_file_args(args.evidence_file, base))
    payload = build_conformance(
        repos,
        databases,
        deterministic=args.deterministic,
        run_external_smoke=args.run_external_smoke,
        external_evidence=external_evidence,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
