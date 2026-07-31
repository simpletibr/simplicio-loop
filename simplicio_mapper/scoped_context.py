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

SCOPED_HANDOFF_SCHEMA = "simplicio.mapper-scoped-context/v1"
GENERATION_SCHEMA = "simplicio.mapper-scoped-generation/v1"
BACKGROUND_SCHEMA = "simplicio.mapper.background-work/v1"
CACHE_SCHEMA = "simplicio.mapper-scoped-cache/v2"
PERFORMANCE_THRESHOLD_MS = 250.0

REASON_TARGET_OUTSIDE_SCOPE = "TARGET_OUTSIDE_SCOPE"
REASON_ROOT_MISMATCH = "ROOT_MISMATCH"
REASON_SCOPED_ARTIFACT_STALE = "SCOPED_ARTIFACT_STALE"
REASON_CORRIDOR_INCOMPLETE = "CORRIDOR_INCOMPLETE"
REASON_CACHE_INCOMPATIBLE = "CACHE_INCOMPATIBLE"
REASON_BACKGROUND_PENDING = "BACKGROUND_PENDING"

_ARTIFACTS = ("project-map.json", "symbol-index.json", "call-graph.json", "architecture-inventory.json")
_MANIFESTS = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "requirements.txt"}
_HEX = re.compile(r"^[0-9a-f]{64}$")


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
        os.replace(temp_name, path)
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
    source = repo / path
    digest = _source_sha(source)
    data = source.read_bytes()
    return {
        "path": path,
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


def _load_generation(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = _read_json(path, REASON_CACHE_INCOMPATIBLE)
    except ScopedContextError:
        return None
    if value.get("schema") != GENERATION_SCHEMA or value.get("immutable") is not True:
        return None
    generation_id = value.get("generation_id")
    return value if isinstance(generation_id, str) and _HEX.fullmatch(generation_id) else None


def _load_current(base: Path, repo_key: str, request_key: str) -> dict[str, Any] | None:
    _, _, promotion, _ = _cache_paths(base, repo_key, request_key)
    if not promotion.is_file():
        return None
    try:
        pointer = _read_json(promotion, REASON_CACHE_INCOMPATIBLE)
        generation_id = str(pointer["generation_id"])
        if pointer.get("generation_sha256") != _sha({"generation_id": generation_id}):
            return None
    except (KeyError, ScopedContextError):
        return None
    return _load_generation(_generation_path(base, repo_key, generation_id))


def _load_pin(base: Path, repo_key: str, attempt_id: str) -> dict[str, Any] | None:
    if not attempt_id:
        return None
    _, _, _, pins = _cache_paths(base, repo_key, "unused")
    safe_id = _sha(attempt_id)
    pin_path = pins / f"{safe_id}.json"
    if not pin_path.is_file():
        return None
    try:
        pin = _read_json(pin_path, REASON_CACHE_INCOMPATIBLE)
        generation_id = str(pin["generation_id"])
    except (KeyError, ScopedContextError):
        return None
    return _load_generation(_generation_path(base, repo_key, generation_id))


def _write_generation(base: Path, repo_key: str, generation: Mapping[str, Any]) -> None:
    path = _generation_path(base, repo_key, str(generation["generation_id"]))
    if path.exists():
        return
    for attempt in range(3):
        try:
            _atomic_json(path, generation)
            return
        except (PermissionError, FileExistsError):
            if path.exists():
                return
            if attempt == 2:
                raise
            time.sleep(0.005)


def _promote(base: Path, repo_key: str, request_key: str, generation_id: str) -> None:
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
        path = out_dir / name
        if path.exists():
            artifacts[name] = _read_json(path)
            records.append({"name": name, "sha256": _source_sha(path), "stat": _stat(path), "bytes": path.stat().st_size})
    return artifacts, records


def _artifacts_unchanged(repo: Path, out_dir: Path, records: Sequence[Mapping[str, Any]]) -> bool:
    for record in records:
        path = out_dir / str(record.get("name", ""))
        if not path.is_file() or _stat(path) != record.get("stat"):
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
    for path in files:
        if not _in_scope(path, scope):
            continue
        if Path(path).name in _MANIFESTS:
            expanded.add(path)
            why.setdefault(path, []).append("manifest")
        if any(token in path.casefold() for token in ("test", "spec")) and any(stem in path.casefold() for stem in stems):
            expanded.add(path)
            why.setdefault(path, []).append("nearest_test")
    return expanded, why


def _in_scope(path: str, scope: str) -> bool:
    normalized = _norm(path)
    return not scope or scope == "." or normalized == scope or normalized.startswith(scope.rstrip("/") + "/")


def _source_changes(repo: Path, generation: Mapping[str, Any], requested: Sequence[str]) -> set[str]:
    known = {str(row["path"]): row for row in generation.get("spans", []) if isinstance(row, Mapping) and row.get("path")}
    candidates = set(known)
    for item in requested:
        candidates.add(_norm(item))
    changed: set[str] = set()
    for path in candidates:
        source = repo / path
        if not source.is_file():
            changed.add(path)
        elif known.get(path, {}).get("source_stat") == _stat(source):
            continue
        elif _source_sha(source) != known.get(path, {}).get("source_sha256"):
            changed.add(path)
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
    total = sum(int(row.get("bytes", 0)) for row in rows)
    if total <= budget:
        return rows, {"requested_bytes": budget, "effective_bytes": budget, "expanded": False, "expansion_bytes": 0}
    ordered = sorted(rows, key=lambda row: (0 if "explicit_target" in row.get("why", []) else 1, row["path"]))
    kept: list[dict[str, Any]] = []
    used = 0
    for row in ordered:
        size = int(row.get("bytes", 0))
        if not kept or used + size <= budget:
            kept.append(row)
            used += size
    effective = max(budget, used)
    return sorted(kept, key=lambda row: row["path"]), {"requested_bytes": budget, "effective_bytes": effective, "expanded": effective > budget, "expansion_bytes": effective - budget}


def _background_paths(base: Path, repo_key: str, work_id: str) -> tuple[Path, Path]:
    root = base / repo_key / "background"
    return root / f"{work_id}.json", root / "queue.jsonl"


def _start_background_work(base: Path, repo_key: str, payload: Mapping[str, Any], start: bool) -> dict[str, Any]:
    work_id = _sha({"repo_key": repo_key, "generation_id": payload["generation_id"]})[:32]
    state_path, queue_path = _background_paths(base, repo_key, work_id)
    if not state_path.exists():
        state = {"schema": BACKGROUND_SCHEMA, "work_id": work_id, "state": "queued", "generation_id": payload["generation_id"], "created_at": time.time()}
        _atomic_json(state_path, state)
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        with queue_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema": BACKGROUND_SCHEMA, "work_id": work_id, "state_path": state_path.as_posix()}, sort_keys=True) + "\n")
    started = False
    if start:
        command = [sys.executable, "-m", "simplicio_mapper.scoped_context", "--worker", work_id, "--cache-root", str(base)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
            started = True
        except OSError:
            started = False
    return {"schema": BACKGROUND_SCHEMA, "state": "started" if started else "queued", "work_id": work_id, "queue_path": queue_path.as_posix(), "started": started, "owner": "simplicio-loop/#408"}


def _run_background_worker(work_id: str, base: Path) -> int:
    matches = list((base).glob(f"*/background/{work_id}.json"))
    if not matches:
        return 2
    state_path = matches[0]
    state = _read_json(state_path, REASON_CACHE_INCOMPATIBLE)
    state = dict(state)
    state.update({"state": "running", "started_at": time.time()})
    _atomic_json(state_path, state)
    state.update({"state": "completed", "completed_at": time.time(), "handoff": "deep-scan-owned-by-issue-408"})
    _atomic_json(state_path, state)
    return 0


def _render(generation: Mapping[str, Any], request: ScopedRequest, metrics: Mapping[str, Any], background: Mapping[str, Any], pinned: bool) -> dict[str, Any]:
    wall_ms = float(metrics.get("wall_ms", 0))
    return {
        "schema": SCOPED_HANDOFF_SCHEMA,
        "ready": True,
        "reason_code": REASON_BACKGROUND_PENDING,
        "repository": generation["repository"],
        "request": {"target_hints": list(request.target_hints), "task_fingerprint": request.task_fingerprint, "context_budget": request.context_budget, "configuration_fingerprint": request.configuration_fingerprint},
        "generation": {"id": generation["generation_id"], "schema": GENERATION_SCHEMA, "immutable": True, "input_fingerprint": generation["input_fingerprint"], "producer": "simplicio-mapper"},
        "attempt": {"id": request.attempt_id, "generation": generation["generation_id"], "pinned": pinned},
        "selected_paths": generation["selected_paths"],
        "spans": generation["spans"],
        "budget": generation["budget"],
        "metrics": dict(metrics) | {"performance_threshold_ms": PERFORMANCE_THRESHOLD_MS, "performance_threshold_passed": wall_ms <= PERFORMANCE_THRESHOLD_MS},
        "background": dict(background),
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
    request_key = _sha({"repo_key": repo_key, "scope": scope_name, "targets": request.target_hints, "task": request.task_fingerprint, "config": request.configuration_fingerprint})
    pinned = _load_pin(base, repo_key, request.attempt_id)
    if pinned is not None:
        metrics = {"wall_ms": round((time.perf_counter() - started_wall) * 1000, 3), "cpu_ms": round((time.process_time() - started_cpu) * 1000, 3), "files_parsed": 0, "files_reused": len(pinned.get("spans", [])), "source_files_parsed": 0, "source_files_reused": len(pinned.get("spans", [])), "artifact_files_parsed": 0, "artifact_bytes": sum(int(item.get("bytes", item.get("stat", {}).get("size", 0))) for item in pinned.get("artifact_records", [])), "cache": "pinned", "changed_paths": sorted(map(_norm, changed_paths)), "actual_changed_paths": []}
        background = _start_background_work(base, repo_key, pinned, start_background)
        return _render(pinned, request, metrics, background, True)
    current = _load_current(base, repo_key, request_key)
    promotion_path = _cache_paths(base, repo_key, request_key)[2]
    if promotion_path.exists() and current is None:
        raise ScopedContextError(REASON_CACHE_INCOMPATIBLE, str(promotion_path))
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
            metrics = {"wall_ms": round((time.perf_counter() - started_wall) * 1000, 3), "cpu_ms": round((time.process_time() - started_cpu) * 1000, 3), "files_parsed": 0, "files_reused": len(current.get("spans", [])), "source_files_parsed": 0, "source_files_reused": len(current.get("spans", [])), "artifact_files_parsed": 0, "artifact_bytes": sum(int(item.get("bytes", item.get("stat", {}).get("size", 0))) for item in current.get("artifact_records", [])), "cache": "hit", "changed_paths": sorted(requested_changed), "actual_changed_paths": []}
            if request.attempt_id:
                _pin(base, repo_key, request.attempt_id, str(current["generation_id"]))
            background = _start_background_work(base, repo_key, current, start_background)
            return _render(current, request, metrics, background, bool(request.attempt_id))
    artifacts, records = _artifact_records(repo, out_dir) if current is None or not _artifacts_unchanged(repo, out_dir, current.get("artifact_records", [])) else ({}, list(current.get("artifact_records", [])))
    if not artifacts and current is not None:
        artifacts = current.get("artifacts", {})
    files = _files_from_artifacts(artifacts)
    selected, why = _target_paths(request, repo, files, artifacts)
    scope_name = _scope_name(repo, scope)
    selected, expansion_why = _closure(selected, files, artifacts, scope_name)
    for path, reasons in expansion_why.items():
        why.setdefault(path, []).extend(reasons)
    invalidated = _dependency_invalidation(actual_changed, artifacts)
    rows = []
    for path in sorted(selected):
        if not _in_scope(path, scope_name):
            continue
        cached_row = {str(item.get("path")): item for item in (current or {}).get("spans", []) if isinstance(item, Mapping)}
        row = dict(cached_row[path]) if current is not None and path in cached_row and path not in invalidated else _span(repo, path)
        row["why"] = sorted(set(why.get(path, ["corridor"])))
        rows.append(row)
    rows, budget = _budget_rows(rows, request.context_budget)
    if not rows:
        raise ScopedContextError(REASON_CORRIDOR_INCOMPLETE, "no target corridor")
    generation_input = {"repo_key": repo_key, "revision": revision, "tree": tree, "scope": scope_name, "targets": request.target_hints, "task": request.task_fingerprint, "config": request.configuration_fingerprint, "selected": [(row["path"], row["source_sha256"]) for row in rows]}
    generation_id = _sha(generation_input)
    generation = {"schema": GENERATION_SCHEMA, "generation_id": generation_id, "input_fingerprint": request_key, "immutable": True, "repository": {"root": repo.as_posix(), "scope_root": scope.as_posix(), "repository_id": repo_key, "revision": revision, "tree": tree, "git_state": git_state}, "request": {"target_hints": list(request.target_hints)}, "selected_paths": [{"path": row["path"], "why": row["why"], "source_sha256": row["source_sha256"]} for row in rows], "spans": rows, "budget": budget, "artifacts": artifacts, "artifact_records": records}
    _write_generation(base, repo_key, generation)
    _promote(base, repo_key, request_key, generation_id)
    if request.attempt_id:
        _pin(base, repo_key, request.attempt_id, generation_id)
    metrics = {"wall_ms": round((time.perf_counter() - started_wall) * 1000, 3), "cpu_ms": round((time.process_time() - started_cpu) * 1000, 3), "files_parsed": len(invalidated) if current is not None else len(rows), "files_reused": max(0, len(rows) - (len(invalidated) if current is not None else len(rows))), "source_files_parsed": len(invalidated) if current is not None else len(rows), "source_files_reused": max(0, len(rows) - (len(invalidated) if current is not None else len(rows))), "artifact_files_parsed": len(records) if current is None else 0, "artifact_bytes": sum(int(item.get("bytes", item.get("stat", {}).get("size", 0))) for item in records), "cache": "miss" if current is None else "incremental", "changed_paths": sorted(requested_changed), "actual_changed_paths": sorted(actual_changed), "dependency_invalidations": sorted(invalidated)}
    background = _start_background_work(base, repo_key, generation, start_background)
    return _render(generation, request, metrics, background, bool(request.attempt_id))


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
