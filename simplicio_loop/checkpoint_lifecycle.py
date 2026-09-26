from __future__ import annotations

import hashlib
import json
import re
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA = "simplicio.loop.checkpoint-lifecycle/v1"
FANIN_SCHEMA = "simplicio.loop.adaptive-fan-in/v1"
ACTIVE_STATES = frozenset({"ORIENTED", "PLANNED", "DRY_RUN", "APPLIED", "VERIFY_FOCUSED", "VERIFY_FULL"})
TERMINAL_STATES = frozenset({"READY_TO_PROMOTE", "PROMOTED", "HELD", "CANCELLED", "SEALED"})


class LifecycleError(ValueError):
    pass


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _require(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    risk: float
    uncertainty: float
    stalled: bool = False


_PATH_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def validate_path_component(value: Any, name: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise LifecycleError(f"unsafe {name}")
    if not _PATH_COMPONENT_RE.fullmatch(value) or value in {".", ".."}:
        raise LifecycleError(f"unsafe {name}")
    return value


def validate_candidate_id(value: Any) -> str:
    return validate_path_component(value, "candidate_id")


class CheckpointLifecycle:
    """Owns immutable base + isolated candidate overlays for one resumable attempt.

    LangGraph-aligned durable-execution practices (without depending on LangGraph):

    - **thread_id** — one resumable conversation/work lineage (``task_id/attempt_id``).
    - **checkpoint per superstep** — each ``checkpoint()`` is an immutable snapshot
      with digest lineage via ``previous_digest`` (replay-safe identity).
    - **no concurrent writers on the same thread** — overlays + leases + promotion fence.
    - **side effects are receipt-gated** — callers must attach idempotent receipt digests;
      replaying a checkpoint must not re-apply un-receipted mutations.
    - **HITL / interrupt** — terminal states HELD/CANCELLED and Action Gate outside this
      module map to LangGraph ``interrupt`` before dangerous promote/apply steps.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        task_id: str,
        attempt_id: str,
        source_commit: str,
        mapper_generation: str,
        base_path: str | Path,
    ) -> None:
        self.root = Path(root)
        self.task_id = validate_path_component(task_id, "task_id")
        self.attempt_id = validate_path_component(attempt_id, "attempt_id")
        self.source_commit = _require(source_commit, "source_commit")
        self.mapper_generation = _require(mapper_generation, "mapper_generation")
        self.base_path = Path(base_path).resolve()
        self.attempt = self.root / self.task_id / self.attempt_id
        self.overlays = self.attempt / "overlays"
        self.checkpoints = self.attempt / "checkpoints"
        self.cancellations = self.attempt / "cancellations"
        self.leases = self.attempt / "leases"
        self.fence_path = self.attempt / "promotion-fence.json"

    @property
    def thread_id(self) -> str:
        """LangGraph-compatible thread key for durable resume (task/attempt lineage)."""
        return f"{self.task_id}/{self.attempt_id}"

    def create_overlay(self, candidate_id: str) -> Path:
        candidate = validate_candidate_id(candidate_id)
        target = self.overlays / candidate
        if target.exists():
            marker = self._read_marker(target)
            if marker["base_path"] != str(self.base_path):
                raise LifecycleError("overlay base mismatch")
            return target
        target.mkdir(parents=True)
        marker = {
            "schema": SCHEMA,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "candidate_id": candidate,
            "base_path": str(self.base_path),
            "base_read_only": True,
        }
        marker["digest"] = _digest(marker)
        _write_json(target / "overlay.json", marker)
        return target

    def _read_marker(self, overlay: Path) -> dict[str, Any]:
        try:
            marker = json.loads((overlay / "overlay.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError("overlay marker missing or corrupt") from exc
        supplied = marker.pop("digest", None)
        if supplied != _digest(marker):
            raise LifecycleError("overlay marker digest mismatch")
        marker["digest"] = supplied
        return marker

    def checkpoint(
        self,
        candidate_id: str,
        shard_id: str,
        state: str,
        *,
        receipts: Sequence[str] = (),
        work_units: int = 0,
        previous_digest: str | None = None,
    ) -> dict[str, Any]:
        candidate = validate_candidate_id(candidate_id)
        shard = validate_path_component(shard_id, "shard_id")
        normalized_state = _require(state, "state").upper()
        if normalized_state not in ACTIVE_STATES | TERMINAL_STATES:
            raise LifecycleError(f"unsafe checkpoint state: {normalized_state}")
        overlay = self.create_overlay(candidate)
        receipt_list = sorted(set(map(str, receipts)))
        # LangGraph practice: side-effect supersteps must carry receipts so resume
        # does not re-fire non-idempotent work. APPLIED without receipts is rejected.
        if normalized_state == "APPLIED" and not receipt_list:
            raise LifecycleError(
                "APPLIED checkpoints require non-empty receipts (idempotent side-effect evidence)"
            )
        value: dict[str, Any] = {
            "schema": SCHEMA,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            # Interop with LangGraph-style durable runners / external tracers.
            "thread_id": self.thread_id,
            "candidate_id": candidate,
            "shard_id": shard,
            "state": normalized_state,
            "source_commit": self.source_commit,
            "mapper_generation": self.mapper_generation,
            "base_path": str(self.base_path),
            "overlay_path": str(overlay.resolve()),
            "receipts": receipt_list,
            "work_units": max(0, int(work_units)),
            "previous_digest": previous_digest,
            "created_ns": time.time_ns(),
            "durable_execution": {
                "model": "checkpoint-per-superstep",
                "side_effects": "receipt-gated",
                "resume_key": self.thread_id,
                "langgraph_alignment": "practices-only-no-runtime-dependency",
            },
        }
        value["checkpoint_id"] = _digest(
            {
                key: value[key]
                for key in (
                    "task_id",
                    "attempt_id",
                    "thread_id",
                    "candidate_id",
                    "shard_id",
                    "state",
                    "previous_digest",
                    "receipts",
                )
            }
        )
        value["digest"] = _digest(value)
        _write_json(self.checkpoints / candidate / f"{shard}.json", value)
        return value

    def verify(self, value: Mapping[str, Any]) -> dict[str, Any]:
        item = dict(value)
        supplied = item.pop("digest", None)
        if item.get("schema") != SCHEMA or supplied != _digest(item):
            raise LifecycleError("checkpoint digest mismatch")
        item["digest"] = supplied
        expected = {
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "source_commit": self.source_commit,
            "mapper_generation": self.mapper_generation,
            "base_path": str(self.base_path),
        }
        if any(item.get(key) != value for key, value in expected.items()):
            raise LifecycleError("stale checkpoint identity")
        overlay = Path(_require(item.get("overlay_path"), "overlay_path"))
        marker = self._read_marker(overlay)
        if marker["candidate_id"] != item.get("candidate_id"):
            raise LifecycleError("candidate overlay mismatch")
        return item

    def load(self, candidate_id: str, shard_id: str) -> dict[str, Any]:
        path = self.checkpoints / validate_candidate_id(candidate_id) / f"{validate_path_component(shard_id, 'shard_id')}.json"
        try:
            return self.verify(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError("checkpoint missing or corrupt") from exc

    def cancel(
        self,
        candidate_ids: Iterable[str],
        *,
        reason: str,
        cancel_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        cancelled: list[str] = []
        errors: list[dict[str, str]] = []
        for raw in sorted(set(candidate_ids)):
            candidate = validate_candidate_id(raw)
            try:
                if cancel_callback:
                    cancel_callback(candidate)
                receipt = {
                    "schema": SCHEMA,
                    "task_id": self.task_id,
                    "attempt_id": self.attempt_id,
                    "candidate_id": candidate,
                    "state": "CANCELLED",
                    "reason": _require(reason, "reason"),
                    "created_ns": time.time_ns(),
                }
                receipt["digest"] = _digest(receipt)
                _write_json(self.cancellations / f"{candidate}.json", receipt)
                cancelled.append(candidate)
            except Exception as exc:
                errors.append({"candidate_id": candidate, "error": str(exc)})
        status = "CANCELLED" if not errors else "HELD"
        return {"schema": SCHEMA, "status": status, "cancelled": cancelled, "errors": errors}

    def fanin(
        self,
        specs: Sequence[CandidateSpec],
        *,
        expected_shards: Sequence[str],
        risk_threshold: float = 0.65,
        uncertainty_threshold: float = 0.55,
        max_candidates: int = 3,
    ) -> dict[str, Any]:
        if not specs:
            raise LifecycleError("fan-in requires at least one candidate")
        ordered = sorted(specs, key=lambda item: item.candidate_id)
        primary = ordered[0]
        expand = primary.stalled or primary.risk >= risk_threshold or primary.uncertainty >= uncertainty_threshold
        selected = ordered[: min(max_candidates, len(ordered))] if expand else [primary]
        shards = sorted(set(map(str, expected_shards)))
        if not shards:
            raise LifecycleError("expected_shards must not be empty")
        candidates: list[dict[str, Any]] = []
        for spec in selected:
            values = [self.load(spec.candidate_id, shard) for shard in shards]
            unsafe_states = sorted({
                str(item["state"]) for item in values
                if item["state"] != "READY_TO_PROMOTE"
            })
            if unsafe_states:
                raise LifecycleError(
                    f"candidate {spec.candidate_id} is not promotion-ready: {unsafe_states}")
            if len({item["digest"] for item in values}) != len(values):
                raise LifecycleError("duplicate or replayed checkpoint")
            score = (
                sum(len(item["receipts"]) for item in values),
                -spec.risk,
                -spec.uncertainty,
                -sum(item["work_units"] for item in values),
            )
            candidates.append({"candidate_id": spec.candidate_id, "score": score, "checkpoints": values})
        winner = max(candidates, key=lambda item: item["score"])
        losers = [item["candidate_id"] for item in candidates if item is not winner]
        result: dict[str, Any] = {
            "schema": FANIN_SCHEMA,
            "status": "READY",
            "fanout_reason": (
                "stall" if primary.stalled
                else "risk" if primary.risk >= risk_threshold
                else "uncertainty" if primary.uncertainty >= uncertainty_threshold
                else "single_candidate_default"
            ),
            "selected_candidates": [item["candidate_id"] for item in candidates],
            "winner_id": winner["candidate_id"],
            "loser_ids": losers,
            "reused_work_units": sum(item["work_units"] for item in winner["checkpoints"]),
        }
        result["digest"] = _digest(result)
        return result

    def seal_winner(self, fanin: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(fanin)
        supplied = value.pop("digest", None)
        if value.get("schema") != FANIN_SCHEMA or supplied != _digest(value):
            raise LifecycleError("fan-in digest mismatch")
        if value.get("status") != "READY":
            raise LifecycleError("fan-in is not ready")
        fence: dict[str, Any] = {
            "schema": SCHEMA,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "winner_id": _require(value.get("winner_id"), "winner_id"),
            "fan_in_digest": supplied,
            "status": "SEALED",
        }
        fence["digest"] = _digest(fence)
        if self.fence_path.exists():
            existing = json.loads(self.fence_path.read_text(encoding="utf-8"))
            if existing == fence:
                return existing
            raise LifecycleError("promotion fence already sealed by another winner")
        try:
            _write_json_exclusive(self.fence_path, fence)
        except FileExistsError:
            existing = json.loads(self.fence_path.read_text(encoding="utf-8"))
            if existing == fence:
                return existing
            raise LifecycleError("promotion fence already sealed by another winner")
        return fence

    def converge(
        self,
        specs: Sequence[CandidateSpec],
        *,
        expected_shards: Sequence[str],
        cancel_callback: Callable[[str], None] | None = None,
        risk_threshold: float = 0.65,
        uncertainty_threshold: float = 0.55,
        max_candidates: int = 3,
    ) -> dict[str, Any]:
        fanin = self.fanin(
            specs,
            expected_shards=expected_shards,
            risk_threshold=risk_threshold,
            uncertainty_threshold=uncertainty_threshold,
            max_candidates=max_candidates,
        )
        fence = self.seal_winner(fanin)
        cancellation = self.cancel(
            fanin["loser_ids"],
            reason=f"winner:{fanin['winner_id']}",
            cancel_callback=cancel_callback,
        )
        return {
            "schema": SCHEMA,
            "status": "SEALED" if cancellation["status"] == "CANCELLED" else "HELD",
            "fan_in": fanin,
            "fence": fence,
            "cancellation": cancellation,
        }

    def converge_selected(
        self,
        *,
        winner_id: str,
        candidate_ids: Sequence[str],
        shard_id: str,
        cancel_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        winner = _require(winner_id, "winner_id")
        candidates = sorted(set(validate_candidate_id(value) for value in candidate_ids))
        if winner not in candidates:
            raise LifecycleError("selected winner is not a candidate")
        checkpoints = [self.load(candidate, shard_id) for candidate in candidates]
        by_candidate = {item["candidate_id"]: item for item in checkpoints}
        if by_candidate[winner]["state"] != "READY_TO_PROMOTE":
            raise LifecycleError("selected winner is not verified")
        if any(item["state"] not in TERMINAL_STATES for item in checkpoints):
            raise LifecycleError("candidate has non-terminal shard")
        fanin: dict[str, Any] = {
            "schema": FANIN_SCHEMA,
            "status": "READY",
            "fanout_reason": "coordinator_selected",
            "selected_candidates": candidates,
            "winner_id": winner,
            "loser_ids": [candidate for candidate in candidates if candidate != winner],
            "reused_work_units": by_candidate[winner]["work_units"],
            "checkpoint_digests": [by_candidate[candidate]["digest"] for candidate in candidates],
        }
        fanin["digest"] = _digest(fanin)
        fence = self.seal_winner(fanin)
        cancellation = self.cancel(
            fanin["loser_ids"],
            reason=f"winner:{winner}",
            cancel_callback=cancel_callback,
        )
        return {
            "schema": SCHEMA,
            "status": "SEALED" if cancellation["status"] == "CANCELLED" else "HELD",
            "fan_in": fanin,
            "fence": fence,
            "cancellation": cancellation,
        }

    def lease(self, candidate_id: str, *, expires_ns: int) -> dict[str, Any]:
        candidate = validate_candidate_id(candidate_id)
        value = {
            "schema": SCHEMA,
            "candidate_id": candidate,
            "attempt_id": self.attempt_id,
            "expires_ns": int(expires_ns),
            "status": "ACTIVE",
        }
        value["digest"] = _digest(value)
        _write_json(self.leases / f"{candidate}.json", value)
        return value

    def gc(self, *, retention_ns: int, now_ns: int | None = None, apply: bool = False) -> dict[str, Any]:
        now = time.time_ns() if now_ns is None else int(now_ns)
        protected: set[str] = set()
        for path in self.leases.glob("*.json"):
            try:
                lease = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            supplied = lease.pop("digest", None)
            if supplied == _digest(lease) and lease.get("status") == "ACTIVE" and int(lease.get("expires_ns", 0)) > now:
                protected.add(str(lease.get("candidate_id")))
        eligible: list[str] = []
        for receipt_path in sorted(self.cancellations.glob("*.json")):
            candidate = receipt_path.stem
            age_ns = max(0, now - receipt_path.stat().st_mtime_ns)
            if candidate in protected or age_ns < max(0, int(retention_ns)):
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            supplied = receipt.pop("digest", None)
            if supplied != _digest(receipt) or receipt.get("state") != "CANCELLED":
                continue
            eligible.append(candidate)
        removed: list[str] = []
        if apply:
            for candidate in eligible:
                overlay = self.overlays / candidate
                checkpoints = self.checkpoints / candidate
                cancellation = self.cancellations / f"{candidate}.json"
                if overlay.exists():
                    shutil.rmtree(overlay, ignore_errors=False)
                if checkpoints.exists():
                    shutil.rmtree(checkpoints, ignore_errors=False)
                cancellation.unlink(missing_ok=True)
                (self.leases / f"{candidate}.json").unlink(missing_ok=True)
                removed.append(candidate)
        return {
            "schema": SCHEMA,
            "status": "GC_APPLIED" if apply else "DRY_RUN",
            "eligible": eligible,
            "protected": sorted(protected),
            "removed": removed,
        }
