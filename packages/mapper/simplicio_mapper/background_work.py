"""Durable background deep mapping worker (issue #408)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BACKGROUND_SCHEMA = "simplicio.mapper.background-work/v1"
EVENT_SCHEMA = "simplicio.mapper.background-event/v1"
STATES = frozenset({"queued", "running", "checkpointed", "completed", "promoted", "cancelled", "failed"})
TERMINAL = frozenset({"promoted", "cancelled", "failed"})
REASON_QUEUED = "QUEUED"
REASON_RUNNING = "LEASE_ACQUIRED"
REASON_CHECKPOINTED = "CHECKPOINT_SAVED"
REASON_COMPLETED = "CANDIDATE_VALIDATED"
REASON_PROMOTED = "PROMOTED_ATOMICALLY"
REASON_CANCELLED = "CANCELLED_REQUESTED"
REASON_RECLAIMED = "LEASE_EXPIRED_RECLAIMED"
REASON_STALE_TREE = "STALE_GIT_TREE"
REASON_NO_RSS = "RSS_METRIC_UNAVAILABLE"
LEASE_SECONDS = 30.0
CHUNK_SIZE = 16
CPU_PERCENT = 35
IO_RATE = 8 * 1024 * 1024
IGNORE = frozenset(
    {
        ".git",
        ".simplicio-loop",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
    }
)


class BackgroundWorkError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _now() -> float:
    return time.time()


def _read(path: Path) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(20):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError, json.JSONDecodeError) as current:
            error = current
            if attempt == 19:
                raise BackgroundWorkError("CORRUPT_STATE", str(path)) from current
            time.sleep(0.005)
    else:
        raise BackgroundWorkError("CORRUPT_STATE", str(path)) from error
    if not isinstance(value, dict):
        raise BackgroundWorkError("CORRUPT_STATE", str(path))
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            data = (
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            )
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.005)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _event(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    for attempt in range(20):
        try:
            with path.open("ab") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.005)


@contextmanager
def _lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = _now() + timeout
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if _now() - path.stat().st_mtime > timeout:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if _now() >= deadline:
                raise BackgroundWorkError("QUEUE_LOCK_TIMEOUT", str(path)) from None
            time.sleep(0.01)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _repo_key(repo: Path) -> str:
    entry = repo / ".git"
    if entry.is_file():
        marker = entry.read_text(encoding="utf-8").strip()
        git_dir = Path(marker.split(":", 1)[-1].strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = (repo / git_dir).resolve()
        root = git_dir.parent.parent
    else:
        root = entry.resolve() if entry.is_dir() else repo.resolve()
    return _sha({"git_common_dir": root.as_posix()})


def _tree(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _files(repo: Path) -> list[str]:
    return sorted(
        p.relative_to(repo).as_posix()
        for p in repo.rglob("*")
        if p.is_file() and not any(part in IGNORE for part in p.relative_to(repo).parts)
    )


def _language(path: str) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".rs": "rust",
        ".go": "go",
        ".json": "json",
        ".md": "markdown",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".ps1": "powershell",
    }.get(Path(path).suffix.lower(), "other")


def _record(repo: Path, relative: str) -> tuple[dict[str, Any], int]:
    path = repo / relative
    try:
        stat = path.stat()
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
                count += len(chunk)
    except OSError as error:
        raise BackgroundWorkError("FILE_READ_FAILED", relative) from error
    return {
        "path": relative,
        "language": _language(relative),
        "bytes": count,
        "sha256": digest.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }, count


def _metrics(
    start_wall: float, start_cpu: float, scanned: int, reused: int, total: int, chunks: int, io_bytes: int
) -> dict[str, Any]:
    return {
        "wall_ms": round((_now() - start_wall) * 1000, 3),
        "cpu_ms": round((time.process_time() - start_cpu) * 1000, 3),
        "files_scanned": scanned,
        "files_reused": reused,
        "files_total": total,
        "chunks": chunks,
        "io_bytes": io_bytes,
        "io_reason_code": None,
        "rss_bytes": None,
        "rss_reason_code": REASON_NO_RSS,
        "cpu_limit_percent": CPU_PERCENT,
        "cpu_limit_reason_code": None,
        "io_limit_bytes_per_second": IO_RATE,
        "foreground_priority": True,
        "unavailable": {},
    }


class BackgroundQueue:
    def __init__(self, cache_root: str | os.PathLike[str], repo_key: str) -> None:
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.repo_key = repo_key
        self.root = self.cache_root / repo_key / "background"
        self.checkpoints = self.root / "checkpoints"
        self.generations = self.root / "generations"
        self.promotion = self.root / "promotion.json"
        self.queue_log = self.root / "queue.jsonl"
        self.events = self.root / "events.jsonl"
        self.lock_path = self.root / ".queue.lock"

    @classmethod
    def for_repo(cls, repo: str | os.PathLike[str], cache_root: str | os.PathLike[str]) -> BackgroundQueue:
        return cls(cache_root, _repo_key(Path(repo).expanduser().resolve()))

    def _path(self, work_id: str) -> Path:
        return self.root / f"{work_id}.json"

    def _checkpoint(self, work_id: str) -> Path:
        return self.checkpoints / f"{work_id}.json"

    def _state(self, work_id: str) -> dict[str, Any]:
        state = _read(self._path(work_id))
        if (
            state.get("schema") != BACKGROUND_SCHEMA
            or state.get("work_id") != work_id
            or state.get("state") not in STATES
        ):
            raise BackgroundWorkError("CORRUPT_STATE", work_id)
        return state

    def _receipt(self, state: Mapping[str, Any], event: str, reason: str) -> None:
        _event(
            self.events,
            {
                "schema": EVENT_SCHEMA,
                "event": event,
                "work_id": state["work_id"],
                "dedup_key": state["dedup_key"],
                "state": state["state"],
                "reason_code": reason,
                "created_at": _now(),
                "generation_id": state.get("candidate_generation_id"),
                "metrics": state.get("metrics", {}),
            },
        )

    def enqueue(self, payload: Mapping[str, Any], start: bool = True) -> dict[str, Any]:
        repo, inputs = payload.get("repository"), payload.get("generation_inputs")
        if not isinstance(repo, Mapping) or not isinstance(inputs, Mapping):
            raise BackgroundWorkError("CORRUPT_STATE", "generation payload")
        dedup = _sha(
            {
                "schema": BACKGROUND_SCHEMA,
                "repository_id": self.repo_key,
                "tree": inputs.get("tree", ""),
                "configuration": inputs.get("config", ""),
                "scope": inputs.get("scope", ""),
                "targets": inputs.get("targets", []),
                "task": inputs.get("task", ""),
                "mapper_version": inputs.get("mapper_version", ""),
                "base_generation": payload.get("generation_id", ""),
            }
        )
        work_id = dedup[:32]
        with _lock(self.lock_path):
            path = self._path(work_id)
            if path.is_file():
                state = self._state(work_id)
            else:
                state = {
                    "schema": BACKGROUND_SCHEMA,
                    "work_id": work_id,
                    "dedup_key": dedup,
                    "state": "queued",
                    "reason_code": REASON_QUEUED,
                    "created_at": _now(),
                    "updated_at": _now(),
                    "repository": {
                        "repository_id": self.repo_key,
                        "root": str(repo.get("root", "")),
                        "tree": str(inputs.get("tree", "")),
                        "revision": str(inputs.get("revision", "")),
                    },
                    "base_generation_id": str(payload.get("generation_id", "")),
                    "requested_scope": {
                        "scope": str(inputs.get("scope", "")),
                        "targets": list(inputs.get("targets", [])),
                        "configuration": str(inputs.get("config", "")),
                    },
                    "mapper_version": str(inputs.get("mapper_version", "")),
                    "priority": "background",
                    "resource_limits": {
                        "cpu_percent": CPU_PERCENT,
                        "rss_bytes": None,
                        "rss_reason_code": REASON_NO_RSS,
                        "io_bytes_per_second": IO_RATE,
                        "foreground_reserved": True,
                    },
                    "lease": None,
                    "cancellation": {"requested": False, "requested_at": None},
                    "checkpoint": {
                        "cursor": 0,
                        "total": 0,
                        "completed": 0,
                        "last_path": None,
                        "checkpoint_path": str(self._checkpoint(work_id)),
                    },
                    "candidate_generation_id": None,
                    "metrics": _metrics(_now(), time.process_time(), 0, 0, 0, 0, 0),
                    "reason_codes": [],
                    "start_requested": bool(start),
                    "spawn": {"requested": False, "started": False, "pid": None, "reason_code": None},
                }
                _write(path, state)
                _event(
                    self.queue_log,
                    {
                        "schema": BACKGROUND_SCHEMA,
                        "event": "queued",
                        "work_id": work_id,
                        "dedup_key": dedup,
                        "created_at": state["created_at"],
                    },
                )
                self._receipt(state, "queued", REASON_QUEUED)
        result = self.status(work_id)
        result.update(
            pending=result["state"] not in TERMINAL,
            started=result["state"] in {"running", "checkpointed", "completed", "promoted"},
        )
        return self.start(work_id) if start and result["state"] in {"queued", "checkpointed"} else result

    def start(self, work_id: str) -> dict[str, Any]:
        with _lock(self.lock_path):
            state = self._state(work_id)
            if state["state"] in TERMINAL or state["state"] == "running":
                return state
            state["start_requested"] = True
            state["spawn"]["requested"] = True
            _write(self._path(work_id), state)
        command = [
            sys.executable,
            "-m",
            "simplicio_mapper.background_work",
            "--worker",
            work_id,
            "--cache-root",
            str(self.cache_root),
        ]
        try:
            flags = (
                0
                if os.name != "nt"
                else getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=os.name != "nt",
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            with _lock(self.lock_path):
                state = self._state(work_id)
                state["spawn"].update(reason_code="WORKER_SPAWN_UNAVAILABLE", started=False)
                _write(self._path(work_id), state)
            return state
        with _lock(self.lock_path):
            state = self._state(work_id)
            state["spawn"].update(reason_code=None, started=True, pid=process.pid)
            _write(self._path(work_id), state)
            return state

    def claim(self, work_id: str, lease_seconds: float = LEASE_SECONDS) -> dict[str, Any] | None:
        with _lock(self.lock_path):
            state = self._state(work_id)
            now = _now()
            if state["state"] in TERMINAL:
                return None
            lease = state.get("lease")
            if (
                state["state"] == "running"
                and isinstance(lease, Mapping)
                and float(lease.get("expires_at", 0)) > now
            ):
                return None
            if state["state"] == "running":
                state.setdefault("reason_codes", []).append(REASON_RECLAIMED)
            token = uuid.uuid4().hex
            state.update(
                state="running",
                reason_code=REASON_RUNNING,
                lease={
                    "owner": f"{platform.node()}:{os.getpid()}",
                    "token": token,
                    "heartbeat_at": now,
                    "expires_at": now + max(0.01, lease_seconds),
                },
                updated_at=now,
            )
            _write(self._path(work_id), state)
            self._receipt(state, "started", REASON_RUNNING)
            return state

    def heartbeat(self, work_id: str, token: str, lease_seconds: float = LEASE_SECONDS) -> None:
        with _lock(self.lock_path):
            state = self._state(work_id)
            lease = state.get("lease")
            if not isinstance(lease, Mapping) or lease.get("token") != token:
                raise BackgroundWorkError("LEASE_FENCED", work_id)
            if float(lease.get("expires_at", 0)) <= _now():
                raise BackgroundWorkError("LEASE_EXPIRED", work_id)
            now = _now()
            state["lease"] = dict(lease) | {"heartbeat_at": now, "expires_at": now + max(0.01, lease_seconds)}
            _write(self._path(work_id), state)

    def cancel(self, work_id: str) -> dict[str, Any]:
        with _lock(self.lock_path):
            state = self._state(work_id)
            if state["state"] in TERMINAL:
                return state
            state["cancellation"] = {"requested": True, "requested_at": _now()}
            state.setdefault("reason_codes", []).append(REASON_CANCELLED)
            if state["state"] == "queued":
                state.update(state="cancelled", reason_code=REASON_CANCELLED, lease=None)
            _write(self._path(work_id), state)
            self._receipt(state, "cancel_requested", REASON_CANCELLED)
            return state

    def resume(self, work_id: str, start: bool = True) -> dict[str, Any]:
        with _lock(self.lock_path):
            state = self._state(work_id)
            if state["state"] == "promoted":
                return state
            state.update(
                state="queued",
                reason_code=REASON_QUEUED,
                lease=None,
                cancellation={"requested": False, "requested_at": None},
            )
            _write(self._path(work_id), state)
            self._receipt(state, "resumed", REASON_QUEUED)
        return self.start(work_id) if start else self.status(work_id)

    def checkpoint(
        self,
        work_id: str,
        token: str,
        cursor: int,
        total: int,
        records: Sequence[Mapping[str, Any]],
        scanned: int,
        reused: int,
        chunks: int,
        io_bytes: int,
        start_wall: float,
        start_cpu: float,
        lease_seconds: float = LEASE_SECONDS,
    ) -> None:
        self.heartbeat(work_id, token, lease_seconds)
        rows = list(records)
        data = {
            "schema": BACKGROUND_SCHEMA,
            "work_id": work_id,
            "cursor": cursor,
            "total": total,
            "completed": len(rows),
            "last_path": rows[-1]["path"] if rows else None,
            "records": rows,
            "scanned": scanned,
            "reused": reused,
            "chunks": chunks,
            "io_bytes": io_bytes,
            "path_digest": _sha([r["path"] for r in rows]),
            "updated_at": _now(),
        }
        _write(self._checkpoint(work_id), data)
        with _lock(self.lock_path):
            state = self._state(work_id)
            if state.get("lease", {}).get("token") != token:
                raise BackgroundWorkError("LEASE_FENCED", work_id)
            state.update(
                state="checkpointed",
                reason_code=REASON_CHECKPOINTED,
                checkpoint={
                    "cursor": cursor,
                    "total": total,
                    "completed": len(rows),
                    "last_path": data["last_path"],
                    "checkpoint_path": str(self._checkpoint(work_id)),
                },
                metrics=_metrics(start_wall, start_cpu, scanned, reused, total, chunks, io_bytes),
                updated_at=_now(),
            )
            _write(self._path(work_id), state)
            self._receipt(state, "checkpointed", REASON_CHECKPOINTED)

    def status(self, work_id: str | None = None) -> dict[str, Any]:
        if work_id:
            return self._state(work_id)
        items = []
        for path in sorted(self.root.glob("*.json")):
            try:
                items.append(_read(path))
            except BackgroundWorkError:
                items.append(
                    {
                        "schema": BACKGROUND_SCHEMA,
                        "state": "failed",
                        "reason_code": "CORRUPT_STATE",
                        "path": str(path),
                    }
                )
        return {
            "schema": BACKGROUND_SCHEMA,
            "repository_id": self.repo_key,
            "counts": {state: sum(row.get("state") == state for row in items) for state in sorted(STATES)},
            "items": items,
        }

    def doctor(self) -> dict[str, Any]:
        recovered = corrupt = 0
        for path in self.root.glob("*.json"):
            try:
                state = self._state(path.stem)
            except BackgroundWorkError:
                corrupt += 1
                continue
            lease = state.get("lease")
            if (
                state["state"] == "running"
                and isinstance(lease, Mapping)
                and float(lease.get("expires_at", 0)) <= _now()
            ):
                with _lock(self.lock_path):
                    state = self._state(path.stem)
                    if state["state"] == "running" and float(state["lease"]["expires_at"]) <= _now():
                        state.update(state="queued", reason_code=REASON_RECLAIMED, lease=None)
                        state.setdefault("reason_codes", []).append(REASON_RECLAIMED)
                        _write(path, state)
                        self._receipt(state, "reclaimed", REASON_RECLAIMED)
                        recovered += 1
        return {
            "schema": BACKGROUND_SCHEMA,
            "ok": corrupt == 0,
            "repository_id": self.repo_key,
            "recovered_leases": recovered,
            "corrupt_records": corrupt,
            "reason_codes": [] if corrupt == 0 else ["CORRUPT_STATE"],
            "metrics": {"rss_bytes": None, "rss_reason_code": REASON_NO_RSS},
        }

    def promote(self, work_id: str, candidate: Mapping[str, Any], token: str) -> dict[str, Any]:
        validate_candidate(candidate, work_id)
        with _lock(self.lock_path):
            state = self._state(work_id)
            if state.get("lease", {}).get("token") != token:
                raise BackgroundWorkError("LEASE_FENCED", work_id)
            previous = []
            if self.promotion.is_file():
                pointer = _read(self.promotion)
                previous = list(pointer.get("rollback_generation_ids", []))
                active = pointer.get("active_generation_id")
                if isinstance(active, str):
                    previous.insert(0, active)
            retained = previous[:2]
            generation_id = str(candidate["generation_id"])
            _write(
                self.promotion,
                {
                    "schema": BACKGROUND_SCHEMA,
                    "active_generation_id": generation_id,
                    "rollback_generation_ids": retained,
                    "promoted_at": _now(),
                    "promotion_digest": _sha(
                        {"active_generation_id": generation_id, "rollback_generation_ids": retained}
                    ),
                },
            )
            state.update(
                state="promoted",
                reason_code=REASON_PROMOTED,
                candidate_generation_id=generation_id,
                lease=None,
            )
            state["metrics"] = dict(state.get("metrics", {})) | {
                "promotion": "atomic",
                "rollback_retained": retained,
            }
            _write(self._path(work_id), state)
            self._receipt(state, "promoted", REASON_PROMOTED)
            return state

    def gc(self, retention_seconds: float = 3600) -> dict[str, Any]:
        retained = set()
        if self.promotion.is_file():
            pointer = _read(self.promotion)
            retained.update(map(str, pointer.get("rollback_generation_ids", [])))
            active = pointer.get("active_generation_id")
            if active:
                retained.add(str(active))
        for pin in (self.cache_root / self.repo_key / "pins").glob("*.json"):
            try:
                value = _read(pin)
                if value.get("generation_id"):
                    retained.add(str(value["generation_id"]))
            except BackgroundWorkError:
                pass
        deleted = 0
        for path in self.generations.glob("*.json"):
            if path.stem not in retained and _now() - path.stat().st_mtime >= retention_seconds:
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass
        return {
            "schema": BACKGROUND_SCHEMA,
            "deleted": deleted,
            "retained_generation_ids": sorted(retained),
            "reason_codes": [],
        }


def validate_candidate(candidate: Mapping[str, Any], expected_work_id: str | None = None) -> dict[str, Any]:
    records = candidate.get("records")
    if (
        candidate.get("schema") != BACKGROUND_SCHEMA
        or candidate.get("complete") is not True
        or (expected_work_id and candidate.get("work_id") != expected_work_id)
    ):
        raise BackgroundWorkError("CANDIDATE_INVALID", "identity")
    if (
        not isinstance(records, list)
        or records != sorted(records, key=lambda row: row.get("path", ""))
        or len({row.get("path") for row in records if isinstance(row, Mapping)}) != len(records)
    ):
        raise BackgroundWorkError("CANDIDATE_INVALID", "records")
    if candidate.get("records_digest") != _sha(records) or int(candidate.get("scanned_count", -1)) != len(
        records
    ):
        raise BackgroundWorkError("CANDIDATE_INVALID", "digest or count")
    return dict(candidate)


def _throttle(start: float, io_bytes: int) -> None:
    time.sleep(max(0, (time.perf_counter() - start) * (100 / CPU_PERCENT - 1)))
    time.sleep(max(0, io_bytes / IO_RATE - (time.perf_counter() - start)))


def run_worker(
    work_id: str,
    cache_root: str | os.PathLike[str],
    *,
    lease_seconds: float = LEASE_SECONDS,
    chunk_size: int = CHUNK_SIZE,
    stop_after_chunks: int | None = None,
) -> int:
    cache = Path(cache_root).expanduser().resolve()
    matches = list(cache.glob(f"*/background/{work_id}.json"))
    if len(matches) != 1:
        raise BackgroundWorkError("WORK_NOT_FOUND", work_id)
    state_path = matches[0]
    queue = BackgroundQueue(cache, state_path.parent.parent.name)
    claimed = queue.claim(work_id, lease_seconds)
    if claimed is None:
        return 0
    token = str(claimed["lease"]["token"])
    repo = Path(str(claimed["repository"]["root"])).expanduser().resolve()
    start_wall, start_cpu = _now(), time.process_time()
    try:
        paths = _files(repo)
        expected, actual = str(claimed["repository"].get("tree", "")), _tree(repo)
        if expected and actual and expected != actual:
            raise BackgroundWorkError(REASON_STALE_TREE, actual)
        cursor = scanned = reused = chunks = io_bytes = 0
        records = []
        checkpoint = queue._checkpoint(work_id)
        if checkpoint.is_file():
            data = _read(checkpoint)
            cursor, records = int(data.get("cursor", 0)), list(data.get("records", []))
            scanned, reused, chunks, io_bytes = (
                int(data.get(k, 0)) for k in ("scanned", "reused", "chunks", "io_bytes")
            )
            if data.get("path_digest") not in (None, _sha([row["path"] for row in records])):
                raise BackgroundWorkError(REASON_STALE_TREE, "checkpoint")
        prior = {row.get("path"): row for row in records if isinstance(row, Mapping)}
        while cursor < len(paths):
            state = queue._state(work_id)
            if state.get("cancellation", {}).get("requested"):
                with _lock(queue.lock_path):
                    state = queue._state(work_id)
                    state.update(state="cancelled", reason_code=REASON_CANCELLED, lease=None)
                    _write(state_path, state)
                    queue._receipt(state, "cancelled", REASON_CANCELLED)
                return 0
            chunk_start = time.perf_counter()
            for relative in paths[cursor : cursor + max(1, chunk_size)]:
                path = repo / relative
                stat = path.stat()
                old = prior.get(relative)
                if (
                    old
                    and int(old.get("size", -1)) == stat.st_size
                    and int(old.get("mtime_ns", -2)) == stat.st_mtime_ns
                ):
                    record, reused = dict(old), reused + 1
                else:
                    record, read_bytes = _record(repo, relative)
                    io_bytes += read_bytes
                prior[relative] = record
                scanned += 1
            cursor = min(len(paths), cursor + max(1, chunk_size))
            chunks += 1
            queue.checkpoint(
                work_id,
                token,
                cursor,
                len(paths),
                sorted(prior.values(), key=lambda row: row["path"]),
                scanned,
                reused,
                chunks,
                io_bytes,
                start_wall,
                start_cpu,
                lease_seconds,
            )
            if stop_after_chunks is not None and chunks >= stop_after_chunks:
                return 75
            _throttle(chunk_start, io_bytes)
        records = sorted(prior.values(), key=lambda row: row["path"])
        final_tree = _tree(repo)
        if expected and final_tree and expected != final_tree:
            raise BackgroundWorkError(REASON_STALE_TREE, final_tree)
        candidate_id = _sha({"work_id": work_id, "tree": expected, "records": _sha(records)})
        candidate = {
            "schema": BACKGROUND_SCHEMA,
            "work_id": work_id,
            "generation_id": candidate_id,
            "base_generation_id": claimed["base_generation_id"],
            "repository": claimed["repository"],
            "requested_scope": claimed["requested_scope"],
            "mapper_version": claimed["mapper_version"],
            "records": records,
            "records_digest": _sha(records),
            "scanned_count": len(records),
            "complete": True,
            "created_at": _now(),
        }
        validate_candidate(candidate, work_id)
        _write(queue.generations / f"{candidate_id}.json", candidate)
        with _lock(queue.lock_path):
            state = queue._state(work_id)
            state.update(
                state="completed",
                reason_code=REASON_COMPLETED,
                candidate_generation_id=candidate_id,
                updated_at=_now(),
            )
            state["metrics"] = _metrics(start_wall, start_cpu, scanned, reused, len(paths), chunks, io_bytes)
            _write(state_path, state)
            queue._receipt(state, "completed", REASON_COMPLETED)
        queue.promote(work_id, candidate, token)
        return 0
    except BackgroundWorkError as error:
        with _lock(queue.lock_path):
            state = queue._state(work_id)
            state.update(state="failed", reason_code=error.reason_code, lease=None, updated_at=_now())
            state.setdefault("reason_codes", []).append(error.reason_code)
            _write(state_path, state)
            queue._receipt(state, "failed", error.reason_code)
        return 1


def enqueue_background_work(
    cache_root: str | os.PathLike[str], repo_key: str, payload: Mapping[str, Any], start: bool = True
) -> dict[str, Any]:
    return BackgroundQueue(cache_root, repo_key).enqueue(payload, start=start)


def background_paths(cache_root: str | os.PathLike[str], repo_key: str, work_id: str) -> tuple[Path, Path]:
    queue = BackgroundQueue(cache_root, repo_key)
    return queue._path(work_id), queue.queue_log


def run_background_worker(work_id: str, cache_root: str | os.PathLike[str]) -> int:
    return run_worker(work_id, cache_root)


def run_background_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-mapper background")
    parser.add_argument("command", choices=("status", "cancel", "resume", "doctor", "gc", "run"))
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--work-id", default="")
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--retention-seconds", type=float, default=3600)
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    cache = Path(
        args.cache_root
        or os.environ.get(
            "SIMPLICIO_MAPPER_SCOPED_CACHE", str(Path.home() / ".simplicio-loop/mapper/scoped-context-cache")
        )
    ).expanduser()
    if args.command == "run":
        if not args.work_id:
            parser.error("run requires --work-id")
        return run_background_worker(args.work_id, cache)
    queue = BackgroundQueue.for_repo(args.root, cache)
    if args.command == "status":
        result = queue.status(args.work_id or None)
    elif args.command == "cancel":
        if not args.work_id:
            parser.error("cancel requires --work-id")
        result = queue.cancel(args.work_id)
    elif args.command == "resume":
        if not args.work_id:
            parser.error("resume requires --work-id")
        result = queue.resume(args.work_id, start=not args.no_start)
    elif args.command == "doctor":
        result = queue.doctor()
    else:
        result = queue.gc(args.retention_seconds)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    parser.add_argument("--cache-root", required=True)
    args = parser.parse_args()
    raise SystemExit(run_worker(args.worker, args.cache_root))
