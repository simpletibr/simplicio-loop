#!/usr/bin/env python3
"""Read-only MapperStore inventory and SQLite DDL policy gate.

The command deliberately treats source files and existing databases as evidence only:
it never opens a database in write mode, executes application code, or changes a
schema.  It is useful both for the initial cross-repository inventory and as a local
gate before a later MapperStore migration adds a new SQLite authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SCHEMA = "simplicio.mapper-store-inventory/v1"
MAX_FILE_BYTES = 1_000_000
SKIP_DIRS = {
    ".git", ".simplicio", ".venv", "__pycache__", "node_modules", "target",
    "dist", "build", "coverage", "playwright-report", "test-results",
}
TEXT_SUFFIXES = {".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".js", ".jsx", ".json", ".md",
                 ".mjs", ".py", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".yml", ".yaml"}
DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm"}

PATTERNS = {
    "library": re.compile(r"\b(?:sqlite3|rusqlite|sqlite[_-]vec|sqlite_vec|vec0|fts5|diskcache)\b", re.I),
    "dsn_or_path": re.compile(
        r"(?:sqlite3?://[^\s'\"]+|sqlite3?\.connect\s*\(|Connection::open(?:_with_flags)?\s*\(|"
        r"(?:[\w./~-]+\.(?:db|sqlite3?|sqlite))|SIMPLICIO_[A-Z0-9_]*(?:DB|DATABASE|MEMORY|STORE)[A-Z0-9_]*)",
        re.I,
    ),
    "ddl": re.compile(r"\b(?:CREATE\s+(?:VIRTUAL\s+)?TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX|CREATE\s+TRIGGER|ALTER\s+TABLE|DROP\s+TABLE|PRAGMA\s+\w+|ATTACH\s+DATABASE|load_extension)\b", re.I),
    "migration": re.compile(r"\b(?:migration|migrate|schema_version|user_version|upgrade|downgrade)\b", re.I),
    "command": re.compile(r"(?:\bsqlite3\b|\.backup\b|\bVACUUM\b|\bBEGIN\s+IMMEDIATE\b|\bwal\b|\bbusy_timeout\b)", re.I),
}
SECRET_VALUE = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*([:=])\s*(['\"]?)[^'\"\s,;]+")
PLACEHOLDER_VALUE = re.compile(r"<([A-Z][A-Z0-9_]+)>")


def _run(*args: str, cwd: Path) -> str | None:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _redact(value: str) -> str:
    redacted = SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", value.strip())
    return PLACEHOLDER_VALUE.sub("<placeholder>", redacted)


def _repo_info(repo_id: str, root: Path) -> dict:
    branch = _run("git", "symbolic-ref", "--short", "HEAD", cwd=root)
    remote = _run("git", "remote", "get-url", "origin", cwd=root)
    default_ref = _run("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=root)
    default_branch = (default_ref or "origin/main").removeprefix("origin/")
    return {
        "id": repo_id,
        "path": "." if repo_id == "mapper" else repo_id,
        "branch": branch,
        "revision": _run("git", "rev-parse", "HEAD", cwd=root),
        "default_branch": default_branch,
        "default_revision": _run("git", "rev-parse", f"refs/remotes/origin/{default_branch}", cwd=root),
        "remote": remote,
        "versions": _versions(root),
    }


def _versions(root: Path) -> dict:
    versions: dict[str, str] = {}
    for name, pattern in (
        ("python", re.compile(r"^version\s*=\s*[\"']([^\"']+)", re.M)),
        ("node", re.compile(r"[\"']version[\"']\s*:\s*[\"']([^\"']+)", re.M)),
        ("rust", re.compile(r"^version\s*=\s*[\"']([^\"']+)", re.M)),
    ):
        candidates = {"python": "pyproject.toml", "node": "package.json", "rust": "rust/Cargo.toml"}
        path = root / candidates[name]
        try:
            match = pattern.search(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            match = None
        if match:
            versions[name] = match.group(1)
    return versions


def _relative_files(root: Path):
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS and not name.startswith("."))
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path.relative_to(root), path


def _is_fixture_or_test(relative: str) -> bool:
    lowered = f"/{relative.lower()}/"
    return any(token in lowered for token in ("/test", "/fixture", "/example", "/golden", "/spec/"))


def _classify(relative: str, kinds: set[str]) -> str:
    lowered = relative.lower()
    if _is_fixture_or_test(relative):
        return "fixture"
    if "cache" in lowered or "index" in lowered:
        return "derived-index"
    if "migration" in lowered or "schema" in lowered:
        return "schema-or-migration"
    if "receipt" in lowered or "ledger" in lowered or "journal" in lowered:
        return "receipt"
    if "ddl" in kinds or "dsn_or_path" in kinds:
        return "production-candidate"
    return "reference"


def _scan_sources(repo_id: str, root: Path) -> tuple[list[dict], list[dict]]:
    matches: list[dict] = []
    matrix: list[dict] = []
    for relative, path in _relative_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        file_matches = []
        kinds: set[str] = set()
        for line_number, line in enumerate(lines, 1):
            for kind, pattern in PATTERNS.items():
                if pattern.search(line):
                    kinds.add(kind)
                    file_matches.append({
                        "kind": kind,
                        "line": line_number,
                        "evidence": _redact(line)[:240],
                    })
        if not file_matches:
            continue
        relative_text = relative.as_posix()
        classification = _classify(relative_text, kinds)
        matches.append({
            "repo": repo_id,
            "file": relative_text,
            "classification": classification,
            "kinds": sorted(kinds),
            "matches": file_matches,
        })
        writers = [repo_id] if {"ddl", "dsn_or_path", "command"} & kinds else []
        matrix.append({
            "repo": repo_id,
            "file": relative_text,
            "kinds": sorted(kinds),
            "classification": classification,
            "current_owner": repo_id,
            "target_owner": "mapper-store",
            "readers": [repo_id],
            "writers": writers,
            "authorized_writer_after_cutover": "mapper-store",
            "source_of_truth": "derived-index" if classification == "derived-index" else "source-of-truth",
            "receipt_authority": "operations.sqlite",
            "durability": "reconstructible" if classification in {"derived-index", "fixture", "reference"} else "durable",
            "criticality": "test-only" if classification == "fixture" else ("critical" if writers else "informational"),
            "migration_strategy": "allowlisted-fixture" if classification == "fixture" else "discover-then-plan",
        })
    return matches, matrix


def _database_info(path: Path, repo_id: str, display_path: str | None = None) -> dict:
    record = {"repo": repo_id, "path": display_path or path.name, "read_only_inspection": True, "status": "unreadable"}
    try:
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            tables = []
            for name, kind, sql in connection.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            ):
                table = {"name": name, "kind": kind, "sql": _redact(sql or "")}
                if kind == "table":
                    table["columns"] = [dict(zip(("cid", "name", "type", "notnull", "default", "pk"), row, strict=False)) for row in connection.execute(f'PRAGMA table_info("{name.replace(chr(34), chr(34) * 2)}")')]
                    table["foreign_keys"] = [list(row) for row in connection.execute(f'PRAGMA foreign_key_list("{name.replace(chr(34), chr(34) * 2)}")')]
                tables.append(table)
            record.update({
                "status": "readable",
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
                "objects": tables,
            })
    except (OSError, sqlite3.Error) as error:
        record["error"] = type(error).__name__
    return record


def _discover_databases(repo_id: str, root: Path) -> list[dict]:
    records = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix.lower() in DATABASE_SUFFIXES:
                records.append(_database_info(path, repo_id, path.relative_to(root).as_posix()))
    return records


def _policy(matrix: list[dict]) -> dict:
    violations = []
    legacy_ddl_matches = 0
    for item in matrix:
        if "ddl" in item["kinds"] and item["repo"] != "mapper":
            legacy_ddl_matches += 1
            continue
        if item["criticality"] == "test-only":
            continue
        if "ddl" in item["kinds"] and not (
            item["file"].startswith("simplicio_mapper/store/")
            or item["file"].startswith("contracts/mapper-store/")
            or item["file"] == "scripts/mapper_store_inventory.py"
            or _is_fixture_or_test(item["file"])
        ):
            violations.append({"repo": item["repo"], "file": item["file"], "reason": "DDL outside allowlisted MapperStore paths"})
    return {
        "schema": "simplicio.mapper-store-ddl-policy/v1",
        "allowlisted_paths": ["simplicio_mapper/store/", "contracts/mapper-store/", "scripts/mapper_store_inventory.py", "tests/", "fixtures/"],
        "violations": violations,
        "legacy_ddl_matches": legacy_ddl_matches,
        "status": "pass" if not violations else "fail",
        "note": "This is a local/read-only gate; no GitHub Actions workflow is added by this issue.",
    }


def build_inventory(repos: list[tuple[str, Path]], databases: list[tuple[str, Path]], deterministic: bool = False) -> dict:
    repo_records = []
    matches = []
    matrix = []
    db_records = []
    for repo_id, root in repos:
        repo_info = _repo_info(repo_id, root)
        repo_info["files_scanned"] = 0
        repo_info["files_scanned"] = sum(1 for _ in _relative_files(root))
        repo_matches, repo_matrix = _scan_sources(repo_id, root)
        repo_records.append(repo_info)
        matches.extend(repo_matches)
        matrix.extend(repo_matrix)
        db_records.extend(_discover_databases(repo_id, root))
    for repo_id, path in databases:
        db_records.append(_database_info(path, repo_id, path.name))
    for database in db_records:
        for database_object in database.get("objects", []):
            if database_object.get("kind") != "table":
                continue
            matrix.append({
                "repo": database["repo"],
                "file": database["path"],
                "table": database_object["name"],
                "kinds": ["materialized-db"],
                "classification": "materialized-store",
                "current_owner": database["repo"],
                "target_owner": "mapper-store",
                "readers": [database["repo"]],
                "writers": [database["repo"]],
                "authorized_writer_after_cutover": "mapper-store",
                "source_of_truth": "source-of-truth",
                "receipt_authority": "operations.sqlite",
                "durability": "durable",
                "criticality": "critical",
                "migration_strategy": "discover-then-plan",
            })
    return {
        "schema": SCHEMA,
        "generated_at": None if deterministic else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repos": repo_records,
        "matches": matches,
        "databases": db_records,
        "ownership_matrix": matrix,
        "policy": _policy(matrix),
        "target_topology": {
            "schema": "MapperStore/v1",
            "root": "~/.simplicio/data/",
            "stores": [
                {"name": "semantic.sqlite", "owner": "mapper-store", "domains": ["ContextGraph", "symbols", "precedents", "documents"]},
                {"name": "memory.sqlite", "owner": "mapper-store", "domains": ["memory", "handoff", "FTS5", "embeddings", "sqlite-vec-optional"]},
                {"name": "operations.sqlite", "owner": "mapper-store", "domains": ["tasks", "queues", "leases", "fences", "journals", "effect-receipts"]},
                {"name": "catalog.sqlite", "owner": "mapper-store", "domains": ["store-catalog", "schema-registry", "migration-ledger"]},
            ],
            "excluded": [{"owner": "simplicio-fast", "paths": [".sfast", "mmap", "TurboQuant"], "reason": "rebuildable binary cache; never SQLite authority"}],
        },
        "compatibility": {
            "python_api": "simplicio_mapper.store",
            "rust_api": "MapperStore/v1 adapter over the same catalog and schema contracts",
            "installed_package_mode": "inventory records local package metadata; no import side effects",
            "cross_domain_transactions": "forbidden; use operations.sqlite receipts and explicit causal IDs",
        },
    }


def _parse_repo(value: str, base: Path) -> tuple[str, Path]:
    if "=" in value:
        repo_id, raw_path = value.split("=", 1)
    else:
        raw_path = value
        repo_id = Path(raw_path).resolve().name
    root = (base / raw_path).resolve() if not os.path.isabs(raw_path) else Path(raw_path).resolve()
    if not root.is_dir():
        raise SystemExit(f"repo does not exist: {root}")
    return repo_id, root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", default=[], help="name=path; repeatable")
    parser.add_argument("--database", action="append", default=[], help="repo-id=path to an existing SQLite file; repeatable")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--check-ddl", action="store_true")
    args = parser.parse_args(argv)
    base = Path.cwd()
    repo_values = args.repo or ["mapper=.", "loop=../simplicio-loop", "dev-cli=../simplicio-dev-cli", "runtime=../simplicio-runtime"]
    repos = [_parse_repo(value, base) for value in repo_values]
    databases = []
    for value in args.database:
        if "=" in value:
            repo_id, raw_path = value.split("=", 1)
        else:
            repo_id, raw_path = "external", value
        path = (base / raw_path).resolve() if not os.path.isabs(raw_path) else Path(raw_path).resolve()
        if not path.is_file():
            raise SystemExit(f"database does not exist: {path}")
        databases.append((repo_id, path))
    payload = build_inventory(repos, databases, args.deterministic)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 1 if args.check_ddl and payload["policy"]["status"] != "pass" else 0


if __name__ == "__main__":
    sys.exit(main())
