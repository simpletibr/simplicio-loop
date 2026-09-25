"""Bounded foreground context with canonical cache and durable deep-work handoff.

The foreground path reads only the selected corridor. Generations are immutable;
promotion and attempt pins are separate atomic records.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__

SCOPED_HANDOFF_SCHEMA = "simplicio.mapper-scoped-context/v1"
GENERATION_SCHEMA = "simplicio.mapper-scoped-generation/v1"
BACKGROUND_SCHEMA = "simplicio.mapper.background-work/v1"
CACHE_SCHEMA = "simplicio.mapper-scoped-cache/v2"
PERFORMANCE_THRESHOLD_MS = 250.0
MAPPER_VERSION = __version__
MAX_NEAREST_TESTS = 3
MAX_PRECEDENTS = 3
RECOMMENDED_NEXT_ACTION = "RUN_FOCUSED_VERIFICATION"

REASON_TARGET_OUTSIDE_SCOPE = "TARGET_OUTSIDE_SCOPE"
REASON_ROOT_MISMATCH = "ROOT_MISMATCH"
REASON_SCOPED_ARTIFACT_STALE = "SCOPED_ARTIFACT_STALE"
REASON_CORRIDOR_INCOMPLETE = "CORRIDOR_INCOMPLETE"
REASON_CACHE_INCOMPATIBLE = "CACHE_INCOMPATIBLE"
REASON_BACKGROUND_PENDING = "BACKGROUND_PENDING"

_ARTIFACTS = ("project-map.json", "symbol-index.json", "call-graph.json", "architecture-inventory.json", "precedent-index.json")
_MANIFESTS = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "requirements.txt"}
_HEX = re.compile(r"^[0-9a-f]{64}$")
_WORKER_ID = re.compile(r"^[0-9a-f]{32}$")


class ScopedContextError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)

@dataclass(frozen=True)
class ScopedRequest:
    repo_root: str
    scope_root: str
    target_hints: tuple[str, ...] = ()
    task_fingerprint: str = ""
    context_budget: int = 8000
    attempt_id: str = ""
    configuration_fingerprint: str = ""

    @classmethod
    def normalize(
        cls,
        repo_root: str,
        *,
        scope_root: str | None = None,
        target_hints: Sequence[str] = (),
        task_fingerprint: str = "",
        context_budget: int = 8000,
        attempt_id: str = "",
        configuration_fingerprint: str = "",
    ) -> ScopedRequest:
        repo = Path(repo_root).expanduser().resolve()
        if not repo.is_dir():
            raise ScopedContextError(REASON_ROOT_MISMATCH, str(repo))
        scope = Path(scope_root or repo).expanduser().resolve()
        _require_inside(scope, repo, REASON_ROOT_MISMATCH)
        if context_budget < 1:
            raise ScopedContextError(REASON_CORRIDOR_INCOMPLETE, "context_budget must be positive")
        normalized: list[str] = []
        for raw_value in target_hints:
            raw = str(raw_value).strip()
            if not raw:
                continue
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = scope / candidate
                repo_candidate = repo / raw
                if not candidate.exists() and repo_candidate.exists():
                    candidate = repo_candidate
            resolved = candidate.resolve()
            _require_inside(resolved, scope, REASON_TARGET_OUTSIDE_SCOPE, raw)
            if resolved.is_file() or _looks_like_path(raw):
                normalized.append(resolved.relative_to(repo).as_posix())
            else:
                normalized.append(raw)
        return cls(
            repo.as_posix(),
            scope.as_posix(),
            tuple(sorted(set(normalized))),
            str(task_fingerprint).strip(),
            int(context_budget),
            str(attempt_id).strip(),
            str(configuration_fingerprint).strip(),
        )


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or bool(Path(value).suffix)


def _require_inside(path: Path, root: Path, reason: str, detail: str = "") -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ScopedContextError(reason, detail or str(path)) from error


def _canon(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _norm(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text

def _safe_source_path(repo: Path, path: str, reason: str = REASON_SCOPED_ARTIFACT_STALE) -> Path:
    normalized = _norm(path)
    candidate = Path(normalized)
    if normalized != path or not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise ScopedContextError(reason, path)
    resolved = (repo / normalized).resolve()
    _require_inside(resolved, repo.resolve(), reason, path)
    if not resolved.is_file():
        raise ScopedContextError(reason, path)
    return resolved


def _artifact_path(repo: Path, out_dir: Path, name: str) -> Path | None:
    candidate = out_dir / name
    if not candidate.exists():
        return None
    resolved = candidate.resolve()
    _require_inside(resolved, repo.resolve(), REASON_SCOPED_ARTIFACT_STALE, name)
    _require_inside(resolved, out_dir.resolve(), REASON_SCOPED_ARTIFACT_STALE, name)
    if not resolved.is_file():
        raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE, name)
    return resolved

def _source_sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE, str(path)) from error


def _read_json(path: Path, reason: str = REASON_SCOPED_ARTIFACT_STALE) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ScopedContextError(reason, str(path)) from error
    if not isinstance(value, dict):
        raise ScopedContextError(reason, str(path))
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}-{uuid.uuid4().hex}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canon(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(temp_name, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.005)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _scope_name(repo: Path, scope: Path) -> str:
    relative = scope.relative_to(repo).as_posix()
    return relative or "."


def _repo_identity(repo: Path) -> str:
    git_entry = repo / ".git"
    if git_entry.is_file():
        marker = git_entry.read_text(encoding="utf-8").strip()
        git_dir = Path(marker.split(":", 1)[-1].strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = (repo / git_dir).resolve()
        common_path = git_dir.parent.parent
    elif git_entry.is_dir():
        common_path = git_entry.resolve()
    else:
        common_path = repo
    return _sha({"git_common_dir": common_path.as_posix()})


def _git_state(repo: Path) -> list[dict[str, int]]:
    git_entry = repo / ".git"
    if git_entry.is_file():
        marker = git_entry.read_text(encoding="utf-8").strip()
        git_dir = Path(marker.split(":", 1)[-1].strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = (repo / git_dir).resolve()
    elif git_entry.is_dir():
        git_dir = git_entry.resolve()
    else:
        return []
    paths = [git_dir / "HEAD", git_dir / "index", git_dir / "packed-refs"]
    head = paths[0]
    if head.is_file():
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref: "):
            paths.append(git_dir.parent.parent / value[5:])
    result: list[dict[str, int]] = []
    for path in paths:
        if path.exists():
            result.append({"size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns})
    return result


def _span(repo: Path, path: str) -> dict[str, Any]:
    source = _safe_source_path(repo, path)
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "path": _norm(path),
        "source_sha256": digest,
        "source_stat": _stat(source),
        "bytes": len(data),
        "spans": [{"start_line": 1, "end_line": max(1, min(120, len(data.splitlines()))), "source_sha256": digest}],
    }

def _default_cache_root() -> Path:
    return Path(os.environ.get("SIMPLICIO_MAPPER_SCOPED_CACHE", str(Path.home() / ".simplicio/mapper/scoped-context-cache"))).expanduser()


def _cache_paths(base: Path, repo_key: str, request_key: str) -> tuple[Path, Path, Path, Path]:
    root = base / repo_key
    return root, root / "generations", root / "promotions" / f"{request_key}.json", root / "pins"


def _generation_path(base: Path, repo_key: str, generation_id: str) -> Path:
    return base / repo_key / "generations" / f"{generation_id}.json"


def _generation_digest(generation: Mapping[str, Any]) -> str:
    content = {key: value for key, value in generation.items() if key != "content_digest"}
    return _sha(content)


def _generation_id(generation: Mapping[str, Any]) -> str:
    inputs = generation.get("generation_inputs")
    if not isinstance(inputs, Mapping):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation inputs")
    return _sha(inputs)


def _artifact_digest(records: Sequence[Mapping[str, Any]]) -> str:
    values = ({"name": str(item.get("name", "")), "sha256": str(item.get("sha256", ""))} for item in records)
    return _sha(sorted(values, key=lambda item: item["name"]))


def _validate_generation(value: Mapping[str, Any], repo: Path, repo_key: str) -> dict[str, Any]:
    if value.get("schema") != GENERATION_SCHEMA or value.get("immutable") is not True:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation schema")
    generation_id = value.get("generation_id")
    if not isinstance(generation_id, str) or _HEX.fullmatch(generation_id) is None:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation id")
    if _generation_id(value) != generation_id:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation identity")
    if value.get("content_digest") != _generation_digest(value):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation content digest")
    producer = value.get("producer")
    inputs = value.get("generation_inputs")
    if not isinstance(producer, Mapping) or producer.get("name") != "simplicio-mapper" or producer.get("version") != MAPPER_VERSION:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "producer version")
    if not isinstance(inputs, Mapping) or inputs.get("mapper_version") != MAPPER_VERSION:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation mapper version")
    expected_input_fingerprint = _sha({"repo_key": inputs.get("repo_key"), "scope": inputs.get("scope"), "targets": inputs.get("targets"), "task": inputs.get("task"), "budget": inputs.get("budget"), "config": inputs.get("config"), "mapper_version": inputs.get("mapper_version")})
    if value.get("input_fingerprint") != expected_input_fingerprint:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "request identity")
    repository = value.get("repository")
    if not isinstance(repository, Mapping) or repository.get("repository_id") != repo_key:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "repository identity")
    if _repo_identity(repo.resolve()) != repo_key:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "request repository identity")
    stored_root = str(repository.get("root", ""))
    if not stored_root:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "repository root")
    stored_root_path = Path(stored_root).expanduser()
    if stored_root_path.exists() and _repo_identity(stored_root_path.resolve()) != repo_key:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "producer repository identity")
    scope_name = repository.get("scope")
    if not isinstance(scope_name, str) or inputs.get("scope") != scope_name:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "repository scope")
    spans = value.get("spans")
    selected = value.get("selected_paths")
    records = value.get("artifact_records")
    precedents = value.get("precedents")
    if not isinstance(spans, list) or not isinstance(selected, list) or not isinstance(records, list) or not isinstance(precedents, list):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation rows")
    if value.get("artifact_digest") != _artifact_digest(records):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "artifact digest")
    span_by_path: dict[str, Mapping[str, Any]] = {}
    for row in spans:
        if not isinstance(row, Mapping):
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "span row")
        path = _norm(row.get("path"))
        if path != row.get("path") or not path:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "span path")
        source_sha = row.get("source_sha256")
        stat = row.get("source_stat")
        if not isinstance(source_sha, str) or _HEX.fullmatch(source_sha) is None or not isinstance(stat, Mapping):
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "span provenance")
        try:
            stat_size = int(stat["size"])
            int(stat["mtime_ns"])
            row_size = int(row.get("bytes", -2))
        except (KeyError, TypeError, ValueError) as error:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "span stat") from error
        if stat_size != row_size:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "span size")
        _safe_source_path(repo, path, REASON_CACHE_INCOMPATIBLE)
        if path in span_by_path:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "duplicate span")
        span_by_path[path] = row
    expected_selected = [
        {"path": row["path"], "why": row.get("why", []), "source_sha256": row["source_sha256"], "source_stat": row["source_stat"]}
        for row in spans
    ]
    if selected != expected_selected or inputs.get("selected") != expected_selected:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "selected span identity")
    expected_artifacts = [
        {"name": str(record.get("name", "")), "sha256": str(record.get("sha256", ""))}
        for record in records
    ]
    if inputs.get("artifacts") != expected_artifacts or inputs.get("artifact_digest") != value.get("artifact_digest"):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "artifact identity")
    if inputs.get("precedents") != precedents:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "precedent identity")
    for row in selected:
        if not isinstance(row, Mapping) or _norm(row.get("path")) not in span_by_path:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "selected span")
        span = span_by_path[_norm(row.get("path"))]
        if row.get("source_sha256") != span.get("source_sha256") or row.get("source_stat") != span.get("source_stat"):
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "selected span digest")
    return dict(value)

def _load_generation(path: Path, repo: Path, repo_key: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _validate_generation(_read_json(path, REASON_CACHE_INCOMPATIBLE), repo, repo_key)


def _load_current(base: Path, repo: Path, repo_key: str, request_key: str) -> dict[str, Any] | None:
    _, _, promotion, _ = _cache_paths(base, repo_key, request_key)
    if not promotion.is_file():
        return None
    pointer = _read_json(promotion, REASON_CACHE_INCOMPATIBLE)
    generation_id = pointer.get("generation_id")
    if not isinstance(generation_id, str) or _HEX.fullmatch(generation_id) is None:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "promotion generation")
    if pointer.get("generation_sha256") != _sha({"generation_id": generation_id}):
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "promotion digest")
    generation = _load_generation(_generation_path(base, repo_key, generation_id), repo, repo_key)
    if generation is None or generation.get("generation_id") != generation_id or generation.get("input_fingerprint") != request_key:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "missing generation")
    return generation


def _load_pin(base: Path, repo: Path, repo_key: str, attempt_id: str) -> dict[str, Any] | None:
    if not attempt_id:
        return None
    _, _, _, pins = _cache_paths(base, repo_key, "unused")
    pin_path = pins / f"{_sha(attempt_id)}.json"
    if not pin_path.is_file():
        return None
    pin = _read_json(pin_path, REASON_CACHE_INCOMPATIBLE)
    if pin.get("schema") != CACHE_SCHEMA or pin.get("attempt_id") != attempt_id:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "attempt pin")
    generation_id = pin.get("generation_id")
    if not isinstance(generation_id, str) or _HEX.fullmatch(generation_id) is None:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "pinned generation")
    generation = _load_generation(_generation_path(base, repo_key, generation_id), repo, repo_key)
    if generation is None or generation.get("generation_id") != generation_id:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "missing pinned generation")
    return generation


def _write_generation(base: Path, repo: Path, repo_key: str, generation: Mapping[str, Any]) -> None:
    path = _generation_path(base, repo_key, str(generation["generation_id"]))
    if path.is_file():
        for attempt in range(20):
            try:
                existing = _load_generation(path, repo, repo_key)
                break
            except ScopedContextError:
                if attempt == 19:
                    raise
                time.sleep(0.005)
        if existing is None or existing.get("content_digest") != generation.get("content_digest"):
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation collision")
        return
    for attempt in range(3):
        try:
            _atomic_json(path, generation)
            existing = _load_generation(path, repo, repo_key)
            if existing is None or existing.get("content_digest") != generation.get("content_digest"):
                raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation collision")
            return
        except (PermissionError, FileExistsError) as error:
            if path.is_file():
                existing = _load_generation(path, repo, repo_key)
                if existing is not None and existing.get("content_digest") == generation.get("content_digest"):
                    return
                raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "generation collision") from error
            if attempt == 2:
                raise
            time.sleep(0.005)

def _promote(base: Path, repo: Path, repo_key: str, request_key: str, generation_id: str) -> None:
    generation = None
    for attempt in range(20):
        try:
            generation = _load_generation(_generation_path(base, repo_key, generation_id), repo, repo_key)
            break
        except ScopedContextError:
            if attempt == 19:
                raise
            time.sleep(0.005)
    if generation is None or generation.get("generation_id") != generation_id:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, "promotion generation")
    _, _, promotion, _ = _cache_paths(base, repo_key, request_key)
    _atomic_json(promotion, {"schema": CACHE_SCHEMA, "generation_id": generation_id, "generation_sha256": _sha({"generation_id": generation_id})})

def _pin(base: Path, repo_key: str, attempt_id: str, generation_id: str) -> None:
    _, _, _, pins = _cache_paths(base, repo_key, "unused")
    _atomic_json(pins / f"{_sha(attempt_id)}.json", {"schema": CACHE_SCHEMA, "attempt_id": attempt_id, "generation_id": generation_id})


def _stat(path: Path) -> dict[str, int]:
    try:
        info = path.stat()
    except OSError as error:
        raise ScopedContextError(REASON_SCOPED_ARTIFACT_STALE, str(path)) from error
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def _artifact_records(repo: Path, out_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    artifacts: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for name in _ARTIFACTS:
        path = _artifact_path(repo, out_dir, name)
        if path is None:
            continue
        artifacts[name] = _read_json(path)
        records.append({"name": name, "sha256": _source_sha(path), "stat": _stat(path), "bytes": path.stat().st_size})
    return artifacts, records


def _artifacts_unchanged(repo: Path, out_dir: Path, records: Sequence[Mapping[str, Any]]) -> bool:
    for record in records:
        try:
            path = _artifact_path(repo, out_dir, str(record.get("name", "")))
            if path is None or _stat(path) != record.get("stat") or _source_sha(path) != record.get("sha256"):
                return False
        except ScopedContextError:
            return False
    return True

def _files_from_artifacts(artifacts: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    project = artifacts.get("project-map.json", {})
    rows = project.get("files", []) if isinstance(project, Mapping) else []
    return {_norm(row.get("path")): row for row in rows if isinstance(row, Mapping) and row.get("path")}


def _target_paths(request: ScopedRequest, repo: Path, files: Mapping[str, Mapping[str, Any]], artifacts: Mapping[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    selected: set[str] = set()
    why: dict[str, list[str]] = {}
    symbols = artifacts.get("symbol-index.json", {}).get("symbols", [])
    for hint in request.target_hints:
        candidate = _norm(hint)
        if candidate in files or (repo / candidate).is_file():
            selected.add(candidate)
            why.setdefault(candidate, []).append("explicit_target")
            continue
        matches = sorted(
            {
                _norm(item.get("defined_in"))
                for item in symbols
                if isinstance(item, Mapping)
                and item.get("defined_in")
                and _norm(item.get("defined_in")) in files
                and (str(item.get("name", "")) == hint or str(item.get("qualified_name", "")) == hint)
            }
        )
        if not matches:
            raise ScopedContextError(REASON_CORRIDOR_INCOMPLETE, hint)
        for path in matches:
            selected.add(path)
            why.setdefault(path, []).append("target_symbol")
    return selected, why


def _closure(selected: set[str], files: Mapping[str, Mapping[str, Any]], artifacts: Mapping[str, Any], scope: str) -> tuple[set[str], dict[str, list[str]]]:
    why: dict[str, list[str]] = {}
    edges = artifacts.get("call-graph.json", {}).get("edges", [])
    expanded = set(selected)
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = _norm(edge.get("source_file") or edge.get("source"))
        target = _norm(edge.get("target_file") or edge.get("target"))
        if source in selected and target in files and _in_scope(target, scope):
            expanded.add(target)
            why.setdefault(target, []).append("direct_callee_or_import")
        if target in selected and source in files and _in_scope(source, scope):
            expanded.add(source)
            why.setdefault(source, []).append("direct_caller_or_import")
    stems = {Path(path).stem.casefold() for path in selected}
    manifest_paths: set[str] = set()
    for seed in sorted(expanded):
        parent = Path(seed).parent
        while True:
            for name in _MANIFESTS:
                candidate = _norm((parent / name).as_posix())
                if candidate in files and _in_scope(candidate, scope):
                    manifest_paths.add(candidate)
            if not parent.parts:
                break
            parent = parent.parent
    for path in sorted(manifest_paths):
        expanded.add(path)
        why.setdefault(path, []).append("manifest")
    test_candidates = [
        path for path in files
        if _in_scope(path, scope)
        and any(token in path.casefold() for token in ("test", "spec"))
        and any(stem in path.casefold() for stem in stems)
    ]
    ranked_tests = sorted(
        set(test_candidates),
        key=lambda path: (-sum(stem in path.casefold() for stem in stems), len(Path(path).parts), path),
    )[:MAX_NEAREST_TESTS]
    for path in ranked_tests:
        expanded.add(path)
        why.setdefault(path, []).append("nearest_test")
    return expanded, why


def _select_precedents(artifacts: Mapping[str, Any], selected: set[str], scope: str) -> list[dict[str, Any]]:
    index = artifacts.get("precedent-index.json", {})
    items = index.get("items", []) if isinstance(index, Mapping) else []
    stems = {Path(path).stem.casefold() for path in selected}
    candidates: list[tuple[int, str, str, Mapping[str, Any]]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        path = _norm(item.get("path"))
        if not path or not _in_scope(path, scope):
            continue
        haystack = " ".join(str(item.get(field, "")) for field in ("path", "summary", "snippet", "tags")).casefold()
        score = sum(stem in haystack for stem in stems)
        if score:
            candidates.append((-score, path, str(item.get("id", "")), item))
    selected_items: list[dict[str, Any]] = []
    for rank, (_, _, _, item) in enumerate(sorted(candidates), start=1):
        if rank > MAX_PRECEDENTS:
            break
        value = dict(item)
        value["rank"] = rank
        value["why"] = "nearest_precedent"
        selected_items.append(value)
    return selected_items

def _in_scope(path: str, scope: str) -> bool:
    normalized = _norm(path)
    return not scope or scope == "." or normalized == scope or normalized.startswith(scope.rstrip("/") + "/")


def _source_changes(repo: Path, generation: Mapping[str, Any], requested: Sequence[str]) -> set[str]:
    known = {str(row["path"]): row for row in generation.get("spans", []) if isinstance(row, Mapping) and row.get("path")}
    candidates = set(known)
    candidates.update(_norm(item) for item in requested)
    changed: set[str] = set()
    for path in candidates:
        normalized = _norm(path)
        candidate = Path(normalized)
        if normalized != path or not normalized or candidate.is_absolute() or ".." in candidate.parts:
            raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, path)
        resolved = (repo / normalized).resolve()
        _require_inside(resolved, repo.resolve(), REASON_CACHE_INCOMPATIBLE, path)
        if not resolved.is_file():
            changed.add(normalized)
            continue
        expected = known.get(path, {}).get("source_sha256")
        if not isinstance(expected, str) or _source_sha(resolved) != expected:
            changed.add(normalized)
    return changed


def _dependency_invalidation(changed: set[str], artifacts: Mapping[str, Any]) -> set[str]:
    invalidated = set(changed)
    edges = artifacts.get("call-graph.json", {}).get("edges", [])
    progress = True
    while progress:
        progress = False
        for edge in edges:
            if not isinstance(edge, Mapping):
                continue
            source = _norm(edge.get("source_file") or edge.get("source"))
            target = _norm(edge.get("target_file") or edge.get("target"))
            if target in invalidated and source not in invalidated:
                invalidated.add(source)
                progress = True
    return invalidated


def _budget_rows(rows: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: row["path"])
    total = sum(int(row.get("bytes", 0)) for row in ordered)
    effective = max(budget, total)
    optional_paths = sorted(
        row["path"] for row in ordered if "nearest_test" in row.get("why", [])
    )
    return ordered, {
        "requested_bytes": budget,
        "effective_bytes": effective,
        "expanded": effective > budget,
        "expansion_bytes": max(0, effective - budget),
        "expansion_reason": "full_required_corridor" if effective > budget else "within_budget",
        "required_paths": [row["path"] for row in ordered],
        "optional_paths": optional_paths,
        "nearest_test_limit": MAX_NEAREST_TESTS,
        "precedent_limit": MAX_PRECEDENTS,
    }

def _background_paths(base: Path, repo_key: str, work_id: str) -> tuple[Path, Path]:
    from .background_work import background_paths

    return background_paths(base, repo_key, work_id)


def _validate_work_id(work_id: str) -> str:
    if not isinstance(work_id, str) or _WORKER_ID.fullmatch(work_id) is None:
        raise ScopedContextError(REASON_BACKGROUND_PENDING, "worker id must be exactly 32 lowercase hex characters")
    return work_id


def _start_background_work(base: Path, repo_key: str, payload: Mapping[str, Any], start: bool) -> dict[str, Any]:
    from .background_work import enqueue_background_work

    return enqueue_background_work(base, repo_key, payload, start=start)


def _run_background_worker(work_id: str, base: Path) -> int:
    from .background_work import run_background_worker

    try:
        return run_background_worker(work_id, base)
    except Exception as error:
        reason = getattr(error, "reason_code", REASON_CACHE_INCOMPATIBLE)
        raise ScopedContextError(reason, str(error)) from error


def _metrics(
    started_wall: float,
    started_cpu: float,
    *,
    cache: str,
    parsed_paths: Sequence[str],
    reused_paths: Sequence[str],
    artifact_files_parsed: int,
    artifact_records: Sequence[Mapping[str, Any]],
    requested_paths: Sequence[str],
    actual_changed_paths: Sequence[str],
    invalidated_paths: Sequence[str] = (),
) -> dict[str, Any]:
    parsed = sorted(set(map(_norm, parsed_paths)))
    reused = sorted(set(map(_norm, reused_paths)))
    changed = sorted(set(map(_norm, actual_changed_paths)))
    return {
        "wall_ms": round((time.perf_counter() - started_wall) * 1000, 3),
        "cpu_ms": round((time.process_time() - started_cpu) * 1000, 3),
        "files_parsed": len(parsed),
        "files_reused": len(reused),
        "parsed_paths": parsed,
        "reused_paths": reused,
        "source_files_parsed": len(parsed),
        "source_files_reused": len(reused),
        "source_paths_parsed": parsed,
        "source_paths_reused": reused,
        "artifact_files_parsed": artifact_files_parsed,
        "artifact_bytes": sum(int(item.get("bytes", item.get("stat", {}).get("size", 0))) for item in artifact_records),
        "cache": cache,
        "changed_paths": sorted(set(map(_norm, requested_paths))),
        "actual_changed_paths": changed,
        "dependency_invalidations": sorted(set(map(_norm, invalidated_paths))),
    }


def _render(
    generation: Mapping[str, Any],
    request: ScopedRequest,
    repo: Path,
    scope: Path,
    metrics: Mapping[str, Any],
    background: Mapping[str, Any],
    pinned: bool,
) -> dict[str, Any]:
    wall_ms = float(metrics.get("wall_ms", 0))
    repository = dict(generation["repository"])
    repository["root"] = repo.as_posix()
    repository["scope_root"] = scope.as_posix()
    repository["scope"] = _scope_name(repo, scope)
    return {
        "schema": SCOPED_HANDOFF_SCHEMA,
        "ready": True,
        "reason_code": REASON_BACKGROUND_PENDING,
        "repository": repository,
        "request": {"target_hints": list(request.target_hints), "task_fingerprint": request.task_fingerprint, "context_budget": request.context_budget, "configuration_fingerprint": request.configuration_fingerprint},
        "generation": {"id": generation["generation_id"], "schema": GENERATION_SCHEMA, "immutable": True, "input_fingerprint": generation["input_fingerprint"], "producer": dict(generation["producer"]), "artifact_digest": generation["artifact_digest"]},
        "attempt": {"id": request.attempt_id, "generation": generation["generation_id"], "pinned": pinned},
        "selected_paths": generation["selected_paths"],
        "spans": generation["spans"],
        "precedents": generation.get("precedents", []),
        "artifact_digest": generation["artifact_digest"],
        "budget": generation["budget"],
        "metrics": dict(metrics) | {"performance_threshold_ms": PERFORMANCE_THRESHOLD_MS, "performance_threshold_passed": wall_ms <= PERFORMANCE_THRESHOLD_MS},
        "background": dict(background),
        "recommended_next_action": RECOMMENDED_NEXT_ACTION,
        "completeness": {"limitations": ["foreground corridor excludes unrelated files"], "deep_required_for": ["repository-wide completeness"]},
    }


def build_scoped_context(
    root: str,
    *,
    scope_root: str | None = None,
    target_hints: Sequence[str] = (),
    task_fingerprint: str = "",
    context_budget: int = 8000,
    attempt_id: str = "",
    configuration_fingerprint: str = "",
    out: str = ".simplicio",
    changed_paths: Sequence[str] = (),
    cache_root: str | None = None,
    start_background: bool = True,
) -> dict[str, Any]:
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    request = ScopedRequest.normalize(root, scope_root=scope_root, target_hints=target_hints, task_fingerprint=task_fingerprint, context_budget=context_budget, attempt_id=attempt_id, configuration_fingerprint=configuration_fingerprint)
    repo = Path(request.repo_root)
    scope = Path(request.scope_root)
    out_dir = (repo / out).resolve() if not Path(out).is_absolute() else Path(out).expanduser().resolve()
    _require_inside(out_dir, repo, REASON_ROOT_MISMATCH, str(out_dir))
    repo_key = _repo_identity(repo)
    base = Path(cache_root).expanduser().resolve() if cache_root else _default_cache_root().resolve()
    scope_name = _scope_name(repo, scope)
    request_key = _sha({"repo_key": repo_key, "scope": scope_name, "targets": request.target_hints, "task": request.task_fingerprint, "budget": request.context_budget, "config": request.configuration_fingerprint, "mapper_version": MAPPER_VERSION})
    pinned = _load_pin(base, repo, repo_key, request.attempt_id)
    if pinned is not None:
        metrics = _metrics(started_wall, started_cpu, cache="pinned", parsed_paths=(), reused_paths=[item.get("path", "") for item in pinned.get("spans", [])], artifact_files_parsed=0, artifact_records=pinned.get("artifact_records", []), requested_paths=changed_paths, actual_changed_paths=())
        background = _start_background_work(base, repo_key, pinned, start_background)
        return _render(pinned, request, repo, scope, metrics, background, True)
    current = _load_current(base, repo, repo_key, request_key)
    git_state = _git_state(repo)
    if current is not None and current.get("repository", {}).get("git_state") == git_state:
        revision = str(current.get("repository", {}).get("revision", ""))
        tree = str(current.get("repository", {}).get("tree", ""))
    else:
        revision = _git(repo, "rev-parse", "HEAD")
        tree = _git(repo, "rev-parse", "HEAD^{tree}")
    requested_changed = {_norm(item) for item in changed_paths}
    actual_changed: set[str] = set()
    if current is not None:
        actual_changed = _source_changes(repo, current, requested_changed)
        if _artifacts_unchanged(repo, out_dir, current.get("artifact_records", [])) and not actual_changed and current.get("repository", {}).get("tree") == tree and current.get("repository", {}).get("git_state") == git_state:
            metrics = _metrics(started_wall, started_cpu, cache="hit", parsed_paths=(), reused_paths=[item.get("path", "") for item in current.get("spans", [])], artifact_files_parsed=0, artifact_records=current.get("artifact_records", []), requested_paths=requested_changed, actual_changed_paths=())
            if request.attempt_id:
                _pin(base, repo_key, request.attempt_id, str(current["generation_id"]))
            background = _start_background_work(base, repo_key, current, start_background)
            return _render(current, request, repo, scope, metrics, background, bool(request.attempt_id))
    artifacts_reused = current is not None and _artifacts_unchanged(repo, out_dir, current.get("artifact_records", []))
    artifacts, records = _artifact_records(repo, out_dir) if not artifacts_reused else ({}, list(current.get("artifact_records", [])))
    if not artifacts and current is not None:
        artifacts = current.get("artifacts", {})
    files = _files_from_artifacts(artifacts)
    selected, why = _target_paths(request, repo, files, artifacts)
    selected, expansion_why = _closure(selected, files, artifacts, scope_name)
    for selected_path, reasons in expansion_why.items():
        why.setdefault(selected_path, []).extend(reasons)
    precedents = _select_precedents(artifacts, selected, scope_name)
    invalidated = _dependency_invalidation(actual_changed, artifacts)
    selected_invalidated = invalidated & selected
    recomputed_paths: set[str] = set()
    reused_paths: set[str] = set()
    rows = []
    cached_row = {str(item.get("path")): item for item in (current or {}).get("spans", []) if isinstance(item, Mapping)}
    for selected_path in sorted(selected):
        if not _in_scope(selected_path, scope_name):
            continue
        if current is not None and selected_path in cached_row and selected_path not in selected_invalidated:
            row = dict(cached_row[selected_path])
            reused_paths.add(selected_path)
        else:
            row = _span(repo, selected_path)
            recomputed_paths.add(selected_path)
        row["why"] = sorted(set(why.get(selected_path, ["corridor"])))
        rows.append(row)
    rows, budget = _budget_rows(rows, request.context_budget)
    if not rows:
        raise ScopedContextError(REASON_CORRIDOR_INCOMPLETE, "no target corridor")
    artifact_digest = _artifact_digest(records)
    selected_inputs = [{"path": row["path"], "why": row["why"], "source_sha256": row["source_sha256"], "source_stat": row["source_stat"]} for row in rows]
    artifact_inputs = [{"name": str(record["name"]), "sha256": str(record["sha256"])} for record in records]
    generation_inputs = {"repo_key": repo_key, "revision": revision, "tree": tree, "scope": scope_name, "targets": request.target_hints, "task": request.task_fingerprint, "budget": request.context_budget, "config": request.configuration_fingerprint, "mapper_version": MAPPER_VERSION, "selected": selected_inputs, "artifacts": artifact_inputs, "artifact_digest": artifact_digest, "precedents": precedents}
    generation_id = _sha(generation_inputs)
    generation = {"schema": GENERATION_SCHEMA, "generation_id": generation_id, "generation_inputs": generation_inputs, "input_fingerprint": request_key, "immutable": True, "producer": {"name": "simplicio-mapper", "version": MAPPER_VERSION}, "repository": {"root": repo.as_posix(), "scope_root": scope.as_posix(), "scope": scope_name, "repository_id": repo_key, "revision": revision, "tree": tree, "git_state": git_state}, "request": {"target_hints": list(request.target_hints)}, "selected_paths": selected_inputs, "spans": rows, "precedents": precedents, "budget": budget, "artifacts": artifacts, "artifact_records": records, "artifact_digest": artifact_digest}
    generation["content_digest"] = _generation_digest(generation)
    _write_generation(base, repo, repo_key, generation)
    _promote(base, repo, repo_key, request_key, generation_id)
    if request.attempt_id:
        _pin(base, repo_key, request.attempt_id, generation_id)
    metrics = _metrics(started_wall, started_cpu, cache="miss" if current is None else "incremental", parsed_paths=recomputed_paths, reused_paths=reused_paths, artifact_files_parsed=0 if artifacts_reused else len(records), artifact_records=records, requested_paths=requested_changed, actual_changed_paths=actual_changed, invalidated_paths=selected_invalidated)
    background = _start_background_work(base, repo_key, generation, start_background)
    return _render(generation, request, repo, scope, metrics, background, bool(request.attempt_id))

def run_scoped_context_cli(argv: Sequence[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="simplicio-mapper scoped-handoff")
    parser.add_argument("root")
    parser.add_argument("--scope-root")
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--task-fingerprint", default="")
    parser.add_argument("--configuration-fingerprint", default="")
    parser.add_argument("--attempt-id", default="")
    parser.add_argument("--context-budget", type=int, default=8000)
    parser.add_argument("--out", default=".simplicio")
    parser.add_argument("--cache-root")
    parser.add_argument("--no-background", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    try:
        payload = build_scoped_context(args.root, scope_root=args.scope_root, target_hints=args.target, task_fingerprint=args.task_fingerprint, context_budget=args.context_budget, attempt_id=args.attempt_id, configuration_fingerprint=args.configuration_fingerprint, out=args.out, changed_paths=args.changed_path, cache_root=args.cache_root, start_background=not args.no_background)
    except ScopedContextError as error:
        payload = {"schema": SCOPED_HANDOFF_SCHEMA, "ready": False, "reason_code": error.reason_code, "detail": str(error)}
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ready"] else 1


__all__ = [
    "BACKGROUND_SCHEMA", "CACHE_SCHEMA", "GENERATION_SCHEMA", "PERFORMANCE_THRESHOLD_MS",
    "REASON_BACKGROUND_PENDING", "REASON_CACHE_INCOMPATIBLE", "REASON_CORRIDOR_INCOMPLETE",
    "REASON_ROOT_MISMATCH", "REASON_SCOPED_ARTIFACT_STALE", "REASON_TARGET_OUTSIDE_SCOPE",
    "SCOPED_HANDOFF_SCHEMA", "ScopedContextError", "ScopedRequest", "build_scoped_context",
    "run_scoped_context_cli",
]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        import argparse

        worker_parser = argparse.ArgumentParser()
        worker_parser.add_argument("--worker", dest="work_id", required=True)
        worker_parser.add_argument("--cache-root", required=True)
        worker_args = worker_parser.parse_args(sys.argv[1:])
        raise SystemExit(_run_background_worker(worker_args.work_id, Path(worker_args.cache_root)))
