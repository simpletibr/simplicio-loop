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
    ".git", ".simplicio-loop", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".hypothesis", ".tox", ".nox", ".cache", "node_modules",
    "target", "dist", "build", "coverage", "playwright-report", "test-results",
}
TEXT_SUFFIXES = {".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".js", ".jsx", ".json", ".md",
                 ".mjs", ".py", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".yml", ".yaml"}
DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
BEHAVIOR_SUFFIXES = {".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".js", ".jsx", ".mjs", ".py", ".rs", ".sh", ".sql", ".ts", ".tsx"}

PATTERNS = {
    "library": re.compile(r"\b(?:sqlite3|rusqlite|sqlite[_-]vec|sqlite_vec|vec0|fts5|diskcache)\b", re.I),
    "dsn_or_path": re.compile(
        r"(?:sqlite3?://[^\s'\"]+|sqlite3?\.connect\s*\(|Connection::open(?:_with_flags)?\s*\(|"
        r"(?:[\w./~-]+\.(?:db|sqlite3?|sqlite))|SIMPLICIO_[A-Z0-9_]*(?:DB|DATABASE|MEMORY|STORE)[A-Z0-9_]*)",
        re.I,
    ),
    "ddl": re.compile(r"\b(?:CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:VIRTUAL\s+)?TABLE|CREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:UNIQUE\s+)?INDEX|CREATE\s+(?:TEMP(?:ORARY)?\s+)?VIEW|CREATE\s+(?:TEMP(?:ORARY)?\s+)?TRIGGER|ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|TRIGGER|VIEW)|PRAGMA\s+\w+|ATTACH\s+DATABASE|load_extension)\b", re.I),
    "migration": re.compile(r"\b(?:migration|migrate|schema_version|user_version|upgrade|downgrade)\b", re.I),
    "command": re.compile(r"(?:\bsqlite3\b|\.backup\b|\bVACUUM\b|\bBEGIN\s+IMMEDIATE\b|\bwal\b|\bbusy_timeout\b)", re.I),
}
EXECUTE_CALL = re.compile(
    r"(?:\.|::)\s*(?:execute|execute_batch|executescript|executemany|execute_sql|execute_query)\s*\(",
    re.I,
)
# A file may mention SQL in policy text, examples, read-only probes, or tests.
# Count a persistent writer only when a mutation is tied to an execution call.
# Temporary tables and read-only PRAGMAs are deliberately excluded.
PERSISTENT_WRITE_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|REPLACE|UPSERT|"
    r"CREATE\s+(?!(?:TEMP(?:ORARY)?\b))(?:(?:VIRTUAL)\s+)?(?:TABLE|INDEX|VIEW|TRIGGER)|"
    r"ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|TRIGGER|VIEW)|"
    r"PRAGMA\s+(?:journal_mode|wal_checkpoint|user_version))\b",
    re.I,
)
PERSISTENT_DDL_SQL = re.compile(
    r"\b(?:CREATE\s+(?!(?:TEMP(?:ORARY)?\b))(?:(?:VIRTUAL)\s+)?(?:TABLE|INDEX|VIEW|TRIGGER)|"
    r"ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|TRIGGER|VIEW))\b",
    re.I,
)
SECRET_NAME = r"[A-Za-z0-9_-]*(?:token|access[_-]?token|auth[_-]?token|secret(?:[_-]?access[_-]?key)?|password|api[_-]?key|x[_-]?api[_-]?key|private[_-]?key|client[_-]?secret|credential)"  # noqa: S105
SECRET_VALUE = re.compile(
    rf"(?i)(?<![A-Za-z0-9])({SECRET_NAME})"
    r"\s*([:=])\s*(?:(['\"])(.*?)\2|([^\s,;)]+))"
)
BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
SQL_DEFAULT_SECRET = re.compile(
    rf"(?i)({SECRET_NAME}[^,;\n]*?\bDEFAULT\s+)(?:(['\"])(.*?)\2|([^\s,;)]+))"
)
PLACEHOLDER_VALUE = re.compile(r"<([A-Z][A-Z0-9_]+)>")


def _run(*args: str, cwd: Path) -> str | None:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _redact(value: str) -> str:
    redacted = value.strip()
    redacted = BEARER_VALUE.sub("Bearer <redacted>", redacted)
    redacted = SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", redacted)
    redacted = SQL_DEFAULT_SECRET.sub(lambda match: f"{match.group(1)}<redacted>", redacted)
    return PLACEHOLDER_VALUE.sub("<placeholder>", redacted)


def _repo_info(repo_id: str, root: Path) -> dict:
    branch = _run("git", "symbolic-ref", "--short", "HEAD", cwd=root)
    remote = _run("git", "remote", "get-url", "origin", cwd=root)
    default_ref = _run("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=root)
    default_branch = (default_ref or "origin/main").removeprefix("origin/")
    default_revision = _run("git", "rev-parse", f"refs/remotes/origin/{default_branch}", cwd=root)
    changed_files = []
    if default_revision:
        changed_files = sorted(
            line for line in (_run("git", "diff", "--name-only", f"{default_revision}...HEAD", cwd=root) or "").splitlines()
            if line
        )
    working_tree_clean = (_run("git", "status", "--porcelain", "--untracked-files=all", cwd=root) or "") == ""
    return {
        "id": repo_id,
        "path": "." if repo_id == "mapper" else repo_id,
        "branch": branch,
        "revision": _run("git", "rev-parse", "HEAD", cwd=root),
        "default_branch": default_branch,
        "default_revision": default_revision,
        "changed_files": changed_files,
        "working_tree_clean": working_tree_clean,
        "remote": remote,
        "versions": _versions(root),
    }


def _versions(root: Path) -> dict:
    versions: dict[str, str] = {}
    candidates = {
        "python": ("pyproject.toml",),
        "node": ("package.json",),
        "rust": ("Cargo.toml", "rust/Cargo.toml"),
    }
    patterns = {
        "python": re.compile(r"^version\s*=\s*[\"']([^\"']+)", re.M),
        "node": re.compile(r"[\"']version[\"']\s*:\s*[\"']([^\"']+)", re.M),
        "rust": re.compile(r"^version\s*=\s*[\"']([^\"']+)", re.M),
    }
    for name in ("python", "node", "rust"):
        pattern = patterns[name]
        for candidate in candidates[name]:
            path = root / candidate
            try:
                match = pattern.search(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                match = None
            if match:
                versions[name] = match.group(1)
                break
    return versions


def _relative_files(root: Path):
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not (Path(directory) / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path.relative_to(root), path


def _is_fixture_or_test(relative: str) -> bool:
    parts = [part.lower() for part in Path(relative).parts]
    filename = parts[-1] if parts else ""
    return (
        any(part in {"test", "tests", "fixture", "fixtures", "example", "examples", "golden", "spec", "specs"} for part in parts[:-1])
        or filename.startswith("test_")
        or filename.endswith(("_test.py", ".test.js", ".spec.ts", ".spec.js"))
    )


def _is_behavioral_path(relative: str) -> bool:
    return Path(relative).suffix.lower() in BEHAVIOR_SUFFIXES


def _has_write_evidence(lines: list[str], *, suffix: str = "") -> bool:
    return _has_persistent_write_evidence(lines, suffix=suffix)


def _comment_only(line: str) -> bool:
    stripped = line.lstrip()
    return not stripped or stripped.startswith(("#", "//", "/*", "*", "--"))


def _rust_test_filtered_lines(lines: list[str]) -> list[str]:
    """Exclude ``#[cfg(test)]`` items from production-writer detection.

    Rust source files commonly keep fixture schemas in a test module beside
    the production adapter.  Those schemas are not reachable in a release
    build and must not be reported as legacy production writers.  This is a
    deliberately small brace-aware filter; the inventory remains a static
    evidence scanner rather than a Rust parser.
    """
    filtered: list[str] = []
    pending_test_item = False
    excluded_depth: int | None = None

    for line in lines:
        stripped = line.strip()
        if excluded_depth is None and stripped.startswith("#[cfg(test)]"):
            pending_test_item = True
            continue

        if excluded_depth is None and pending_test_item:
            if not stripped or stripped.startswith("#["):
                continue
            if re.search(r"\b(?:mod|fn)\s+[A-Za-z_][A-Za-z0-9_]*\b", stripped) and "{" in stripped:
                excluded_depth = line.count("{") - line.count("}")
                pending_test_item = False
                continue
            else:
                pending_test_item = False

        if excluded_depth is None:
            filtered.append(line)
        elif excluded_depth != 0:
            excluded_depth += line.count("{") - line.count("}")
            if excluded_depth <= 0:
                excluded_depth = None

    return filtered


def _python_ephemeral_fixture_filtered_lines(lines: list[str]) -> list[str]:
    """Exclude the benchmark's in-memory SQL oracle from persistent DDL scans.

    ``scripts/unbiased-benchmark.py`` executes candidate SQL against a
    disposable ``:memory:`` fixture inside ``check_sql``.  Its schema is test
    data, not a Runtime-owned persistent store.  Keep this narrow and
    function-scoped so production Python DDL remains visible to the inventory.
    """
    filtered: list[str] = []
    excluded_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if excluded_indent is not None:
            if stripped and indent <= excluded_indent:
                excluded_indent = None
            else:
                continue
        if excluded_indent is None and re.match(r"^\s*def\s+check_sql\s*\(", line):
            excluded_indent = indent
            continue
        filtered.append(line)
    return filtered


def _has_persistent_write_evidence(lines: list[str], *, suffix: str = "") -> bool:
    """Return true only for executable, persistent SQLite mutation evidence.

    The inventory scans source text, so a file-level ``CREATE TABLE`` match is
    not enough: action-gate policy strings and read-only schema verifiers must
    not be reported as database owners. A small nearby execution window also
    handles multiline ``execute_batch``/``executescript`` statements without
    pretending to parse every host language.
    """
    scan_lines = _rust_test_filtered_lines(lines) if suffix.lower() == ".rs" else lines
    for index, line in enumerate(scan_lines):
        if _comment_only(line) or not PERSISTENT_WRITE_SQL.search(line):
            continue
        if suffix.lower() == ".sql":
            return True
        start = max(0, index - 3)
        end = min(len(scan_lines), index + 4)
        window = " ".join(candidate for candidate in scan_lines[start:end] if not _comment_only(candidate))
        if EXECUTE_CALL.search(window):
            return True
    return False


def _has_persistent_ddl_evidence(lines: list[str], *, suffix: str = "") -> bool:
    """Return true only when executable, non-temporary DDL is present."""
    if suffix.lower() == ".rs":
        scan_lines = _rust_test_filtered_lines(lines)
    elif suffix.lower() == ".py":
        scan_lines = _python_ephemeral_fixture_filtered_lines(lines)
    else:
        scan_lines = lines
    for index, line in enumerate(scan_lines):
        if _comment_only(line) or not PERSISTENT_DDL_SQL.search(line):
            continue
        if re.search(r"\btemp(?:orary)?\b|\btemp\.", line, re.I):
            continue
        if suffix.lower() == ".sql":
            return True
        start = max(0, index - 3)
        end = min(len(scan_lines), index + 4)
        window = " ".join(candidate for candidate in scan_lines[start:end] if not _comment_only(candidate))
        if EXECUTE_CALL.search(window):
            return True
    return False


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
    if _is_behavioral_path(relative) and ("ddl" in kinds or "dsn_or_path" in kinds):
        return "production-candidate"
    return "reference"


def _target_store_path(relative: str, kinds: set[str], hints: str = "") -> str:
    lowered = f"{relative} {hints}".lower()
    if any(token in lowered for token in ("queue", "lease", "fence", "journal", "receipt", "operation")):
        store = "operations.sqlite"
    elif any(token in lowered for token in ("memory", "handoff", "embedding", "fts", "vec")):
        store = "memory.sqlite"
    elif any(token in lowered for token in ("migration", "registry", "catalog", "schema")):
        store = "catalog.sqlite"
    else:
        store = "semantic.sqlite"
    return f"~/.simplicio-loop/data/{store}"


def _scan_sources(repo_id: str, root: Path, changed_files: set[str] | None = None) -> tuple[list[dict], list[dict]]:
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
        behavioral = _is_behavioral_path(relative)
        evidence_text = " ".join(match["evidence"] for match in file_matches)
        writers = (
            [repo_id]
            if behavioral and _has_persistent_write_evidence(lines, suffix=path.suffix)
            else []
        )
        ddl_writers = (
            [repo_id]
            if behavioral and _has_persistent_ddl_evidence(lines, suffix=path.suffix)
            else []
        )
        matrix.append({
            "repo": repo_id,
            "file": relative_text,
            "current_path": relative_text,
            "target_path": _target_store_path(relative_text, kinds, evidence_text),
            "kinds": sorted(kinds),
            "classification": classification,
            "current_owner": repo_id,
            "target_owner": "mapper-store",
            "readers": [repo_id],
            "writers": writers,
            "ddl_writers": ddl_writers,
            "changed_since_default": relative_text in (changed_files or set()) if changed_files is not None else None,
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
        sidecars = {}
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{path}{suffix}")
            if sidecar.is_file() and not sidecar.is_symlink():
                sidecars[suffix[1:]] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        if sidecars:
            record["sidecar_sha256"] = sidecars
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


def _is_database_path(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in DATABASE_SUFFIXES and not name.endswith(("-wal", "-shm"))


def _is_database_sidecar(path: Path) -> bool:
    return path.name.lower().endswith(("-wal", "-shm"))


def _discover_databases(repo_id: str, root: Path) -> list[dict]:
    records = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not (Path(directory) / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if _is_database_path(path) and not path.is_symlink():
                records.append(_database_info(path, repo_id, path.relative_to(root).as_posix()))
    return sorted(records, key=lambda item: (item["repo"], item["path"]))


def _policy(matrix: list[dict]) -> dict:
    violations = []
    legacy_ddl_files = []
    for item in matrix:
        is_legacy_writer = (
            item["repo"] != "mapper"
            and "ddl" in item["kinds"]
            and item.get("criticality") == "critical"
            and bool(item.get("ddl_writers", item.get("writers")))
        )
        if is_legacy_writer:
            legacy_ddl_files.append({"repo": item["repo"], "file": item["file"]})
            continue
        if item["criticality"] == "test-only":
            continue
        if "ddl" in item["kinds"] and item.get("ddl_writers", item["writers"]) and not (
            item["file"].startswith("simplicio_mapper/store/")
            or item["file"].startswith("simplicio_mapper/contracts/mapper-store/")
            or item["file"] == "scripts/mapper_store_inventory.py"
            or _is_fixture_or_test(item["file"])
        ):
            violations.append({"repo": item["repo"], "file": item["file"], "reason": "DDL outside allowlisted MapperStore paths"})
    return {
        "schema": "simplicio.mapper-store-ddl-policy/v1",
        "allowlisted_paths": ["simplicio_mapper/store/", "simplicio_mapper/contracts/mapper-store/", "scripts/mapper_store_inventory.py", "tests/", "fixtures/"],
        "violations": violations,
        "legacy_ddl_matches": len(legacy_ddl_files),
        "legacy_ddl_files": legacy_ddl_files,
        "scope": "Mapper repository DDL only; consumer repositories are inventoried as legacy evidence",
        "status": "pass" if not violations else "fail",
        "note": "This is a local/read-only gate; no GitHub Actions workflow is added by this issue.",
    }


def build_inventory(repos: list[tuple[str, Path]], databases: list[tuple], deterministic: bool = False) -> dict:
    repo_records = []
    matches = []
    matrix = []
    db_records = []
    for repo_id, root in repos:
        repo_info = _repo_info(repo_id, root)
        repo_info["files_scanned"] = 0
        repo_info["files_scanned"] = sum(1 for _ in _relative_files(root))
        repo_matches, repo_matrix = _scan_sources(repo_id, root, set(repo_info["changed_files"]))
        repo_records.append(repo_info)
        matches.extend(repo_matches)
        matrix.extend(repo_matrix)
        db_records.extend(_discover_databases(repo_id, root))
    for database in databases:
        repo_id, path = database[:2]
        display_path = database[2] if len(database) > 2 else path.name
        db_records.append(_database_info(path, repo_id, display_path))
    if deterministic:
        repo_records.sort(key=lambda item: item["id"])
        matches.sort(key=lambda item: (item["repo"], item["file"]))
        db_records.sort(key=lambda item: (item["repo"], item["path"]))
        matrix.sort(key=lambda item: (item["repo"], item["file"], item.get("table", "")))
    for database in db_records:
        for database_object in database.get("objects", []):
            if database_object.get("kind") != "table":
                continue
            matrix.append({
                "repo": database["repo"],
                "file": database["path"],
                "current_path": database["path"],
                "target_path": _target_store_path(database["path"], {"materialized-db"}),
                "table": database_object["name"],
                "kinds": ["materialized-db"],
                "classification": "materialized-store",
                "current_owner": database["repo"],
                "target_owner": "mapper-store",
                "readers": [database["repo"]],
                "writers": [database["repo"]],
                "changed_since_default": None,
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
            "root": "~/.simplicio-loop/data/",
            "stores": [
                {"name": "semantic.sqlite", "owner": "mapper-store", "domains": ["ContextGraph", "symbols", "precedents", "documents"]},
                {"name": "memory.sqlite", "owner": "mapper-store", "domains": ["memory", "handoff", "FTS5", "embeddings", "sqlite-vec-optional"]},
                {"name": "operations.sqlite", "owner": "mapper-store", "domains": ["tasks", "queues", "leases", "fences", "journals", "effect-receipts"]},
                {"name": "catalog.sqlite", "owner": "mapper-store", "domains": ["store-catalog", "schema-registry", "migration-ledger"]},
            ],
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
    databases = []
    for value in args.database:
        if "=" in value:
            repo_id, raw_path = value.split("=", 1)
        else:
            repo_id, raw_path = "external", value
        raw_path_obj = (base / raw_path) if not os.path.isabs(raw_path) else Path(raw_path)
        if raw_path_obj.is_symlink():
            raise SystemExit(f"database must not be a symlink: {raw_path_obj}")
        path = raw_path_obj.resolve()
        if not path.is_file() or _is_database_sidecar(path):
            raise SystemExit(f"database does not exist: {path}")
        display_path = raw_path_obj.as_posix() if not raw_path_obj.is_absolute() else f"<external>/{path.name}"
        databases.append((repo_id, path, display_path))
    # Validate explicit database arguments before resolving default repository
    # roots.  A malformed or symlinked database must fail with its actionable
    # database error even when the caller is using the default cross-repo
    # layout and one sibling checkout is unavailable.
    repos = [_parse_repo(value, base) for value in repo_values]
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
