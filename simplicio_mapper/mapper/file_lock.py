"""Generalized cross-process single-flight file lock (issue #236, ADR-008 section 4).

This is the same mature lock implementation that used to live only inside
``simplicio_mapper.cli._index_engine`` (``_acquire_index_lock`` /
``_inspect_index_lock`` / ``_release_index_lock``): ``O_CREAT|O_EXCL``
atomic create, a JSON record carrying ``schema``/``pid``/
``process_start_identity`` (PID-reuse protection via
:mod:`simplicio_mapper.mapper.process_liveness`), ``owner_token``,
``acquired_at``/``heartbeat_at``, a configurable TTL
(``SIMPLICIO_MAPPER_LOCK_TTL_SECONDS``), and safe reclamation of a dead
owner/reused-PID/expired-TTL/malformed lock -- never a live owner's lock.

ADR-008 section 4 ("Lock single-flight -- reaproveitar, nao reinventar")
explicitly calls for generalizing this mechanism to accept an arbitrary
``lock_path`` and an ``operation`` label (the existing index lock already
writes ``"operation": "index"``; the canonical-map builder needs a second
value, ``"operation": "canonical-build"``) instead of writing a second lock
implementation from scratch.

This module is the extraction point: ``_index_engine.py``'s
``_acquire_index_lock``/``_inspect_index_lock`` are now thin,
behavior-preserving wrappers around :func:`acquire_lock_at` /
:func:`inspect_lock_at` here, and
:mod:`simplicio_mapper.mapper.canonical_builder` (issue #236 gap #1) imports
these functions directly for the canonical-build lock. The extraction lives
in ``simplicio_mapper.mapper`` rather than ``simplicio_mapper.cli`` for the
same reason ``process_liveness.py`` does (see that module's docstring):
``simplicio_mapper.mapper`` must never import from ``simplicio_mapper.cli``
-- the dependency only runs the other way.

No behavior change versus the previous inline versions in ``_index_engine.py``
for the ``operation="index"`` case -- every existing test in
``tests/python/test_lock_recovery.py`` continues to exercise the exact same
code path through the preserved wrapper functions.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field

from .process_liveness import process_is_alive, process_start_token

#: Current-format schema string written by :func:`acquire_lock_at`.
LOCK_SCHEMA = "simplicio.mapper-index-lock/v1"

#: Pre-v1 schema string tolerated by :func:`inspect_lock_at` for lock files
#: written before the JSON-record format existed.
LEGACY_LOCK_SCHEMA = "simplicio.index-lock/v1"

#: Same environment override used by every single-flight lock in this
#: project -- ADR-008 section 4 explicitly asks for "the same TTL/heartbeat
#: semantics as the index lock", not a second, independently-tunable knob.
LOCK_TTL_ENV = "SIMPLICIO_MAPPER_LOCK_TTL_SECONDS"
DEFAULT_LOCK_TTL_SECONDS = 6 * 60 * 60
MALFORMED_LOCK_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class LockHandle:
    path: str
    token: str
    # ``lock_acquired`` is the success-path counterpart to the reclaim reason
    # codes returned by ``inspect_lock_at`` below (issue #201's proposed
    # contract lists it as one of the minimum reason codes). Callers that want
    # to surface acquisition as evidence in CLI output can read it straight
    # off the handle instead of re-deriving it.
    reason_code: str = "lock_acquired"
    #: Free-form extra fields merged into the lock record at acquire time
    #: (e.g. ``root_fingerprint`` for the index lock). Not required for the
    #: lock's own correctness -- purely an audit trail.
    extra: dict = field(default_factory=dict)


def _lock_reason(reason: str) -> str:
    return {
        "live": "lock_live_owner",
        "legacy_live": "lock_live_owner",
        "dead_process": "lock_dead_owner_reclaimed",
        "pid_reused": "lock_dead_owner_reclaimed",
        "ttl_expired": "lock_expired_reclaimed",
        "malformed": "lock_malformed_reclaimed",
        "legacy": "lock_legacy_reclaimed",
        "owner_mismatch": "lock_owner_mismatch",
    }.get(reason, reason)


def _lock_ttl_seconds() -> float:
    raw = os.environ.get(LOCK_TTL_ENV)
    if raw is None:
        return float(DEFAULT_LOCK_TTL_SECONDS)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(DEFAULT_LOCK_TTL_SECONDS)


def _mapper_version() -> str:
    try:
        from importlib.metadata import version

        return version("simplicio-mapper")
    except Exception:  # noqa: BLE001 - source checkouts may not be installed
        return "unknown"


def _lock_file_snapshot(path: str) -> tuple[bytes, tuple[int, int, int]] | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        stat = os.stat(path)
    except OSError:
        return None
    return raw, (stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0))


def _remove_lock_snapshot(path: str, snapshot: tuple[bytes, tuple[int, int, int]]) -> bool:
    if _lock_file_snapshot(path) != snapshot:
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def inspect_lock_at(lock_path: str, *, recover: bool = False) -> dict:
    """Classify the lock at ``lock_path`` and optionally reclaim a proven orphan.

    Identical semantics to the pre-extraction ``_inspect_index_lock``: never
    reclaims a live owner solely because its heartbeat/TTL looks old, only
    when the owner is provably dead (process gone or PID reused) or the
    record itself is malformed past a short grace window.
    """
    snapshot = _lock_file_snapshot(lock_path)
    if snapshot is None:
        return {"exists": False, "active": False, "recovered": False, "reason": "absent"}
    raw, stat_identity = snapshot
    age = max(0.0, time.time() - (stat_identity[0] / 1_000_000_000))
    stripped = raw.decode("utf-8", errors="replace").strip()
    record: dict | None = None
    legacy = False
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            record = parsed
        elif isinstance(parsed, int) and parsed > 0 and stripped.isdigit():
            legacy = True
            record = {"pid": parsed}
    except ValueError:
        if stripped.isdigit():
            legacy = True
            record = {"pid": int(stripped)}

    reason = "malformed"
    recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS
    pid = None
    if record is not None:
        pid = record.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            reason = "malformed"
            recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS
        else:
            alive = process_is_alive(pid)
            acquired_at = record.get("acquired_at")
            process_start = record.get("process_start_identity", record.get("process_start"))
            record_age = age
            if isinstance(acquired_at, (int, float)):
                record_age = max(0.0, time.time() - float(acquired_at))
            if not alive:
                reason = "dead_process"
                recoverable = True
            elif record_age > _lock_ttl_seconds():
                # Report expiration for operators, but retain the lock while
                # the owner is alive. Reclaiming an active lock can permit two
                # operations to mutate the same target concurrently.
                reason = "ttl_expired"
                recoverable = False
            elif legacy:
                reason = "legacy_live"
                recoverable = False
            elif (
                record.get("schema") not in (LOCK_SCHEMA, LEGACY_LOCK_SCHEMA)
                or not isinstance(record.get("owner_token", record.get("token")), str)
                or not record.get("owner_token", record.get("token"))
                or not isinstance(process_start, str)
            ):
                reason = "malformed"
                # A partially-written record can still contain a valid PID.
                # Never reclaim it while that process is alive; malformed
                # metadata is not evidence that ownership ended.
                recoverable = age >= MALFORMED_LOCK_GRACE_SECONDS and not alive
            else:
                actual_start = process_start_token(pid)
                expected_start = process_start
                if (
                    actual_start is not None
                    and expected_start != "unknown"
                    and actual_start != expected_start
                ):
                    reason = "pid_reused"
                    recoverable = True
                else:
                    reason = "live"
                    # A live owner is never reclaimed solely because its
                    # heartbeat is old. This is the critical cross-platform
                    # safety invariant; TTL only applies once the owner is
                    # proven dead or unresolvable.
                    recoverable = False

    recovered = False
    if recover and recoverable:
        recovered = _remove_lock_snapshot(lock_path, snapshot)
        if not recovered:
            # A concurrent owner replaced the observed lock; never unlink it.
            return inspect_lock_at(lock_path, recover=False)
    return {
        "exists": not recovered,
        "active": not recovered and not recoverable,
        "recovered": recovered,
        "reason": reason,
        "reason_code": _lock_reason(reason),
        "pid": pid,
        "age_seconds": round(age, 3),
        "legacy": legacy,
        "owner": record if isinstance(record, dict) else None,
    }


def acquire_lock_at(
    lock_path: str,
    *,
    operation: str,
    extra_fields: dict | None = None,
) -> LockHandle | None:
    """Acquire (or fail to acquire) the single-flight lock at ``lock_path``.

    ``operation`` is stamped into the lock record's ``"operation"`` field
    (``"index"`` for the pre-existing per-worktree index lock,
    ``"canonical-build"`` for the cross-worktree canonical-manifest builder
    lock) -- the only per-caller variation; everything else (PID-reuse
    protection, TTL, dead-owner reclaim) is identical for every operation.
    """
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    extra = dict(extra_fields or {})
    for _attempt in range(4):
        token = secrets.token_hex(16)
        record = {
            "schema": LOCK_SCHEMA,
            "pid": os.getpid(),
            "process_start": process_start_token(os.getpid()) or "unknown",
            "token": token,
            "acquired_at": time.time(),
            # Canonical v1 fields. The short aliases above remain for readers
            # of the pre-0.21 lock format.
            "process_start_identity": process_start_token(os.getpid()) or "unknown",
            "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown",
            "created_at": time.time(),
            "heartbeat_at": time.time(),
            "owner_token": token,
            "mapper_version": _mapper_version(),
            "operation": operation,
            **extra,
        }
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            status = inspect_lock_at(lock_path, recover=True)
            if status["active"]:
                return None
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                os.unlink(lock_path)
            except OSError:
                pass
            raise
        return LockHandle(path=lock_path, token=token, extra=extra)
    return None


def release_lock_at(lock: LockHandle | None) -> None:
    """Release ``lock`` iff its ``token`` still matches the on-disk owner.

    A no-op (never raises, never removes someone else's lock) when the file
    is already gone or a different owner has since replaced it -- the same
    "only the true owner may unlink" invariant as the pre-extraction
    ``_release_index_lock``.
    """
    if not lock:
        return
    snapshot = _lock_file_snapshot(lock.path)
    if snapshot is None:
        return
    try:
        record = json.loads(snapshot[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return
    if not isinstance(record, dict) or record.get("owner_token", record.get("token")) != lock.token:
        return
    _remove_lock_snapshot(lock.path, snapshot)


__all__ = [
    "LOCK_SCHEMA",
    "LEGACY_LOCK_SCHEMA",
    "LOCK_TTL_ENV",
    "DEFAULT_LOCK_TTL_SECONDS",
    "MALFORMED_LOCK_GRACE_SECONDS",
    "LockHandle",
    "acquire_lock_at",
    "inspect_lock_at",
    "release_lock_at",
]
