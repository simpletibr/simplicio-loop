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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.mapper-store-conformance/v1"
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
    loop_evidence = (external_evidence or {}).get("loop_standalone")
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
    checks.append(
        _result(
            "runtime_single_authority",
            "unverified",
            "Runtime-backed cutover and Rust adapter smoke require the installed Runtime package",
            {"runtime_revision": default_refs["runtime"]["sha"]},
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
    checks.append(
        _result(
            "installed_package_matrix",
            "unverified",
            "fresh/upgrade and Windows/Linux/macOS installed-package matrix was not executed here",
            {"host": platform.platform(), "python": sys.version.split()[0]},
        )
    )

    scenario_results = [
        _result(
            f"scenario:{scenario}",
            "unverified",
            "scenario requires a clean sandbox and external consumer packages",
        )
        for scenario in SCENARIOS
    ]
    if run_external_smoke:
        # The flag is intentionally an evidence declaration: this Mapper-only
        # command never imports or mutates consumer packages.
        for result in scenario_results:
            result["reason"] = "external smoke requested but not executable by the read-only Mapper gate"

    residual = [
        {"id": result["id"], "reason": result["reason"]}
        for result in checks + scenario_results
        if result["status"] == "unverified"
    ]
    payload = {
        "schema": SCHEMA,
        "status": "fail"
        if any(item["status"] == "fail" for item in checks)
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
        help="check=JSON receipt; currently supports loop_standalone",
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
